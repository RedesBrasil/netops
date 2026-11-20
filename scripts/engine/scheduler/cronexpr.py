#!/usr/bin/env python3
"""Expressão cron de 5 campos (min hora dia-do-mês mês dia-da-semana) — sobre a biblioteca `croniter`.

`croniter` é a mesma biblioteca do agendador do Hermes Agent (NousResearch): madura, com fuso
(tz-aware), horário de verão e sintaxe estendida (`L` = último dia, `#` = n-ésimo dia da semana,
nomes `jan`/`mon`, atalhos `@daily` etc.). Semântica do Vixie cron: dia-do-mês E dia-da-semana
restritos = vale um OU outro.

Aqui só acrescentamos: exigência de 5 campos (o despachante roda a cada minuto, segundos não fazem
sentido), mensagens em PT-BR para a tela e a mesma API de antes (CronExpr.matches / next_after).
O horário é avaliado no fuso da tarefa (zoneinfo), não no do servidor.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from croniter import CroniterBadCronError, CroniterBadDateError, CroniterError, croniter

from lib import i18n

ALIASES = ("@hourly", "@daily", "@midnight", "@weekly", "@monthly", "@yearly", "@annually")


class CronError(ValueError):
    """Expressão cron inválida (mensagem em PT-BR, pronta para a UI)."""


class CronExpr:
    def __init__(self, expr: str):
        raw = (expr or "").strip()
        if not raw:
            raise CronError(i18n.t("lib_scheduler.cron_empty"))
        if raw.lower() not in ALIASES and len(raw.split()) != 5:
            raise CronError(i18n.t("lib_scheduler.cron_five_fields"))
        try:
            ok = croniter.is_valid(raw)
        except (CroniterError, ValueError, TypeError):
            ok = False
        if not ok:
            raise CronError(i18n.t("lib_scheduler.cron_invalid", expr=raw))
        self.expr = raw

    def matches(self, dt: datetime) -> bool:
        """O minuto de `dt` (no fuso de `dt`) é um horário da expressão?"""
        return croniter.match(self.expr, dt.replace(second=0, microsecond=0))

    def next_after(self, dt: datetime, limit_days: int = 366 * 5) -> datetime | None:
        """Próximo instante (minuto cheio) estritamente depois de `dt`, no fuso de `dt`."""
        start = dt.replace(second=0, microsecond=0)
        try:
            nxt = croniter(self.expr, start).get_next(datetime)
        except (CroniterBadDateError, CroniterBadCronError):
            return None
        if nxt <= dt:   # garantia "estritamente depois" mesmo com segundos em `dt`
            nxt = croniter(self.expr, start + timedelta(minutes=1)).get_next(datetime)
        return nxt if nxt - dt <= timedelta(days=limit_days) else None


def validate(expr: str) -> str:
    """Normaliza (strip) e valida; levanta CronError."""
    CronExpr(expr)
    return expr.strip()
