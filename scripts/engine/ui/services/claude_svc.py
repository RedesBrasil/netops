#!/usr/bin/env python3
"""Sessão Claude Code sobre WebSocket — ponte entre o `claude-agent-sdk` e a UI.

⚠ EXECUÇÃO DE COMANDO ARBITRÁRIO + EDIÇÃO DE ARQUIVOS. Cada conexão abre um
`ClaudeSDKClient` (que dispara um subprocesso `claude`) rodando COMO O USUÁRIO DO
SERVIDOR, com `cwd` = NETOPS_ROOT e herdando AGENTS.md/skills/agentes do projeto.
Por isso só liga com `--enable-claude` (default DESLIGADO) e nunca em `--read-only`
(ver routers/claude.py e server.py).

Espelha o desenho do terminal web (routers/terminal.py): a auth do handshake é feita
À MÃO no router, e aqui rodamos duas tarefas asyncio — uma lê o WebSocket (turnos do
usuário, troca de modo, respostas de permissão, interromper) e outra bombeia as
mensagens do SDK de volta como JSON. A autenticação do `claude` reaproveita o login de
assinatura já existente (~/.claude/.credentials.json) — o SDK herda o HOME do processo.

PERSISTÊNCIA (--enable-claude-persist; o start.sh liga por padrão, NETOPS_UI_CLAUDE_PERSIST=0 desliga). Com a flag LIGADA, a sessão
DESACOPLA do socket: se a aba dorme/entra em standby e o WebSocket cai, o agente NÃO é
morto — termina o turno e o SDK grava tudo no transcript em disco (SEM buffer na RAM).
Ao voltar, a aba RE-ANEXA à sessão viva (e recarrega o que faltou do disco). O dono é
validado por um cookie HttpOnly (anti-sequestro); os limites são ESTÁTICOS (teto de
sessões + carência + timeout de pergunta). Com a flag DESLIGADA tudo isto fica inerte e
o comportamento é o original (vida do agente = vida do socket). Ver o diário de fixes.

Protocolo (JSON nos dois sentidos) — ver scripts/engine/ui/static/js/pages/claude.js:
  cliente -> servidor:
    {"type":"prompt","text":...,"queue":bool}         turno do usuário (inclui /slash). Com turno
                                                      em andamento: queue=false (padrão) manda JÁ —
                                                      o CLI absorve no turno atual; queue=true guarda
                                                      na FILA e só envia quando o turno terminar
    {"type":"queue_remove","id":...}                  tira um item da fila
    {"type":"queue_send_now","id":...}                tira da fila e manda imediatamente
    {"type":"queue_move","id":...,"to":int}           reordena: põe o item na posição `to` (0 = próximo)
    {"type":"queue_add","texts":[...]}                devolve à fila o que a ABA guardou (localStorage)
                                                      quando o servidor perdeu a dele; NÃO despacha na
                                                      hora — roda no fim do próximo turno ou via ⚡
    {"type":"set_mode","mode":...}                    troca o permission_mode em tempo real
    {"type":"set_model","model":...}                  troca o modelo (None = padrão)
    {"type":"permission","id":...,"decision":"allow|deny","updated_input":{...},"message":...}
    {"type":"interrupt"}                              aborta o turno atual
    {"type":"bye"}                                    fechamento DELIBERADO (encerra a sessão viva;
                                                      um drop por standby NÃO manda isto -> desanexa)
  servidor -> cliente:
    {"type":"system","subtype":...,"data":{...}}      init traz session_id/model/slash_commands
    {"type":"text_delta","text":...}                  streaming do texto do assistente
    {"type":"thinking_delta","text":...}              streaming do "pensamento"
    {"type":"tool_use","id":..,"name":..,"input":{...}}
    {"type":"tool_result","tool_use_id":..,"content":..,"is_error":bool}
    {"type":"assistant_end"}                           fim de uma mensagem do assistente
    {"type":"permission_request","id":..,"tool":..,"input":{...},"context":{...}}
    {"type":"mode_changed","mode":...}
    {"type":"reattached","busy":bool}                  re-anexou a uma sessão viva (persist)
    {"type":"queue","items":[{"id":..,"text":..}]}     estado da fila (a cada mudança e no re-anexo)
    {"type":"queue","items":[],"fresh":true}           sessão NOVA neste socket (fila do servidor vazia
                                                      de verdade): a aba pode devolver o cache dela
    {"type":"queue_dispatched","id":..,"text":..}      item da fila virou turno (UI mostra a bolha)
    {"type":"queue_restored","items":[...]}            turno interrompido/com erro: a fila NÃO roda
                                                      sozinha — os textos voltam p/ a caixa
    {"type":"result","session_id":..,"cost_usd":..,"usage":{...},"is_error":bool,"result":..}
    {"type":"error","detail":...}
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import secrets
import shutil
import time
from collections import deque
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

import deps
from services import claude_models, claude_prefs

# Importado de forma preguiçosa para não quebrar a UI quando o SDK não está instalado
# (instalação headless sem `pip install claude-agent-sdk`). O router checa is_available().
try:  # noqa: SIM105
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookMatcher,
        PermissionResultAllow,
        PermissionResultDeny,
        ResultMessage,
        StreamEvent,
        SystemMessage,
        TextBlock,
        ThinkingBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
    )
    _SDK_OK = True
except ImportError:  # pragma: no cover - depende da instalação
    _SDK_OK = False

# Modos expostos na UI (todos, incluindo bypass — decisão do projeto). 'auto' fica de fora
# (classificador ainda específico do TS) — slash `/model`/`/permissions` cobre o resto.
VALID_MODES = ("plan", "default", "acceptEdits", "dontAsk", "bypassPermissions")
_TOOL_RESULT_MAX = 8000  # trunca saída de ferramenta p/ não inundar a UI
# stderr do subprocesso `claude` — antes era descartado (cegava o diagnóstico). Vai p/ um log
# dedicado (não polui o console.log) e alimenta o erro mostrado na UI. Ver ClaudeWebSession._on_stderr.
_AGENT_LOG = deps.RUNS_DIR / "claude" / "agent-stderr.log"
# Nunca gravar segredo em texto puro (regra do projeto): redige tokens que porventura vazem no stderr.
_SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_-]{6,}|Bearer\s+[A-Za-z0-9._-]{8,}|eyJ[A-Za-z0-9._-]{20,})")


def is_available() -> bool:
    """O SDK está instalado E o binário `claude` está no PATH?"""
    return _SDK_OK and bool(claude_path())


def claude_path() -> str | None:
    """Binário `claude` que a aba usa — o mesmo do agente e do login (ver claude_auth)."""
    return shutil.which("claude") or ("/usr/bin/claude" if os.path.exists("/usr/bin/claude") else None)


def _stringify(content) -> str:
    """ToolResultBlock.content pode ser str ou lista de blocos; vira texto enxuto."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                parts.append(b.get("text") or b.get("content") or json.dumps(b, default=str))
            else:
                parts.append(str(b))
        text = "\n".join(parts)
    else:
        text = str(content)
    if len(text) > _TOOL_RESULT_MAX:
        text = text[:_TOOL_RESULT_MAX] + f"\n… (truncado, +{len(text) - _TOOL_RESULT_MAX} chars)"
    return text


# --------------------------------------------------------------------------- #
# Persistência: registro de sessões vivas + donos (cookie). Tudo em memória do
# processo (uvicorn single-process), como as sessões de login. Ver deps.ServerState
# e o diário de fixes. NADA de buffer de conteúdo aqui — o disco é a fonte da verdade.
# --------------------------------------------------------------------------- #
_LIVE: dict[str, "ClaudeWebSession"] = {}   # session_id -> sessão viva (só quando persist)
_OWNERS: dict[str, dict] = {}               # token do cookie -> {"login_sid": str, "exp": epoch}
_OWNER_TTL = 12 * 3600                        # validade do cookie de dono (renovada a cada emissão)


def mint_owner(login_sid: str | None) -> str:
    """Emite um token de DONO (vai num cookie HttpOnly) amarrado à sessão de login atual.
    O `session_id` NÃO é credencial — é só índice; o re-anexo exige ESTE token."""
    _gc_owners()
    tok = secrets.token_urlsafe(32)
    _OWNERS[tok] = {"login_sid": login_sid or "", "exp": time.time() + _OWNER_TTL}
    return tok


def valid_owner(token: str | None) -> bool:
    """True se o token existe, não expirou e a sessão de login que o criou ainda vale
    (logout/restart invalida — amarra o re-anexo ao login vivo)."""
    if not token:
        return False
    o = _OWNERS.get(token)
    if not o:
        return False
    if o["exp"] <= time.time():
        _OWNERS.pop(token, None)
        return False
    if deps.auth_required() and o.get("login_sid") and not deps.auth_session_valid(o["login_sid"]):
        return False
    return True


def _gc_owners() -> None:
    now = time.time()
    for k in [k for k, v in _OWNERS.items() if v["exp"] <= now]:
        _OWNERS.pop(k, None)


def _detached_count() -> int:
    uniq = {id(s): s for s in _LIVE.values()}.values()   # a mesma sessão pode ter 2 chaves (resume/init)
    return sum(1 for s in uniq if s.ws is None and not s._closing_done)


# --------------------------------------------------------------------------- #
# RETOMADA APÓS RESTART. Reiniciar o console mata o subprocesso `claude` no meio do turno.
# Para o turno voltar SOZINHO, cada sessão persistente com turno em andamento fica anotada em
# disco (runs/claude/resume-on-restart.json) — gravado a cada início/fim de turno e mudança de
# fila, então vale até para kill -9. No startup, resume_after_restart() relança essas sessões
# (resume=<sid>) e manda um prompt de continuação; a aba re-anexa quando reconectar.
# Kill-switch: NETOPS_UI_CLAUDE_AUTORESUME=0. Limites ESTÁTICOS: idade e cadeia de retomadas.
# --------------------------------------------------------------------------- #
_RESUME_FILE = deps.RUNS_DIR / "claude" / "resume-on-restart.json"
_RESUME_MAX_AGE = 30 * 60      # seg: turno anotado há mais tempo que isso não é retomado
_RESUME_MAX_CHAIN = 2          # retomadas automáticas seguidas sem prompt humano (anti-loop)
_RESUME_DELAY = 3.0            # seg após o startup antes de relançar (deixa o console assentar)
_SHUTTING_DOWN = False         # shutdown_all em curso: teardown NÃO apaga a anotação
RESUME_PROMPT = (
    "[NetOps — retomada automática] O console web foi reiniciado enquanto você executava o turno "
    "anterior e o seu processo foi encerrado no meio. Retome a tarefa de onde parou. Antes de "
    "repetir qualquer ação, confira o estado real (um comando pode ter rodado só em parte; nunca "
    "repita alteração em equipamento sem verificar). Se o reinício foi disparado por você mesmo, "
    "apenas confirme que o console voltou (HTTP) e conclua — NÃO reinicie o console de novo."
)


def _resume_load() -> dict:
    try:
        data = json.loads(_RESUME_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _resume_save(data: dict) -> None:
    try:
        _RESUME_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _RESUME_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        os.replace(tmp, _RESUME_FILE)
    except OSError:
        pass   # best-effort: nunca derruba o agente por causa da anotação


def _resume_forget(sid: str | None) -> None:
    if not sid:
        return
    data = _resume_load()
    if data.pop(sid, None) is not None:
        _resume_save(data)


def _rlog(msg: str) -> None:
    """Diário da retomada (stdout do servidor = /tmp/netops-restart.log): cada decisão fica visível."""
    print(f"[claude-autoresume] {msg}", flush=True)


def autoresume_enabled() -> bool:
    return (os.environ.get("NETOPS_UI_CLAUDE_AUTORESUME", "1") != "0"
            and deps.STATE.enable_claude and deps.STATE.claude_persist and is_available())


async def resume_after_restart(delay: float = _RESUME_DELAY, snapshot: dict | None = None) -> list[str]:
    """Relança as sessões que estavam NO MEIO de um turno quando o console caiu. Devolve os sids
    retomados. Se a aba já reconectou (sessão viva em _LIVE), injeta o prompt nela em vez de
    abrir um segundo `claude` na mesma conversa. `snapshot` = o arquivo lido NO STARTUP, antes de
    aceitar conexões (a aba pode reconectar durante o `delay`)."""
    if delay:
        await asyncio.sleep(delay)
    data = dict(snapshot) if snapshot is not None else _resume_load()
    _rlog(f"anotadas: {len(data)} ({_RESUME_FILE})")
    if not data:
        return []
    now = time.time()
    done: list[str] = []
    for sid, e in list(data.items()):
        try:
            if not isinstance(e, dict) or not e.get("busy"):
                _rlog(f"{sid}: ociosa, ignorada")
                data.pop(sid, None)
                continue
            chain = int(e.get("chain") or 0)
            age = now - float(e.get("t") or 0)
            if age > _RESUME_MAX_AGE or chain >= _RESUME_MAX_CHAIN or not project_session_exists(sid):
                _rlog(f"{sid}: descartada (idade {age:.0f}s, cadeia {chain})")
                data.pop(sid, None)
                continue
            s = _LIVE.get(sid)
            reuse = s is not None and not s._closing_done
            if not reuse:
                if _detached_count() >= deps.STATE.claude_max_sessions:
                    _rlog(f"{sid}: teto de sessões, fica p/ o próximo start")
                    continue           # teto: fica anotada p/ um próximo start, não força
                s = ClaudeWebSession(persist=True, resume=sid, model=e.get("model") or None,
                                     effort=e.get("effort") or None)
                _LIVE[sid] = s
            await s.start()
            s._auto_chain = chain + 1
            known = {q["text"] for q in s._queue}
            for t in e.get("queue") or []:
                if isinstance(t, str) and t.strip() and t not in known and len(s._queue) < MAX_QUEUE:
                    s._queue_seq += 1
                    s._queue.append({"id": f"q{s._queue_seq}", "text": t})
            if not s._busy:
                await s._send({"type": "queue_dispatched", "id": None, "text": RESUME_PROMPT})
                await s._query(RESUME_PROMPT)
                _rlog(f"{sid}: retomada ({'aba já anexada' if reuse else 'sessão nova'}, cadeia {chain + 1})")
            else:
                _rlog(f"{sid}: já tinha turno rodando, nada a injetar")
            await s._send_queue()
            done.append(sid)
        except Exception:
            import logging  # noqa: PLC0415
            logging.getLogger("netops").exception("Claude: falha ao retomar a sessão %s após restart", sid)
            data.pop(sid, None)
            s = _LIVE.get(sid)
            if s is not None:
                await s.teardown()
    # Releitura: as sessões retomadas já regravaram a própria anotação (chain+1) no _query.
    cur = _resume_load()
    for sid in list(cur):
        if sid not in data and sid not in done:
            cur.pop(sid, None)
    _resume_save(cur)
    return done


def attach_or_create(*, owner: str, resume: str | None, model: str | None, effort: str | None = None):
    """Decide entre RE-ANEXAR a uma sessão viva e CRIAR uma nova (respeitando o teto estático).

    Retorna (session|None, how) com how em {"reattach","new","too_many","forbidden"}.
    """
    if resume and resume in _LIVE:
        s = _LIVE[resume]
        if s._closing_done:          # estava morrendo (carência disparou): cria nova
            _LIVE.pop(resume, None)
        else:
            # TAKEOVER (não "forbidden"): QUALQUER usuário autenticado pode retomar a conversa —
            # outro PC, ou o MESMO navegador após re-login (cookie novo). O acesso já é protegido
            # pelo login da senha-mestra (_ws_authorized); travar por dono deixava a sessão
            # IRRECUPERÁVEL ("erro" sem saída). Assume a posse e re-anexa; o socket antigo (se
            # ainda vivo) é fechado no attach() (supersede). Prioridade: continuar a conversa.
            if s.owner != owner:
                s.owner = owner
            return s, "reattach"
    if _detached_count() >= deps.STATE.claude_max_sessions:
        return None, "too_many"       # teto estático: recusa com mensagem (o cliente avisa)
    s = ClaudeWebSession(owner=owner, persist=True, resume=resume, model=model, effort=effort)
    if resume:
        # Registra JÁ (o init só chega no 1º turno): duas abas — ou a aba + a retomada automática
        # pós-restart — reconectando na mesma conversa caem na MESMA sessão, nunca em dois `claude`.
        _LIVE[resume] = s
    return s, "new"


async def shutdown_all() -> None:
    """Teardown de todas as sessões vivas (chamado no shutdown do uvicorn) — não deixa
    subprocesso `claude` órfão num deploy/restart. A anotação de retomada FICA no disco: é ela
    que faz o turno interrompido voltar sozinho no próximo start (resume_after_restart)."""
    global _SHUTTING_DOWN
    _SHUTTING_DOWN = True
    for s in {id(v): v for v in _LIVE.values()}.values():
        try:
            await s.teardown()
        except Exception:
            pass
    _LIVE.clear()
    _OWNERS.clear()


VALID_EFFORT = ("low", "medium", "high", "xhigh", "max")
_SEND_TIMEOUT = 10.0   # seg p/ um envio ao socket (half-open não pode travar o agente)
MAX_QUEUE = 20   # teto de mensagens na fila por sessão (estático)


class ClaudeWebSession:
    """Dirige um ClaudeSDKClient. O socket é um atributo TROCÁVEL (attach/detach): no modo
    persistente a sessão vive acima do socket; no modo clássico nasce e morre com ele."""

    def __init__(self, ws: WebSocket | None = None, *, owner: str = "",
                 persist: bool = False, resume: str | None = None, model: str | None = None,
                 effort: str | None = None):
        self._wss: list = [ws] if ws is not None else []   # MULTI-ANEXO: várias abas na mesma sessão
        self.owner = owner
        self.persist = persist
        # resume/model ficam na SESSÃO (não no socket), p/ (re)lançar igual em cada anexo.
        self._resume = resume if resume is not None else ((ws.query_params.get("resume") if ws else None) or None)
        self._model = model if model is not None else ((ws.query_params.get("model") if ws else None) or None)
        _eff = effort or (ws.query_params.get("effort") if ws else None) or None
        self._effort = _eff if _eff in VALID_EFFORT else None
        self.sid: str | None = self._resume   # vira o session_id real quando o init chega
        # Conversa retomada volta no ÚLTIMO modelo/modo usados nela; nova usa os padrões das configurações.
        saved = claude_prefs.get_session(self._resume) if self._resume else {}
        dflt = claude_prefs.defaults()
        if saved.get("model"):
            self._model = saved["model"]
        elif not self._model and dflt["default_model"] and not self._resume:
            self._model = dflt["default_model"]
        self._mode = saved.get("mode") or (dflt["default_mode"] if not self._resume else "default")
        self._last_turn: dict | None = None   # {t, usage, ctx} do último turno (re-anexo restaura cache/contexto)
        self.client: ClaudeSDKClient | None = None
        self._pending: dict[str, asyncio.Future] = {}   # id de permissão -> Future
        self._pending_payloads: dict[str, dict] = {}     # id -> card (p/ reemitir no re-anexo)
        self._counter = 0
        self._ask_tool_ids: set[str] = set()            # tool_use_ids de AskUserQuestion (suprimir card)
        self._stderr_tail: deque[str] = deque(maxlen=60)  # últimas linhas de stderr do agente (diagnóstico)
        self._busy = False               # turno em andamento? (controla a carência de teardown)
        self._closing = False            # cliente mandou "bye" (fechamento deliberado)
        self._closing_done = False       # teardown já executado (idempotência)
        self._started = False            # client já conectado?
        self._sdk_task: asyncio.Task | None = None
        self._grace_handle = None        # timer de teardown (desanexado + ocioso)
        self._ask_timers: dict[str, object] = {}  # id -> TimerHandle (timeout de pergunta)
        # FILA de prompts: guardados enquanto há turno rodando e enviados, um por vez, quando o
        # turno termina (ResultMessage). Vive na SESSÃO (não no socket) -> com persist, roda
        # mesmo com a aba fechada. Mensagem "imediata" não passa por aqui: vai direto p/ o CLI,
        # que a absorve no turno corrente (medido: um único ResultMessage p/ os dois textos).
        self._queue: list[dict] = []
        self._queue_seq = 0
        self._interrupted = False        # interrupt durante o turno -> não despacha a fila no fim
        self._restore_pending: list[dict] = []  # itens a devolver p/ a caixa quando reanexar
        self._auto_chain = 0             # retomadas automáticas seguidas (zera no prompt humano)
        # Só quem JÁ rodou turno neste processo mexe na anotação. Sem isto, a aba que reconecta
        # logo após o restart (sessão nova, ociosa) APAGAVA a anotação antes da retomada lê-la.
        self._tracked = False
        self._start_lock = asyncio.Lock()  # aba e retomada automática podem chamar start() juntas

    def _track(self) -> None:
        """Anota/remove esta sessão no arquivo de retomada pós-restart (só persist + sid conhecido)."""
        if not self.persist or not self.sid or self._closing_done or not self._tracked:
            return
        data = _resume_load()
        if self._busy or self._queue:
            data[self.sid] = {"busy": self._busy, "queue": [q["text"] for q in self._queue],
                              "model": self._model, "effort": self._effort,
                              "chain": self._auto_chain, "t": time.time()}
        elif data.pop(self.sid, None) is None:
            return
        _resume_save(data)

    @property
    def ws(self):
        """Socket mais recente (compat). Pode haver vários anexados em `_wss`."""
        return self._wss[-1] if self._wss else None

    @ws.setter
    def ws(self, value) -> None:
        self._wss = [value] if value is not None else []

    # ------------------------------------------------------------------ envio
    async def _send(self, obj: dict, only=None, skip=None) -> None:
        """Envia a TODAS as abas anexadas (ou só a `only`; `skip` exclui uma). Desanexado
        (persist): NÃO guarda nada — o transcript em disco é a verdade. Descarta."""
        targets = [only] if only is not None else list(self._wss)
        if skip is not None:
            targets = [w for w in targets if w is not skip]
        if not targets:
            return
        # default=str protege contra qualquer valor não-serializável vindo do SDK.
        data = json.dumps(obj, default=str)
        await asyncio.gather(*(self._send_one(w, data) for w in targets))

    async def _send_one(self, ws, data: str) -> None:
        try:
            # Timeout: socket half-open (celular bloqueou/sem rede, sem FIN) pode travar o drain e,
            # como o _sdk_pump envia inline, parar o agente. Estourou = solta SÓ esse socket
            # (as outras abas continuam).
            await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT)
        except asyncio.TimeoutError:
            if self.persist and ws in self._wss:
                self.detach(ws)
                try:
                    asyncio.create_task(ws.close())
                except Exception:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            pass

    def _options(self) -> "ClaudeAgentOptions":
        resume = self._resume  # retomar sessão passada
        # Escolha explícita ou Sonnet anunciado pelo MESMO CLI/provider da sessão.
        model = self._model or claude_models.default_model()
        return ClaudeAgentOptions(
            cwd=str(deps.NETOPS_ROOT),
            resume=resume,
            model=model,
            **({"effort": self._effort} if self._effort else {}),
            setting_sources=["user", "project", "local"],  # herda AGENTS.md/skills/agentes
            # O modo bypassPermissions (exposto na UI) exige DUAS condições no lançamento:
            #  1) a sessão precisa nascer com --dangerously-skip-permissions, senão o SDK recusa a
            #     troca em runtime ("session was not launched with --dangerously-skip-permissions").
            #     Passamos o flag via extra_args mas MANTEMOS permission_mode="default" — a sessão
            #     começa segura e a UI só entra em bypass quando o usuário escolhe;
            #  2) o `claude` recusa esse flag sob root/sudo (o console sobe por sudo em container).
            #     IS_SANDBOX=1 declara o ambiente isolado (LXC) e libera. Escopo mínimo: só o
            #     subprocesso `claude`. Merge com os.environ p/ preservar PATH/HOME/credenciais.
            env={**os.environ, "IS_SANDBOX": "1"},
            extra_args={"dangerously-skip-permissions": None},
            permission_mode="default",                       # seguro-mas-usável; UI troca p/ qualquer um
            include_partial_messages=True,                   # streaming de texto/pensamento
            can_use_tool=self._can_use_tool,                 # aprovação na tela
            # AskUserQuestion é o modelo PERGUNTANDO ao usuário — não deve obedecer ao modo de
            # permissão. Um hook PreToolUse a intercepta em QUALQUER modo (até dontAsk/bypass),
            # abre o seletor na UI e devolve a escolha em updatedInput.answers.
            hooks={"PreToolUse": [HookMatcher(matcher="AskUserQuestion", hooks=[self._hook_ask_question])]},
            cli_path=claude_path(),
            stderr=self._on_stderr,
        )

    # ------------------------------------------------------------- stderr do agente
    def _on_stderr(self, line: str) -> None:
        """Cada linha de stderr do subprocesso `claude`. Antes era jogada fora (`lambda: None`),
        o que cegava todo diagnóstico de por que um turno morre no meio. Guarda as últimas linhas
        (anexadas ao erro que a UI recebe) e registra num log dedicado, redigindo segredos."""
        try:
            text = _SECRET_RE.sub("«redacted»", (line or "").rstrip("\n"))
            if not text.strip():
                return
            self._stderr_tail.append(text)
            ts = datetime.datetime.now().isoformat(timespec="seconds")
            _AGENT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _AGENT_LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts} [{id(self):x}] {text}\n")
        except Exception:
            pass  # diagnóstico nunca pode derrubar a sessão

    # -------------------------------------------------------- ponte de permissão
    async def _ask_ui(self, tool_name: str, input_data: dict, context: dict | None = None):
        """Envia uma requisição à UI e bloqueia até a resposta (resolvida pelo _ws_pump).
        Devolve o dict da resposta {decision, updated_input?, message?} ou None se o WS cair.

        No modo persistente, se a pergunta nasce (ou fica) SEM socket anexado, um timeout a
        resolve como NEGAÇÃO — "dúvida sem resposta = não faz" (ver _arm_ask_timer)."""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._counter += 1
        rid = f"perm{self._counter}"
        self._pending[rid] = fut
        payload = {
            "type": "permission_request",
            "id": rid,
            "tool": tool_name,
            "input": input_data,
            "context": context or {},
        }
        self._pending_payloads[rid] = payload
        await self._send(payload)
        if self.persist and self.ws is None:   # perguntou já desanexado -> começa a contar
            self._arm_ask_timer(rid)
        try:
            return await fut
        except asyncio.CancelledError:
            return None
        finally:
            self._pending.pop(rid, None)
            self._pending_payloads.pop(rid, None)
            self._cancel_ask_timer(rid)

    async def _can_use_tool(self, tool_name: str, input_data: dict, context):
        """Chamado pelo SDK quando uma ferramenta precisa de aprovação (modos default/plan/
        acceptEdits). AskUserQuestion NÃO chega aqui — é tratada pelo hook PreToolUse."""
        decision = await self._ask_ui(tool_name, input_data, {
            "title": getattr(context, "title", None),
            "description": getattr(context, "description", None),
            "blocked_path": getattr(context, "blocked_path", None),
            "decision_reason": getattr(context, "decision_reason", None),
        })
        if decision is None:
            return PermissionResultDeny(message="sessão encerrada")
        if decision.get("decision") == "allow":
            ui = decision.get("updated_input")
            return PermissionResultAllow(updated_input=ui if isinstance(ui, dict) else input_data)
        return PermissionResultDeny(message=decision.get("message") or "negado pelo usuário")

    async def _hook_ask_question(self, input_data: dict, tool_use_id, context):
        """Hook PreToolUse p/ AskUserQuestion — roda em QUALQUER modo de permissão. Abre o
        seletor na UI e devolve a escolha em updatedInput.answers (curto-circuita a permissão)."""
        tool_input = input_data.get("tool_input") or {}
        if tool_use_id:
            self._ask_tool_ids.add(tool_use_id)  # suprime o card de ferramenta duplicado
        answer = await self._ask_ui("AskUserQuestion", tool_input)
        if answer is not None and answer.get("decision") == "allow":
            ui = answer.get("updated_input")
            return {"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": ui if isinstance(ui, dict) else tool_input,
            }}
        reason = (answer or {}).get("message") if answer else None
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason or "Usuário pulou a pergunta.",
        }}

    # ----------------------------------------------------- attach / detach / timers
    def attach(self, ws: WebSocket) -> None:
        """(Re)anexa um socket. Cancela os timers de carência/pergunta e reemite os cards de
        permissão pendentes (o envio original foi DESCARTADO enquanto desanexado)."""
        # MULTI-ANEXO: abas/dispositivos adicionais convivem; nenhum derruba o outro.
        if ws not in self._wss:
            self._wss.append(ws)
        self._cancel_grace()
        self._cancel_ask_timers()               # você voltou: perguntas voltam a esperar sem pressa
        for payload in list(self._pending_payloads.values()):
            asyncio.create_task(self._send(payload, only=ws))

    def detach(self, ws=None) -> None:
        """Solta um socket (ou todos, sem argumento) SEM matar o agente. Só arma a carência e o
        timeout das perguntas quando NÃO sobrar nenhuma aba anexada."""
        if ws is None:
            self._wss = []
        elif ws in self._wss:
            self._wss.remove(ws)
        if self._wss:
            return
        if self._pending_payloads:              # perguntas em aberto e você saiu -> conta o timeout
            self._arm_ask_timers()
        self._maybe_arm_grace()

    def _maybe_arm_grace(self) -> None:
        # Só agenda o teardown quando NÃO há socket, NÃO há turno rodando e NÃO há pergunta aberta.
        if self.ws is None and not self._busy and not self._pending and not self._closing_done:
            self._arm_grace()

    def _arm_grace(self) -> None:
        self._cancel_grace()
        loop = asyncio.get_event_loop()
        self._grace_handle = loop.call_later(
            max(1, deps.STATE.claude_detach_grace),
            lambda: asyncio.create_task(self.teardown()),
        )

    def _cancel_grace(self) -> None:
        if self._grace_handle is not None:
            self._grace_handle.cancel()
            self._grace_handle = None

    def _arm_ask_timer(self, rid: str) -> None:
        if rid in self._ask_timers:
            return
        loop = asyncio.get_event_loop()
        self._ask_timers[rid] = loop.call_later(
            max(1, deps.STATE.claude_ask_timeout),
            lambda: self._expire_ask(rid),
        )

    def _arm_ask_timers(self) -> None:
        for rid in list(self._pending_payloads.keys()):
            self._arm_ask_timer(rid)

    def _expire_ask(self, rid: str) -> None:
        self._ask_timers.pop(rid, None)
        fut = self._pending.get(rid)
        if fut and not fut.done():
            fut.set_result({"decision": "deny", "message": "sem resposta (timeout)"})

    def _cancel_ask_timer(self, rid: str) -> None:
        t = self._ask_timers.pop(rid, None)
        if t is not None:
            t.cancel()

    def _cancel_ask_timers(self) -> None:
        for t in self._ask_timers.values():
            t.cancel()
        self._ask_timers.clear()

    # ------------------------------------------------------------- ciclo de vida
    async def start(self) -> None:
        """Conecta o client e inicia o pump do SDK (uma vez por sessão viva)."""
        async with self._start_lock:   # o 2º chamador espera o client ficar pronto
            if self._started:
                return
            if not self._model:
                # Descoberta usa um loop próprio; não pode bloquear/nestar o loop do WebSocket.
                self._model = await asyncio.to_thread(claude_models.default_model)
            self.client = ClaudeSDKClient(options=self._options())
            await self.client.connect()  # sem prompt: modo streaming, pronto p/ query()
            if self._mode != "default" and self._mode in VALID_MODES:
                try:
                    await self.client.set_permission_mode(self._mode)
                except Exception:
                    self._mode = "default"
            self._sdk_task = asyncio.create_task(self._sdk_pump())
            self._started = True

    async def run(self) -> None:
        """Caminho CLÁSSICO (persist OFF): vida do agente = vida do socket."""
        await self.start()
        await self._send_queue(fresh=True)
        try:
            await self._ws_pump()
        finally:
            await self.teardown()

    async def serve(self, ws: WebSocket, first: bool) -> None:
        """Caminho PERSISTENTE: (re)anexa este socket e roda o ws_pump. Ao cair, DESANEXA
        (não mata), a menos que o cliente tenha mandado "bye" (fechamento deliberado)."""
        self.attach(ws)
        if first:
            await self.start()
            await self._send_queue(fresh=True)
        else:
            # Estado inicial só para ESTE socket (as outras abas já o têm).
            await self._send({"type": "reattached", "busy": self._busy}, only=ws)
            await self._send_queue(only=ws)
            if self._restore_pending:
                items, self._restore_pending = self._restore_pending, []
                await self._send({"type": "queue_restored", "items": items}, only=ws)
            lt = self._last_turn
            if lt:   # restaura o relógio do cache (idade real) e o contexto após recarregar a página
                await self._send({"type": "cache_state", "usage": lt["usage"],
                                  "age": max(0.0, time.monotonic() - lt["t"])}, only=ws)
                if lt.get("ctx"):
                    await self._send(lt["ctx"], only=ws)
        try:
            await self._ws_pump(ws)
        finally:
            if self._closing:
                await self.teardown()
            else:                      # solta só ESTE socket; as outras abas seguem
                self.detach(ws)

    async def teardown(self) -> None:
        """Mata o subprocesso `claude`, cancela timers/futures e sai do registro. Idempotente."""
        if self._closing_done:
            return
        if not _SHUTTING_DOWN:          # encerrou de verdade (bye/carência): nada a retomar
            _resume_forget(self.sid)
        self._closing_done = True
        self._cancel_grace()
        self._cancel_ask_timers()
        if self._sdk_task is not None:
            self._sdk_task.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        self._pending_payloads.clear()
        for key in {self.sid, self._resume}:
            if key and _LIVE.get(key) is self:
                _LIVE.pop(key, None)
        try:
            if self.client is not None:
                await self.client.disconnect()  # mata o subprocesso `claude`
        except Exception:
            pass
        for w in list(self._wss):
            try:
                await w.close()
            except Exception:
                pass

    async def _ws_pump(self, ws=None) -> None:
        ws = ws or self.ws
        while True:
            try:
                raw = await ws.receive_json()
            except (WebSocketDisconnect, RuntimeError):
                return
            except Exception:
                return
            if not isinstance(raw, dict):
                continue
            kind = raw.get("type")
            if kind == "prompt":
                text = (raw.get("text") or "").strip()
                if text:
                    self._auto_chain = 0     # humano no comando: a cadeia anti-loop recomeça
                    if len(self._wss) > 1:   # outras abas da sessão veem a pergunta
                        await self._send({"type": "user_echo", "text": text}, skip=ws)
                    if raw.get("queue") and self._busy:
                        await self._enqueue(text)
                    elif raw.get("queue"):
                        # Pediu fila mas o turno acabou no caminho: roda já e avisa a UI (que,
                        # por ter escolhido "fila", ainda não desenhou a bolha).
                        await self._send({"type": "queue_dispatched", "id": None, "text": text})
                        await self._query(text)
                    else:
                        await self._query(text)
            elif kind == "queue_remove":
                if self._pop_queued(raw.get("id")) is not None:
                    await self._send_queue()
            elif kind == "queue_add":
                await self._add_to_queue(raw.get("texts"))
            elif kind == "queue_move":
                if self._move_queued(raw.get("id"), raw.get("to")):
                    await self._send_queue()
            elif kind == "queue_send_now":
                item = self._pop_queued(raw.get("id"))
                if item is not None:
                    self._auto_chain = 0
                    await self._send_queue()
                    await self._send({"type": "queue_dispatched", **item})
                    await self._query(item["text"])
            elif kind == "bye":
                # Fechamento DELIBERADO (encerrar / trocar de sessão): mata a sessão viva.
                # Um drop por standby NÃO manda "bye" — por isso lá a gente só desanexa.
                self._closing = True
                return
            elif kind == "set_mode":
                mode = raw.get("mode")
                if mode in VALID_MODES:
                    try:
                        await self.client.set_permission_mode(mode)
                        self._mode = mode
                        claude_prefs.set_session(self.sid, mode=mode)
                        await self._send({"type": "mode_changed", "mode": mode})
                    except Exception as e:
                        await self._send({"type": "error", "detail": f"set_mode: {e}"})
            elif kind == "set_model":
                try:
                    self._model = raw.get("model") or None
                    await self.client.set_model(self._model)
                    claude_prefs.set_session(self.sid, model=self._model)
                except Exception as e:
                    await self._send({"type": "error", "detail": f"set_model: {e}"})
            elif kind == "set_effort":
                # O SDK só aceita o esforço no lançamento: vale para o próximo (re)lançamento.
                eff = raw.get("effort")
                self._effort = eff if eff in VALID_EFFORT else None
            elif kind == "interrupt":
                if self._busy:
                    self._interrupted = True   # o turno acaba, mas a fila NÃO deve disparar sozinha
                try:
                    await self.client.interrupt()
                except Exception as e:
                    await self._send({"type": "error", "detail": f"interrupt: {e}"})
            elif kind == "permission":
                fut = self._pending.get(raw.get("id"))
                if fut and not fut.done():
                    fut.set_result(raw)

    # ------------------------------------------------------------------ fila
    async def _query(self, text: str) -> None:
        self._busy = True
        self._tracked = True
        self._track()
        await self.client.query(text)

    async def _send_queue(self, fresh: bool = False, only=None) -> None:
        ev = {"type": "queue", "items": list(self._queue)}
        if fresh:
            ev["fresh"] = True
        self._track()
        await self._send(ev, only=only)

    async def _add_to_queue(self, texts) -> None:
        """Re-enfileira o cache da aba SEM despachar (nem com o agente ocioso): o turno que as
        esperava morreu junto com a fila do servidor — o humano decide (⚡) ou o próximo turno leva."""
        if not isinstance(texts, list):
            return
        for t in texts:
            t = t.strip() if isinstance(t, str) else ""
            if not t:
                continue
            if len(self._queue) >= MAX_QUEUE:
                await self._send({"type": "error", "detail": f"Fila cheia ({MAX_QUEUE} mensagens)."})
                break
            self._queue_seq += 1
            self._queue.append({"id": f"q{self._queue_seq}", "text": t})
        await self._send_queue()

    async def _enqueue(self, text: str) -> None:
        if len(self._queue) >= MAX_QUEUE:
            await self._send({"type": "error", "detail": f"Fila cheia ({MAX_QUEUE} mensagens)."})
            return
        self._queue_seq += 1
        self._queue.append({"id": f"q{self._queue_seq}", "text": text})
        await self._send_queue()

    def _pop_queued(self, qid) -> dict | None:
        for i, it in enumerate(self._queue):
            if it["id"] == qid:
                return self._queue.pop(i)
        return None

    def _move_queued(self, qid, to) -> bool:
        """Move o item `qid` p/ a posição `to` (limitada à fila). Item ausente (já despachado
        ou removido no caminho) ou posição inválida = no-op; a UI recebe o estado real de volta."""
        if not isinstance(to, int) or isinstance(to, bool):
            return False
        item = self._pop_queued(qid)
        if item is None:
            return False
        self._queue.insert(max(0, min(to, len(self._queue))), item)
        return True

    async def _after_turn(self, is_error: bool) -> None:
        """Fim de turno: despacha o próximo da fila — ou, se o turno foi interrompido/deu erro,
        devolve a fila p/ a caixa (não sai executando sozinho o que foi pensado p/ outro contexto)."""
        interrupted, self._interrupted = self._interrupted, False
        if not self._queue:
            return
        if interrupted or is_error:
            items, self._queue = self._queue, []
            if self.ws is None:          # aba fechada: devolve quando ela re-anexar
                self._restore_pending.extend(items)
            else:
                await self._send({"type": "queue_restored", "items": items})
            await self._send_queue()
            return
        item = self._queue.pop(0)
        await self._send_queue()
        await self._send({"type": "queue_dispatched", **item})
        await self._query(item["text"])

    async def _sdk_pump(self) -> None:
        try:
            async for msg in self.client.receive_messages():
                await self._translate(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            detail = str(e)
            tail = "\n".join(list(self._stderr_tail)[-8:])
            if tail:
                detail += f"\n\n— stderr recente do agente —\n{tail}"
            await self._send({"type": "error", "detail": detail})

    # -------------------------------------------------------------- tradução
    async def _translate(self, msg) -> None:
        if isinstance(msg, SystemMessage):
            # Persistência: ao conhecer o session_id real, registra a sessão p/ o re-anexo achá-la.
            if self.persist and msg.subtype == "init":
                sid = (msg.data or {}).get("session_id")
                if sid:
                    self.sid = sid
                    _LIVE[sid] = self
                    self._track()
            data = msg.data
            if msg.subtype == "init":
                sid = (data or {}).get("session_id")
                # grava o modelo/modo vigentes desta conversa se ainda não há registro
                if sid and not claude_prefs.get_session(sid):
                    claude_prefs.set_session(sid, model=self._model, mode=self._mode)
                data = {**(data or {}), "permissionMode": self._mode}   # o CLI sempre diz "default"
            await self._send({"type": "system", "subtype": msg.subtype, "data": data})

        elif isinstance(msg, StreamEvent):
            ev = msg.event or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    await self._send({"type": "text_delta", "text": delta.get("text", "")})
                elif delta.get("type") == "thinking_delta":
                    await self._send({"type": "thinking_delta", "text": delta.get("thinking", "")})

        elif isinstance(msg, AssistantMessage):
            error = getattr(msg, "error", None)
            if error:
                detail = "\n".join(b.text for b in msg.content if isinstance(b, TextBlock))
                await self._send({"type": "error", "detail": detail or str(error),
                                  "error_code": error})
            # Texto/pensamento já foram streamados via StreamEvent; aqui emitimos os
            # tool_use finalizados (não dá p/ montar bem o JSON parcial) e fechamos a msg.
            for b in msg.content:
                if isinstance(b, ToolUseBlock):
                    if b.name == "AskUserQuestion":  # já vira o seletor (hook); não dup. card
                        self._ask_tool_ids.add(b.id)
                        continue
                    await self._send({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
            await self._send({"type": "assistant_end"})

        elif isinstance(msg, UserMessage):
            # Resultados de ferramenta voltam como UserMessage com ToolResultBlock.
            content = msg.content
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, ToolResultBlock):
                        if b.tool_use_id in self._ask_tool_ids:  # resultado do AskUserQuestion: já mostrado no seletor
                            continue
                        await self._send({
                            "type": "tool_result",
                            "tool_use_id": b.tool_use_id,
                            "content": _stringify(b.content),
                            "is_error": bool(b.is_error),
                        })

        elif isinstance(msg, ResultMessage):
            self._busy = False
            await self._send({
                "type": "result",
                "session_id": msg.session_id,
                "cost_usd": msg.total_cost_usd,
                "usage": msg.usage,
                "is_error": msg.is_error,
                "result": msg.result,
                "errors": getattr(msg, "errors", None),
                "api_error_status": getattr(msg, "api_error_status", None),
            })
            self._last_turn = {"t": time.monotonic(), "usage": msg.usage, "ctx": None}
            try:   # uso do contexto p/ o indicador discreto da UI (best-effort)
                cu = await self.client.get_context_usage()
                ctx = {"type": "context_usage", "total": cu.get("totalTokens"),
                       "max": cu.get("rawMaxTokens") or cu.get("maxTokens"),
                       "percentage": cu.get("percentage")}
                self._last_turn["ctx"] = ctx
                await self._send(ctx)
            except Exception:
                pass
            try:
                await self._after_turn(bool(msg.is_error))
            except Exception as e:
                await self._send({"type": "error", "detail": f"fila: {e}"})
            self._track()   # turno acabou (e a fila não disparou outro): sai da anotação
            if self.persist:
                # Turno acabou. Se a aba está dormindo (desanexado), começa a contar a carência
                # até o teardown — a resposta já foi gravada no disco.
                self._maybe_arm_grace()


# --------------------------------------------------------------------------- #
# Sessões passadas (retomar) — lê os transcripts em ~/.claude/projects/<projeto>.
# --------------------------------------------------------------------------- #
def project_session_exists(sid: str) -> bool:
    """Confere UUID e pertencimento ao projeto, sem iniciar o agente nem ler mensagens."""
    if not re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", sid):
        return False
    live = _LIVE.get(sid)
    if live is not None and not live._closing_done:
        return True
    if not _SDK_OK:
        return False
    try:
        from claude_agent_sdk import get_session_info  # noqa: PLC0415
        return get_session_info(sid, directory=str(deps.NETOPS_ROOT)) is not None
    except ImportError:
        # SDKs anteriores ao lookup individual ainda oferecem list_sessions.
        return any(s["id"] == sid for s in list_project_sessions(limit=None))
    except Exception:
        return False


def list_project_sessions(limit: int | None = 60) -> list[dict]:
    """Sessões Claude Code deste projeto (cwd=NETOPS_ROOT), mais recentes primeiro."""
    if not _SDK_OK:
        return []
    try:
        from claude_agent_sdk import list_sessions  # noqa: PLC0415
        sess = list_sessions(directory=str(deps.NETOPS_ROOT), limit=limit)
    except Exception:
        return []
    out = []
    for x in sess:
        title = (x.custom_title or x.summary or x.first_prompt or "").strip()
        out.append({
            "id": x.session_id,
            "title": (title or "(sem título)")[:80],
            "preview": (x.first_prompt or "").strip()[:140],
            "mtime": x.last_modified,
            "created": x.created_at,
            "tag": x.tag,
            "branch": x.git_branch,
        })
    return out


def _sessions_project_dir(sample_ids):
    """Localiza a pasta ~/.claude/projects/<proj> que contem os transcripts deste projeto."""
    base = Path(os.path.expanduser("~")) / ".claude" / "projects"
    if not base.is_dir():
        return None
    ids = [s for s in sample_ids][:5]
    try:
        for d in base.iterdir():
            if d.is_dir() and any((d / (sid + ".jsonl")).exists() for sid in ids):
                return d
    except OSError:
        pass
    return None


def _content_snippet(text, idx, qlen, width=70):
    """Trecho legivel em torno do match (limpa escapes de JSON)."""
    start = max(0, idx - width)
    end = min(len(text), idx + qlen + width)
    frag = text[start:end].replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
    frag = re.sub(r"\s+", " ", frag).strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


def search_project_sessions(query, limit=80):
    """Sessoes cujo titulo/preview OU conteudo do transcript casam com query (case-insensitive)."""
    q = (query or "").strip().lower()
    sessions = list_project_sessions(limit=limit)
    if not q:
        return sessions
    pdir = _sessions_project_dir([s["id"] for s in sessions])
    out = []
    for s in sessions:
        title_hay = (s.get("title", "") + " " + s.get("preview", "")).lower()
        if q in title_hay:
            out.append(s)
            continue
        if pdir is None:
            continue
        try:
            text = (pdir / (s["id"] + ".jsonl")).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        idx = text.lower().find(q)
        if idx != -1:
            s2 = dict(s)
            s2["snippet"] = _content_snippet(text, idx, len(q))
            out.append(s2)
    return out


def _transcript_timestamps(sid: str) -> dict[str, int]:
    """uuid da mensagem -> epoch ms, lido do .jsonl (o SDK não expõe o timestamp)."""
    out: dict[str, int] = {}
    try:
        base = Path(os.path.expanduser("~")) / ".claude" / "projects"
        f = next((d / (sid + ".jsonl") for d in base.iterdir()
                  if d.is_dir() and (d / (sid + ".jsonl")).exists()), None)
        if f is None:
            return out
        with f.open(encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"timestamp"' not in line or '"uuid"' not in line:
                    continue
                try:
                    o = json.loads(line)
                    ts = datetime.datetime.fromisoformat(str(o["timestamp"]).replace("Z", "+00:00"))
                    out[o["uuid"]] = int(ts.timestamp() * 1000)
                except Exception:
                    continue
    except Exception:
        pass
    return out


def session_items(sid: str) -> list[dict]:
    """Traduz o histórico de uma sessão para os mesmos itens da transcrição da UI."""
    if not _SDK_OK:
        return []
    try:
        from claude_agent_sdk import get_session_messages  # noqa: PLC0415
        msgs = get_session_messages(sid, directory=str(deps.NETOPS_ROOT))
    except Exception:
        return []
    items: list[dict] = []
    tool_index: dict[str, dict] = {}
    ask_ids: set[str] = set()
    stamps = _transcript_timestamps(sid)
    for sm in msgs:
        role_item = "user" if sm.type == "user" else "assistant"
        ts = stamps.get(sm.uuid)
        content = (sm.message or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                it = {"type": role_item, "text": content.strip(), "ts": ts}
                if role_item == "user":
                    it["uuid"] = sm.uuid   # âncora do fork ("ramificar daqui")
                items.append(it)
            continue
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                t = (b.get("text") or "").strip()
                if t:
                    it = {"type": role_item, "text": t, "ts": ts}
                    if role_item == "user":
                        it["uuid"] = sm.uuid   # âncora do fork ("ramificar daqui")
                    items.append(it)
            elif bt == "thinking":
                t = (b.get("thinking") or "").strip()
                if t:
                    items.append({"type": "thinking", "text": t})
            elif bt == "tool_use":
                if b.get("name") == "AskUserQuestion":
                    ask_ids.add(b.get("id"))
                    continue
                it = {"type": "tool", "id": b.get("id"), "name": b.get("name"),
                      "input": b.get("input"), "tstatus": "done"}
                items.append(it)
                tool_index[b.get("id")] = it
            elif bt == "tool_result":
                tid = b.get("tool_use_id")
                if tid in ask_ids:
                    continue
                it = tool_index.get(tid)
                if it is not None:
                    it["result"] = _stringify(b.get("content"))
                    it["isError"] = bool(b.get("is_error"))
                    it["tstatus"] = "error" if b.get("is_error") else "done"
    return items


def delete_project_session(sid: str) -> None:
    if not _SDK_OK:
        return
    try:
        from claude_agent_sdk import delete_session  # noqa: PLC0415
        delete_session(sid, directory=str(deps.NETOPS_ROOT))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Fork (ramificar) — nova conversa com o histórico até o fim do turno de um prompt.
# --------------------------------------------------------------------------- #
def _prompt_text(sm) -> str | None:
    """Texto do prompt humano; None se a mensagem não é prompt (tool_result, assistant…)."""
    if sm.type != "user":
        return None
    content = (sm.message or {}).get("content")
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts = [(b.get("text") or "").strip() for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        t = "\n".join(p for p in parts if p)
        return t or None
    return None


_SYNTHETIC_RE = re.compile(r"^\s*<(task-notification|system-reminder|command-name|command-message|"
                           r"local-command-stdout|local-command-stderr|bash-stdout|bash-input)>")


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def fork_cut_uuid(msgs, *, uuid: str | None = None, text: str | None = None,
                  occurrence: int = 0) -> str | None:
    """UUID da ÚLTIMA mensagem do turno do prompt escolhido (inclusive a resposta dele).

    O prompt é achado pelo uuid (histórico lido do transcript) ou, na conversa ao vivo (itens
    do stream não têm uuid), pela `occurrence`-ésima ocorrência do texto — com fallback para
    prompts que CONTÊM o texto (a fila pode juntar mensagens num envio só).
    """
    prompts = [(i, _prompt_text(m)) for i, m in enumerate(msgs)]
    prompts = [(i, t) for i, t in prompts if t is not None]
    start = None
    if uuid:
        start = next((i for i, _ in prompts if msgs[i].uuid == uuid), None)
    if start is None and text:
        want = _norm(text)
        for pred in (lambda t: _norm(t) == want, lambda t: want and want in _norm(t)):
            hits = [i for i, t in prompts if pred(t)]
            if hits:
                start = hits[min(max(occurrence, 0), len(hits) - 1)]
                break
    if start is None:
        return None
    # Mensagens injetadas (fim de tarefa em background, saída de /comando) continuam o turno.
    nxt = next((i for i, t in prompts if i > start and not _SYNTHETIC_RE.match(t)), len(msgs))
    return msgs[nxt - 1].uuid


def fork_project_session(sid: str, *, uuid: str | None = None, text: str | None = None,
                         occurrence: int = 0, title: str | None = None) -> str:
    """Cria a conversa ramificada e devolve o novo sid. ValueError/FileNotFoundError se inválido."""
    if not _SDK_OK:
        raise RuntimeError("SDK do Claude indisponível")
    if not project_session_exists(sid):
        raise FileNotFoundError(sid)
    from claude_agent_sdk import fork_session, get_session_messages  # noqa: PLC0415
    msgs = get_session_messages(sid, directory=str(deps.NETOPS_ROOT))
    cut = fork_cut_uuid(msgs, uuid=uuid, text=text, occurrence=occurrence)
    if cut is None:
        raise ValueError("prompt não encontrado no histórico gravado")
    res = fork_session(sid, directory=str(deps.NETOPS_ROOT), up_to_message_id=cut,
                       title=(title or None))
    src = claude_prefs.get_session(sid)   # o ramo herda modelo/modo da conversa de origem
    if src:
        claude_prefs.set_session(res.session_id, model=src.get("model"), mode=src.get("mode"))
    return res.session_id
