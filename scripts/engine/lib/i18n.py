"""Translations (i18n) shared by the console API, the CLIs and the frontend.

Catalogs live in <repo>/locales/<lang>/<namespace>.json. A key is "<namespace>.<key>" (nested JSON objects
are flattened with dots). English (`en`) is the source of truth: a key missing in another language falls back
to English, and a key missing everywhere is returned as-is (never an empty screen).

Language resolution (first match wins):
  1. explicit `lang` argument;
  2. the request/CLI context (`use_lang()` / contextvar set by the console middleware per request);
  3. NETOPS_LANG environment variable (CLIs, scheduled tasks);
  4. the instance language: core/config/project-config.yaml -> instance.language (chosen at first access);
  5. LEGACY_DEFAULT (installs older than i18n, which were Portuguese-only).

Placeholders: "{name}". Plurals: keys "<key>_one" / "<key>_other" selected by the `count` variable.
No external dependency.
"""
from __future__ import annotations

import contextvars
import json
import os
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCALES_DIR = REPO_ROOT / "core" / "locales"
SOURCE_LANG = "en"
LEGACY_DEFAULT = "pt-BR"   # only when the instance has no language yet (pre-i18n installs)

_ctx_lang: contextvars.ContextVar[str | None] = contextvars.ContextVar("netops_lang", default=None)
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_langs_cache: tuple[float, list] | None = None


# ----------------------------------------------------------------- languages
def languages() -> list[dict]:
    """[{code, name, status}] from core/locales/_languages.yaml (cached by mtime)."""
    global _langs_cache
    path = LOCALES_DIR / "_languages.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return [{"code": SOURCE_LANG, "name": "English", "status": "complete"}]
    if _langs_cache and _langs_cache[0] == mtime:
        return _langs_cache[1]
    try:
        import yaml  # noqa: PLC0415
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - no PyYAML (system python) or bad file: languages = folders present
        return [{"code": d.name, "name": d.name, "status": "partial"}
                for d in sorted(LOCALES_DIR.iterdir()) if d.is_dir()] or \
            [{"code": SOURCE_LANG, "name": "English", "status": "complete"}]
    out = [{"code": str(x["code"]), "name": str(x.get("name") or x["code"]),
            "status": str(x.get("status") or "partial")}
           for x in (data.get("languages") or []) if isinstance(x, dict) and x.get("code")]
    _langs_cache = (mtime, out)
    return out


def codes() -> list[str]:
    return [x["code"] for x in languages()]


def normalize(code: str | None) -> str | None:
    """'pt', 'pt_br', 'PT-br', 'pt-BR,pt;q=0.9' -> 'pt-BR'; unknown -> None."""
    if not code:
        return None
    raw = str(code).split(",")[0].split(";")[0].strip().replace("_", "-")
    if not raw:
        return None
    known = codes()
    low = {c.lower(): c for c in known}
    if raw.lower() in low:
        return low[raw.lower()]
    base = raw.split("-")[0].lower()
    if base in low:
        return low[base]
    for c in known:                       # 'pt' -> 'pt-BR'
        if c.split("-")[0].lower() == base:
            return c
    return None


# ----------------------------------------------------------------- instance language
_data_root_provider = None        # the console points this at deps.DATA_ROOT (read at call time)
_inst_cache: dict[str, tuple[float, str | None]] = {}


def set_data_root_provider(fn) -> None:
    global _data_root_provider
    _data_root_provider = fn


def _data_root(data_root: Path | str | None = None) -> Path:
    if data_root:
        return Path(data_root)
    if _data_root_provider is not None:
        return Path(_data_root_provider())
    return Path(os.environ.get("NETOPS_UI_DATA_ROOT") or REPO_ROOT)


def project_config(data_root: Path | str | None = None) -> Path:
    return _data_root(data_root) / "core" / "config" / "project-config.yaml"


def instance_language(data_root: Path | str | None = None) -> str | None:
    """instance.language from project-config.yaml, or None when not chosen yet (cached by mtime)."""
    path = project_config(data_root)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _inst_cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        import yaml  # noqa: PLC0415
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    lang = (cfg.get("instance") or {}).get("language") if isinstance(cfg, dict) else None
    out = normalize(lang) if isinstance(lang, str) else None
    _inst_cache[str(path)] = (mtime, out)
    return out


def write_instance_language(lang: str, data_root: Path | str | None = None) -> str:
    """Write instance.language (round-trip YAML: keeps comments). Returns the normalized code."""
    code = normalize(lang)
    if not code:
        raise ValueError(f"unsupported language: {lang!r}")
    path = project_config(data_root)
    if not path.exists():
        example = path.with_name("project-config.example.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(example.read_text(encoding="utf-8") if example.exists() else "", encoding="utf-8")
    from ruamel.yaml import YAML  # noqa: PLC0415
    y = YAML()
    y.preserve_quotes = True
    data = y.load(path.read_text(encoding="utf-8")) or {}
    inst = data.get("instance")
    if not isinstance(inst, dict):
        data["instance"] = {"language": code}
    else:
        inst["language"] = code
    tmp = path.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        y.dump(data, f)
    os.replace(tmp, path)
    return code


def default_lang(data_root: Path | str | None = None) -> str:
    """Language for output with no explicit choice: NETOPS_LANG -> instance -> legacy default."""
    return normalize(os.environ.get("NETOPS_LANG")) or instance_language(data_root) or LEGACY_DEFAULT


def current_lang() -> str:
    return _ctx_lang.get() or default_lang()


def set_context_lang(lang: str | None):
    """Set the language for the current request/thread context. Returns a token for reset_context_lang."""
    return _ctx_lang.set(normalize(lang))


def reset_context_lang(token) -> None:
    _ctx_lang.reset(token)


# ----------------------------------------------------------------- catalogs
def _flatten(prefix: str, obj, out: dict) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(obj, str):
        out[prefix] = obj


def _load_dir(lang: str) -> dict:
    d = LOCALES_DIR / lang
    out: dict[str, str] = {}
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _flatten(f.stem, data, out)
    return out


def _dir_mtime(lang: str) -> float:
    d = LOCALES_DIR / lang
    try:
        return max([d.stat().st_mtime] + [f.stat().st_mtime for f in d.glob("*.json")])
    except OSError:
        return 0.0


def raw_catalog(lang: str) -> dict:
    """Only the keys present in core/locales/<lang>/ (no fallback). Cached by mtime."""
    m = _dir_mtime(lang)
    with _lock:
        hit = _cache.get(lang)
        if hit and hit[0] == m:
            return hit[1]
    cat = _load_dir(lang)
    with _lock:
        _cache[lang] = (m, cat)
    return cat


def catalog(lang: str | None) -> dict:
    """Merged catalog: English base + the language on top."""
    code = normalize(lang) or SOURCE_LANG
    base = dict(raw_catalog(SOURCE_LANG))
    if code != SOURCE_LANG:
        base.update(raw_catalog(code))
    return base


# ----------------------------------------------------------------- t()
def plural_category(lang: str, n) -> str:
    try:
        n = abs(float(n))
    except (TypeError, ValueError):
        return "other"
    base = (lang or SOURCE_LANG).split("-")[0].lower()
    if base in ("pt", "fr"):
        return "one" if n < 2 and n == int(n) else "other"
    return "one" if n == 1 else "other"


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def t(key: str, _lang: str | None = None, **params) -> str:
    """Translate `key` into `_lang` (positional; default = the current context language)."""
    code = normalize(_lang) or current_lang()
    cat = raw_catalog(code)
    src = raw_catalog(SOURCE_LANG)
    k = key
    if "count" in params:
        cand = f"{key}_{plural_category(code, params['count'])}"
        if cand in cat or cand in src:
            k = cand
        elif f"{key}_other" in cat or f"{key}_other" in src:
            k = f"{key}_other"
    msg = cat.get(k) or src.get(k)
    if msg is None:
        return key
    try:
        return msg.format_map(_SafeDict({k2: v for k2, v in params.items()}))
    except (ValueError, IndexError):
        return msg


_ = t
