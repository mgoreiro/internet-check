# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro
"""Latido (heartbeat): la alarma de «se ha caído la conexión» mientras la conexión está caída.

Con Internet cortado la Pi no puede escribir a Telegram. La solución es darle la vuelta: la Pi avisa
cada minuto a un servicio externo y es ese servicio quien manda la alarma a Telegram cuando los
avisos dejan de llegar. Sirve también si la Pi se queda sin corriente o se cuelga.

Compatible con cualquier servicio de «push monitor» que reciba una petición GET: Healthchecks.io
(con su integración de Telegram), Uptime Kuma (monitor de tipo Push), Better Stack, etc.
Se configura con HEARTBEAT_URL; la URL lleva un código secreto, por lo que nunca se escribe en los logs.
"""
import logging
import os
import time
import urllib.parse
import urllib.request

import common as c

log = logging.getLogger("internet-check.heartbeat")

URL = os.environ.get("HEARTBEAT_URL", "").strip()
INTERVAL = float(os.environ.get("HEARTBEAT_SECONDS", "60"))
TIMEOUT = 10

_state = {"ok": None, "fail": 0, "sent": 0}  # hora del último latido correcto, fallos seguidos, total enviados


def host() -> str:
    return urllib.parse.urlparse(URL).hostname or "?"


def ping(url=None) -> bool:
    """Un latido. Devuelve True si el servicio contestó con éxito."""
    url = url or URL
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "internet-check"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read(64)
    except Exception as e:  # noqa: BLE001 (sin Internet, DNS, TLS, código HTTP...)
        _state["fail"] += 1
        if _state["fail"] == 1:  # solo el primer fallo de cada racha, y sin la URL
            log.info("Latido no entregado a %s: %s", host(), type(e).__name__)
        return False
    if _state["fail"]:
        log.info("Latido de nuevo entregado a %s tras %d fallos", host(), _state["fail"])
    _state.update(ok=time.time(), fail=0, sent=_state["sent"] + 1)
    return True


def tick():
    if URL:
        ping()


def status_line():
    """Línea para /estado, o None si el latido no está configurado."""
    if not URL:
        return None
    if _state["ok"] is None:
        return f"💓 Latido a {host()}: aún sin enviar"
    ago = c.fmt_ago(time.time() - _state["ok"])
    return f"💓 Latido a {host()}: " + ("correcto" if not _state["fail"] else f"{_state['fail']} fallos seguidos") + \
        f" (último hace {ago})"
