"""Primeiro acesso ao console: idioma + conta do admin + cofre, num assistente só (#setup).

O instalador não pergunta nada. Ele deixa o console escutando em todos os IPs e gera um token de uso
único (lib/setup_token.py). Enquanto o assistente não for concluído, o console só responde a ele
(deps.setup_mode / app.py). Concluir faz, nesta ordem:

1. cria o cofre com a senha informada (ela é a senha-mestra E a senha do admin, como no login antigo);
2. cria o usuário admin (login = e-mail) com keyslot do cofre;
3. grava o idioma da instalação em core/config/project-config.yaml (`instance.language`);
4. destranca o cofre nesta sessão e faz o login;
5. pede a etapa ROOT (instalação layout 2): a unidade netops-setup-finish-<slug>.path roda
   /usr/local/sbin/netops-setup-finish, que fixa o verificador do cofre no sudo e gera a senha do
   host Local (gravada no cofre pela conta operacional; o console nunca a vê).
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import deps
from lib import accessdb, setup_token

LANGUAGES = [{"code": "en", "name": "English"}, {"code": "pt-BR", "name": "Português"}]
LANGUAGE_CODES = {x["code"] for x in LANGUAGES}
IDENT_DIR = Path(os.environ.get("NETOPS_IDENTITY_DIR") or "/etc/netops/instances")


class SetupError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _slug() -> str | None:
    try:
        from lib import runtime_identity as rid  # noqa: PLC0415
        return rid.slug(deps.NETOPS_ROOT)
    except Exception:  # noqa: BLE001
        return None


def instance_language() -> str | None:
    import yaml  # noqa: PLC0415
    try:
        cfg = yaml.safe_load(deps.PROJECT_CONFIG.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return None
    lang = (cfg.get("instance") or {}).get("language") if isinstance(cfg, dict) else None
    return lang if lang in LANGUAGE_CODES else None


def _write_language(lang: str) -> None:
    """instance.language no project-config.yaml (local da instalação; o atualizador não mexe)."""
    from services import yaml_io  # noqa: PLC0415
    path = deps.PROJECT_CONFIG
    if not path.exists():
        example = path.with_name("project-config.example.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")
    data, _rev, y = yaml_io.load_rt(path)
    if data is None:
        data = {}
    inst = data.get("instance")
    if not isinstance(inst, dict):
        data["instance"] = {"language": lang}
    else:
        inst["language"] = lang
    yaml_io.write_rt(path, y, data, expected=None)


def _create_vault(password: str) -> bytes:
    """Cofre novo (credentials.yaml 0600). Recusa se já existir."""
    from lib import vault  # noqa: PLC0415
    from vault import cli as vcli  # noqa: PLC0415
    path: Path = deps.CREDS_FILE
    text = path.read_text(encoding="utf-8") if path.exists() else "version: 1\n\ncredentials: {}\n"
    if deps.vault_initialized():
        raise SetupError("already_configured", "O cofre já foi inicializado.", 409)
    meta, key = vault.build_meta(password)
    path.parent.mkdir(parents=True, exist_ok=True)
    vcli._atomic_write(path, vcli._set_vault_block(text, meta))
    os.chmod(path, 0o600)
    return key


def finish_status() -> dict:
    """Estado da etapa root (layout 2). Arquivos de root em /etc/netops/instances/<slug>.setup-*."""
    slug = _slug()
    cmd = f"sudo /usr/local/sbin/netops-setup-finish {slug}" if slug else ""
    if not slug:
        return {"state": "not_applicable", "command": ""}
    done = IDENT_DIR / f"{slug}.setup-done"
    pending = IDENT_DIR / f"{slug}.setup-pending"
    result = {}
    try:
        result = json.loads(done.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {}
    if pending.exists():
        state = "failed" if result.get("state") == "failed" else "pending"
        return {"state": state, "detail": result.get("detail", ""), "command": cmd,
                "requested": setup_token.request_path(deps.DATA_ROOT).exists()}
    if result:
        return {"state": result.get("state", "done"), "detail": result.get("detail", ""),
                "pin": result.get("pin"), "localadmin": result.get("localadmin"), "command": cmd}
    return {"state": "not_applicable", "command": ""}


def request_finish() -> dict:
    """(Re)dispara a etapa root, se ela estiver pendente."""
    st = finish_status()
    if st["state"] in ("pending", "failed"):
        setup_token.request_finish(deps.DATA_ROOT)
        st = finish_status()
    return st


def status() -> dict:
    return {
        "setup_required": deps.setup_mode(),
        "token": setup_token.state(deps.DATA_ROOT),
        "languages": LANGUAGES,
        "language": instance_language(),
        "password_min": accessdb.PASSWORD_MIN,
    }


def complete(*, token: str, language: str, name: str, email: str, password: str, ip: str = "",
             user_agent: str = "") -> dict:
    if not deps.setup_mode():
        raise SetupError("already_configured", "O primeiro acesso já foi concluído. Entre com seu e-mail e senha.", 409)
    if language not in LANGUAGE_CODES:
        raise SetupError("invalid_language", "Escolha o idioma: English ou Português.", 422)
    db = deps.db_file()
    lock_path = setup_token.token_path(deps.DATA_ROOT).with_name(".complete.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)          # dois navegadores ao mesmo tempo: só um conclui
        if not deps.setup_mode():
            raise SetupError("already_configured", "O primeiro acesso já foi concluído.", 409)
        if not setup_token.check(deps.DATA_ROOT, token):
            accessdb.audit(db, "setup_denied", ip=ip, detail="token inválido ou expirado")
            raise SetupError("bad_token", "Link de configuração inválido ou expirado. Gere outro no servidor: "
                             "python3 scripts/engine/users/cli.py setup-link", 403)
        accessdb.check_password_policy(password)
        email_n = accessdb.norm_email(email, required=True)
        key = _create_vault(password)
        try:
            accessdb.create_user(db, deps.LEGACY_ADMIN, password, display_name=(name or "").strip()[:80] or "Administrador",
                                 email=email_n, groups=[accessdb.ADMIN_GROUP], created_by="primeiro acesso",
                                 vault_key=key, require_email=True)
        except Exception:
            # sem usuário o cofre recém-criado travaria o console: desfaz para o assistente continuar valendo
            try:
                from vault import cli as vcli  # noqa: PLC0415
                text = deps.CREDS_FILE.read_text(encoding="utf-8")
                vcli._atomic_write(deps.CREDS_FILE, _strip_vault(text))
            except Exception:  # noqa: BLE001
                pass
            raise
        _write_language(language)
        setup_token.consume(deps.DATA_ROOT)
    from lib import vault_session  # noqa: PLC0415
    if deps.STATE.allow_vault_unlock:
        vault_session.set_session_key(key, vault_session.default_ttl())
    sid = deps.create_auth_session(user=deps.LEGACY_ADMIN, ip=ip, user_agent=user_agent)
    accessdb.record_login(db, deps.LEGACY_ADMIN, ip)
    accessdb.audit(db, "setup_complete", username=deps.LEGACY_ADMIN, ip=ip,
                   detail=f"primeiro acesso: admin {email_n}, idioma {language}")
    finish = request_finish() if deps.STATE.allow_vault_unlock else finish_status()
    from services import authz  # noqa: PLC0415
    p = authz.principal_for_user(deps.LEGACY_ADMIN)
    return {"auth_token": sid, "user": p.public() if p else None, "language": language, "finish": finish}


def _strip_vault(text: str) -> str:
    from vault import cli as vcli  # noqa: PLC0415
    lines = text.splitlines()
    span = vcli._vault_span(lines)
    if not span:
        return text
    s, e = span
    return "\n".join(lines[:s] + lines[e:]) + "\n"
