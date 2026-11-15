# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Modo no molestar: retiene los avisos poco urgentes y los entrega juntos al terminar.

Hay dos formas de activarlo y se suman:
- un horario fijo, `QUIET_HOURS=23:00-07:00` (puede cruzar la medianoche; `off` lo desactiva);
- un modo manual por horas, desde el bot (`/silencio 8`).

Solo afecta a los avisos que pasan por `notify`. Las caídas de Internet, los reinicios y las caídas
de los servicios vigilados siguen llegando siempre.
"""
import os
import time
from datetime import datetime

import common as c
import db

QUIET_HOURS = os.environ.get("QUIET_HOURS", "off").strip().lower()
MAX_DIGEST_LINES = 25


def _window():
    """(inicio, fin) en minutos desde las 00:00, o None si no hay horario válido."""
    try:
        start, end = QUIET_HOURS.split("-")
        sh, sm = start.split(":")
        eh, em = end.split(":")
        return int(sh) * 60 + int(sm), int(eh) * 60 + int(em)
    except ValueError:
        return None


def manual_until():
    value = db.kv_get("dnd_until")
    return float(value) if value else None


def is_quiet(now=None) -> bool:
    now = time.time() if now is None else now
    until = manual_until()
    if until and now < until:
        return True
    window = _window()
    if not window or window[0] == window[1]:
        return False
    start, end = window
    dt = datetime.fromtimestamp(now)
    minute = dt.hour * 60 + dt.minute
    return start <= minute < end if start < end else (minute >= start or minute < end)


def set_manual(hours):
    """Activa el modo manual durante `hours` horas; 0 lo desactiva."""
    if hours and hours > 0:
        db.kv_set("dnd_until", time.time() + hours * 3600)
    else:
        db.kv_del("dnd_until")


def status_text() -> str:
    now = time.time()
    until = manual_until()
    lines = []
    if until and now < until:
        lines.append(f"🌙 Modo no molestar activo hasta las {datetime.fromtimestamp(until).strftime('%H:%M')} "
                     f"({c.fmt_ago(until - now)} más).")
    elif is_quiet(now):
        lines.append("🌙 Modo no molestar activo (horario programado).")
    else:
        lines.append("🔔 Modo no molestar desactivado.")
    window = _window()
    if window and window[0] != window[1]:
        lines.append(f"Horario programado: {QUIET_HOURS}")
    held = len(db.held_all())
    if held:
        lines.append(f"Avisos retenidos: {held} (se entregarán juntos al terminar).")
    lines.append("Siguen llegando siempre: caídas de Internet, reinicios y caídas de servicios vigilados.")
    return "\n".join(lines)


def notify(text, broadcast=False) -> bool:
    """Envía un aviso poco urgente o, con el modo activo, lo retiene. Devuelve True si se entregó o retuvo."""
    if is_quiet():
        db.held_add(text, broadcast)
        return True
    return c.send_telegram(text, broadcast=broadcast)


def flush() -> bool:
    """Entrega el resumen de lo retenido cuando termina el modo no molestar."""
    if is_quiet():
        return False
    rows = db.held_all()
    if not rows:
        return False
    lines = [f"🌙 Resumen del modo no molestar ({len(rows)} aviso{'s' if len(rows) != 1 else ''}):"]
    for r in rows[:MAX_DIGEST_LINES]:
        first, *rest = r["text"].splitlines() or [""]
        lines.append(f"• {c.fmt_short(r['ts'])} · {first}" + (f" (+{len(rest)} líneas)" if rest else ""))
    if len(rows) > MAX_DIGEST_LINES:
        lines.append(f"… y {len(rows) - MAX_DIGEST_LINES} más")
    if c.send_telegram("\n".join(lines), broadcast=any(r["broadcast"] for r in rows)):
        db.held_clear()
        return True
    return False
