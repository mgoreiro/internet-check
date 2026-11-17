# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro
"""Latido (heartbeat): la alarma de «se ha caído la conexión» mientras la conexión está caída.

Con Internet cortado el router no puede escribir a Telegram. Se le da la vuelta: avisa cada minuto a un
servicio externo (Healthchecks.io, Uptime Kuma en modo Push...) y es ese servicio quien manda la alarma
cuando los avisos dejan de llegar. HEARTBEAT_URL lleva un código secreto: nunca se escribe en los logs.
"""
from __future__ import division, print_function, unicode_literals

import logging
import time

import common as c

log = logging.getLogger("internet-check.heartbeat")

URL = c.env("HEARTBEAT_URL").strip()
INTERVAL = float(c.env("HEARTBEAT_SECONDS", "60"))
TIMEOUT = 10
MAX_PAUSE_MINUTES = 60

_state = {"ok": None, "fail": 0, "sent": 0}
_pause = {"until": 0.0}


def host():
    return c.urlparse(URL).hostname or "?"


def ping(url=None):
    """Un latido. Devuelve True si el servicio contestó con éxito."""
    try:
        c.http_get(url or URL, TIMEOUT, 64, headers={"User-Agent": "internet-check"})
    except Exception as e:  # noqa: BLE001
        _state["fail"] += 1
        if _state["fail"] == 1:  # solo el primer fallo de cada racha, y sin la URL
            log.info("Latido no entregado a %s: %s", host(), type(e).__name__)
        return False
    if _state["fail"]:
        log.info("Latido de nuevo entregado a %s tras %d fallos", host(), _state["fail"])
    _state.update(ok=time.time(), fail=0, sent=_state["sent"] + 1)
    return True


def pause(minutes):
    minutes = max(1.0, min(float(minutes), MAX_PAUSE_MINUTES))
    _pause["until"] = time.time() + minutes * 60
    return _pause["until"]


def resume():
    _pause["until"] = 0.0


def is_paused():
    return time.time() < _pause["until"]


def tick():
    if URL and not is_paused():
        ping()


def status_line():
    if not URL:
        return None
    if is_paused():
        return "⏸️ Latido a %s: pausado hasta las %s" % (host(), time.strftime(str("%H:%M"), time.localtime(_pause["until"])))
    if _state["ok"] is None:
        return "💓 Latido a %s: aún sin enviar" % host()
    return "💓 Latido a %s: %s (último hace %s)" % (
        host(), "correcto" if not _state["fail"] else "%d fallos seguidos" % _state["fail"],
        c.fmt_ago(time.time() - _state["ok"]))


def status_text():
    if not URL:
        return ("💓 El latido no está configurado.\n\n"
                "Es la alarma de «se ha caído la conexión»: el router avisa cada minuto a un servicio externo y es "
                "ese servicio quien avisa a Telegram cuando dejan de llegar los latidos.\n"
                "Añade en config.env:\nHEARTBEAT_URL=https://hc-ping.com/tu-codigo-secreto")
    lines = [status_line(), "Cada %g s a %s (la URL no se muestra: lleva un código secreto)." % (INTERVAL, host())]
    if _state["sent"]:
        lines.append("Latidos entregados desde el arranque: %d." % _state["sent"])
    return "\n".join(lines)
