#!/usr/bin/env python3
"""Expressão cron de 5 campos (min hora dia-do-mês mês dia-da-semana) — sem dependência externa.

Suporta `*`, listas (`1,15`), faixas (`1-5`), passos (`*/15`, `8-18/2`), nomes de mês/dia
(`jan`, `mon`) e os atalhos `@hourly @daily @weekly @monthly @yearly`. Semântica do Vixie cron:
quando dia-do-mês E dia-da-semana são ambos restritos, vale um OU outro.

O horário é avaliado no fuso da tarefa (zoneinfo), não no do servidor — o cron do Debian não
tem CRON_TZ e o servidor roda em UTC. Por isso o despachante (`runner.tick`) avalia as tarefas.
"""
from __future__ import annotations

from datetime import datetime, timedelta

_ALIASES = {
    "@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0", "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *",
}
_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_DAYS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
# (nome, mínimo, máximo, apelidos)
_FIELDS = [("minuto", 0, 59, {}), ("hora", 0, 23, {}), ("dia do mês", 1, 31, {}),
           ("mês", 1, 12, _MONTHS), ("dia da semana", 0, 7, _DAYS)]


class CronError(ValueError):
    """Expressão cron inválida (mensagem em PT-BR, pronta para a UI)."""


def _num(tok: str, lo: int, hi: int, names: dict, label: str) -> int:
    t = tok.strip().lower()
    if t in names:
        return names[t]
    if not t.isdigit():
        raise CronError(f"{label}: valor inválido '{tok}'")
    v = int(t)
    if not lo <= v <= hi:
        raise CronError(f"{label}: {v} fora de {lo}-{hi}")
    return v


def _field(spec: str, lo: int, hi: int, names: dict, label: str) -> tuple[set, bool]:
    """Devolve (valores, restrito?). `*` (com ou sem passo a partir do mínimo) não restringe."""
    out: set[int] = set()
    restricted = True
    for part in spec.split(","):
        if not part:
            raise CronError(f"{label}: lista vazia")
        base, _, step_s = part.partition("/")
        step = 1
        if step_s:
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"{label}: passo inválido '{step_s}'")
            step = int(step_s)
        if base == "*":
            a, b = lo, hi
            if step == 1:
                restricted = False
        elif "-" in base:
            x, _, y = base.partition("-")
            a, b = _num(x, lo, hi, names, label), _num(y, lo, hi, names, label)
            if a > b:
                raise CronError(f"{label}: faixa invertida '{base}'")
        else:
            a = _num(base, lo, hi, names, label)
            b = hi if step_s else a
        out.update(range(a, b + 1, step))
    return out, restricted


class CronExpr:
    def __init__(self, expr: str):
        raw = (expr or "").strip()
        if not raw:
            raise CronError("expressão vazia")
        self.expr = raw
        parts = _ALIASES.get(raw.lower(), raw).split()
        if len(parts) != 5:
            raise CronError("use 5 campos: minuto hora dia-do-mês mês dia-da-semana")
        parsed = [_field(p, lo, hi, names, label) for p, (label, lo, hi, names) in zip(parts, _FIELDS)]
        (self.minutes, _), (self.hours, _), (self.mdays, self.mday_r), (self.months, _), (wd, self.wday_r) = parsed
        self.wdays = {0 if d == 7 else d for d in wd}

    def _day_ok(self, dt: datetime) -> bool:
        if dt.month not in self.months:
            return False
        md = dt.day in self.mdays
        wd = ((dt.weekday() + 1) % 7) in self.wdays   # Python: seg=0; cron: dom=0
        if self.mday_r and self.wday_r:
            return md or wd
        if self.mday_r:
            return md
        if self.wday_r:
            return wd
        return True

    def matches(self, dt: datetime) -> bool:
        return dt.minute in self.minutes and dt.hour in self.hours and self._day_ok(dt)

    def next_after(self, dt: datetime, limit_days: int = 366 * 5) -> datetime | None:
        """Próximo instante (minuto cheio) estritamente depois de `dt`, no fuso de `dt`.

        Itera em hora local "de parede" e reaplica o fuso: lida com horário de verão sem pular dias.
        """
        tz = dt.tzinfo
        cur = dt.replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
        end = cur + timedelta(days=limit_days)
        while cur < end:
            if not self._day_ok(cur):
                cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if cur.hour not in self.hours:
                cur = (cur + timedelta(hours=1)).replace(minute=0)
                continue
            if cur.minute not in self.minutes:
                cur += timedelta(minutes=1)
                continue
            return cur.replace(tzinfo=tz)
        return None


def validate(expr: str) -> str:
    """Normaliza (strip) e valida; levanta CronError."""
    CronExpr(expr)
    return expr.strip()
