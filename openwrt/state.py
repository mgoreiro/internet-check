# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Estado en memoria. No se escribe nada en disco: al reiniciar el servicio se parte de cero."""
from __future__ import division, print_function, unicode_literals

import threading
import time

STARTED = time.time()
MAX_OUTAGES = 20
MAX_QUALITY = 60  # una hora de medidas a una por minuto

lock = threading.Lock()
S = {
    "online": None,         # None hasta la primera comprobación
    "since": STARTED,       # desde cuándo está en el estado actual
    "down_since": None,
    "outages": [],          # [(inicio, fin)] las más recientes al final
    "speed": None,          # último test de velocidad
    "quality": [],          # últimas ráfagas de calidad
    "down_total": 0.0,      # segundos de caída acumulados desde el arranque
}


def outage_open(start):
    with lock:
        S["online"], S["down_since"], S["since"] = False, start, start


def outage_close(end):
    """Cierra la caída en curso y devuelve su inicio."""
    with lock:
        start = S["down_since"] or end
        S["outages"] = (S["outages"] + [(start, end)])[-MAX_OUTAGES:]
        S["down_total"] += max(end - start, 0)
        S["online"], S["down_since"], S["since"] = True, None, end
        return start


def availability():
    """% de disponibilidad desde que arrancó el servicio, o None si es muy pronto."""
    now = time.time()
    span = now - STARTED
    if span < 60:
        return None
    with lock:
        down = S["down_total"] + (now - S["down_since"] if S["down_since"] else 0)
    return 100 * (1 - min(down, span) / span)


def add_quality(q):
    with lock:
        S["quality"] = (S["quality"] + [q])[-MAX_QUALITY:]
