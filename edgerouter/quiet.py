# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Modo no molestar: retiene los avisos poco urgentes y los entrega juntos al terminar (todo en memoria).

Horario fijo `QUIET_HOURS=23:00-07:00` (`off` = sin horario) y modo manual desde el bot (`/silencio 8`).
Las caídas de Internet, los reinicios y las caídas de servicios vigilados llegan siempre.
"""
from __future__ import division, print_function, unicode_literals

import threading
import time
from datetime import datetime

import common as c

QUIET_HOURS = c.env("QUIET_HOURS", "off").strip().lower()
MAX_HELD = 50
MAX_DIGEST_LINES = 25

_lock = threading.Lock()
_manual = {"until": 0.0}
_held = []  # [(ts, texto, broadcast)]


def _window():
    try:
        start, end = QUIET_HOURS.split("-")
        sh, sm = start.split(":")
        eh, em = end.split(":")
        return int(sh) * 60 + int(sm), int(eh) * 60 + int(em)
    except ValueError:
        return None


def is_quiet(now=None):
    now = time.time() if now is None else now
    if now < _manual["until"]:
        return True
    window = _window()
    if not window or window[0] == window[1]:
        return False
    start, end = window
    dt = datetime.fromtimestamp(now)
    minute = dt.hour * 60 + dt.minute
    return start <= minute < end if start < end else (minute >= start or minute < end)


def set_manual(hours):
    _manual["until"] = time.time() + hours * 3600 if hours and hours > 0 else 0.0


def status_text():
    now = time.time()
    lines = []
    if now < _manual["until"]:
        lines.append("🌙 Modo no molestar activo hasta las %s (%s más)."
                     % (datetime.fromtimestamp(_manual["until"]).strftime(str("%H:%M")), c.fmt_ago(_manual["until"] - now)))
    elif is_quiet(now):
        lines.append("🌙 Modo no molestar activo (horario programado).")
    else:
        lines.append("🔔 Modo no molestar desactivado.")
    window = _window()
    if window and window[0] != window[1]:
        lines.append("Horario programado: %s" % QUIET_HOURS)
    if _held:
        lines.append("Avisos retenidos: %d (se entregarán juntos al terminar)." % len(_held))
    lines.append("Siguen llegando siempre: caídas de Internet, reinicios y caídas de servicios vigilados.")
    return "\n".join(lines)


def notify(text, broadcast=False):
    """Envía un aviso poco urgente o, con el modo activo, lo retiene."""
    if is_quiet():
        with _lock:
            _held.append((time.time(), text, broadcast))
            del _held[:-MAX_HELD]
        return True
    return c.send_telegram(text, broadcast=broadcast)


def flush():
    """Entrega el resumen de lo retenido cuando termina el modo no molestar."""
    if is_quiet():
        return False
    with _lock:
        rows = list(_held)
    if not rows:
        return False
    lines = ["🌙 Resumen del modo no molestar (%d aviso%s):" % (len(rows), "s" if len(rows) != 1 else "")]
    for ts, text, _b in rows[:MAX_DIGEST_LINES]:
        parts = text.splitlines() or [""]
        lines.append("• %s · %s%s" % (c.fmt_short(ts), parts[0], " (+%d líneas)" % (len(parts) - 1) if len(parts) > 1 else ""))
    if len(rows) > MAX_DIGEST_LINES:
        lines.append("… y %d más" % (len(rows) - MAX_DIGEST_LINES))
    if c.send_telegram("\n".join(lines), broadcast=any(r[2] for r in rows)):
        with _lock:
            del _held[:len(rows)]
        return True
    return False
