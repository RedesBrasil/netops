#!/usr/bin/env python3
"""Sessão Claude Code sobre WebSocket — ponte entre o `claude-agent-sdk` e a UI.

⚠ EXECUÇÃO DE COMANDO ARBITRÁRIO + EDIÇÃO DE ARQUIVOS. Cada conexão abre um
`ClaudeSDKClient` (que dispara um subprocesso `claude`) rodando COMO O USUÁRIO DO
SERVIDOR, com `cwd` = NETOPS_ROOT e herdando CLAUDE.md/skills/agentes do projeto.
Por isso só liga com `--enable-claude` (default DESLIGADO) e nunca em `--read-only`
(ver routers/claude.py e server.py).

Espelha o desenho do terminal web (routers/terminal.py): a auth do handshake é feita
À MÃO no router, e aqui rodamos duas tarefas asyncio — uma lê o WebSocket (turnos do
usuário, troca de modo, respostas de permissão, interromper) e outra bombeia as
mensagens do SDK de volta como JSON. A autenticação do `claude` reaproveita o login de
assinatura já existente (~/.claude/.credentials.json) — o SDK herda o HOME do processo.

Protocolo (JSON nos dois sentidos) — ver scripts/ui/static/js/pages/claude.js:
  cliente -> servidor:
    {"type":"prompt","text":...}                      turno do usuário (inclui /slash)
    {"type":"set_mode","mode":...}                    troca o permission_mode em tempo real
    {"type":"set_model","model":...}                  troca o modelo (None = padrão)
    {"type":"permission","id":...,"decision":"allow|deny","updated_input":{...},"message":...}
    {"type":"interrupt"}                              aborta o turno atual
  servidor -> cliente:
    {"type":"system","subtype":...,"data":{...}}      init traz session_id/model/slash_commands
    {"type":"text_delta","text":...}                  streaming do texto do assistente
    {"type":"thinking_delta","text":...}              streaming do "pensamento"
    {"type":"tool_use","id":..,"name":..,"input":{...}}
    {"type":"tool_result","tool_use_id":..,"content":..,"is_error":bool}
    {"type":"assistant_end"}                           fim de uma mensagem do assistente
    {"type":"permission_request","id":..,"tool":..,"input":{...},"context":{...}}
    {"type":"mode_changed","mode":...}
    {"type":"result","session_id":..,"cost_usd":..,"usage":{...},"is_error":bool,"result":..}
    {"type":"error","detail":...}
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil

from fastapi import WebSocket, WebSocketDisconnect

import deps

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


def is_available() -> bool:
    """O SDK está instalado E o binário `claude` está no PATH?"""
    return _SDK_OK and bool(_claude_path())


def _claude_path() -> str | None:
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


class ClaudeWebSession:
    """Dirige um ClaudeSDKClient a partir de um WebSocket já autorizado e aceito."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.client: ClaudeSDKClient | None = None
        self._pending: dict[str, asyncio.Future] = {}  # id de permissão -> Future
        self._counter = 0
        self._ask_tool_ids: set[str] = set()           # tool_use_ids de AskUserQuestion (suprimir card)

    # ------------------------------------------------------------------ envio
    async def _send(self, obj: dict) -> None:
        # default=str protege contra qualquer valor não-serializável vindo do SDK.
        try:
            await self.ws.send_text(json.dumps(obj, default=str))
        except (WebSocketDisconnect, RuntimeError):
            pass

    def _options(self) -> "ClaudeAgentOptions":
        resume = self.ws.query_params.get("resume") or None  # retomar sessão passada (?resume=<sid>)
        return ClaudeAgentOptions(
            cwd=str(deps.NETOPS_ROOT),
            resume=resume,
            setting_sources=["user", "project", "local"],  # herda CLAUDE.md/skills/agentes
            permission_mode="default",                       # seguro-mas-usável; UI troca p/ qualquer um
            include_partial_messages=True,                   # streaming de texto/pensamento
            can_use_tool=self._can_use_tool,                 # aprovação na tela
            # AskUserQuestion é o modelo PERGUNTANDO ao usuário — não deve obedecer ao modo de
            # permissão. Um hook PreToolUse a intercepta em QUALQUER modo (até dontAsk/bypass),
            # abre o seletor na UI e devolve a escolha em updatedInput.answers.
            hooks={"PreToolUse": [HookMatcher(matcher="AskUserQuestion", hooks=[self._hook_ask_question])]},
            cli_path=_claude_path(),
            stderr=lambda _s: None,
        )

    # -------------------------------------------------------- ponte de permissão
    async def _ask_ui(self, tool_name: str, input_data: dict, context: dict | None = None):
        """Envia uma requisição à UI e bloqueia até a resposta (resolvida pelo _ws_pump).
        Devolve o dict da resposta {decision, updated_input?, message?} ou None se o WS cair."""
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._counter += 1
        rid = f"perm{self._counter}"
        self._pending[rid] = fut
        await self._send({
            "type": "permission_request",
            "id": rid,
            "tool": tool_name,
            "input": input_data,
            "context": context or {},
        })
        try:
            return await fut
        except asyncio.CancelledError:
            return None
        finally:
            self._pending.pop(rid, None)

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

    # ------------------------------------------------------------- ciclo de vida
    async def run(self) -> None:
        """Conecta o cliente e roda os dois pumps até o WebSocket fechar."""
        self.client = ClaudeSDKClient(options=self._options())
        await self.client.connect()  # sem prompt: modo streaming, pronto p/ query()
        pump = asyncio.create_task(self._sdk_pump())
        try:
            await self._ws_pump()  # retorna ao desconectar
        finally:
            pump.cancel()
            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
            self._pending.clear()
            try:
                await self.client.disconnect()  # mata o subprocesso `claude`
            except Exception:
                pass
            try:
                await self.ws.close()
            except Exception:
                pass

    async def _ws_pump(self) -> None:
        while True:
            try:
                raw = await self.ws.receive_json()
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
                    await self.client.query(text)
            elif kind == "set_mode":
                mode = raw.get("mode")
                if mode in VALID_MODES:
                    try:
                        await self.client.set_permission_mode(mode)
                        await self._send({"type": "mode_changed", "mode": mode})
                    except Exception as e:
                        await self._send({"type": "error", "detail": f"set_mode: {e}"})
            elif kind == "set_model":
                try:
                    await self.client.set_model(raw.get("model") or None)
                except Exception as e:
                    await self._send({"type": "error", "detail": f"set_model: {e}"})
            elif kind == "interrupt":
                try:
                    await self.client.interrupt()
                except Exception as e:
                    await self._send({"type": "error", "detail": f"interrupt: {e}"})
            elif kind == "permission":
                fut = self._pending.get(raw.get("id"))
                if fut and not fut.done():
                    fut.set_result(raw)

    async def _sdk_pump(self) -> None:
        try:
            async for msg in self.client.receive_messages():
                await self._translate(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._send({"type": "error", "detail": str(e)})

    # -------------------------------------------------------------- tradução
    async def _translate(self, msg) -> None:
        if isinstance(msg, SystemMessage):
            await self._send({"type": "system", "subtype": msg.subtype, "data": msg.data})

        elif isinstance(msg, StreamEvent):
            ev = msg.event or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    await self._send({"type": "text_delta", "text": delta.get("text", "")})
                elif delta.get("type") == "thinking_delta":
                    await self._send({"type": "thinking_delta", "text": delta.get("thinking", "")})

        elif isinstance(msg, AssistantMessage):
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
            await self._send({
                "type": "result",
                "session_id": msg.session_id,
                "cost_usd": msg.total_cost_usd,
                "usage": msg.usage,
                "is_error": msg.is_error,
                "result": msg.result,
            })


# --------------------------------------------------------------------------- #
# Sessões passadas (retomar) — lê os transcripts em ~/.claude/projects/<projeto>.
# --------------------------------------------------------------------------- #
def list_project_sessions(limit: int = 60) -> list[dict]:
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
    for sm in msgs:
        role_item = "user" if sm.type == "user" else "assistant"
        content = (sm.message or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                items.append({"type": role_item, "text": content.strip()})
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
                    items.append({"type": role_item, "text": t})
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
