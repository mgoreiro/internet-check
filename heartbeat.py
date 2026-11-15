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


MAX_PAUSE_MINUTES = 60
_pause = {"until": 0.0}  # los latidos se detienen hasta esta hora (solo en memoria: un reinicio la cancela)


def pause(minutes) -> float:
    """Detiene los latidos para poder probar la alarma sin tocar cables. Se reanudan solos al acabar."""
    minutes = max(1.0, min(float(minutes), MAX_PAUSE_MINUTES))
    _pause["until"] = time.time() + minutes * 60
    return _pause["until"]


def resume():
    _pause["until"] = 0.0


def is_paused() -> bool:
    return time.time() < _pause["until"]


def tick():
    if URL and not is_paused():
        ping()


def status_line():
    """Línea para /estado, o None si el latido no está configurado."""
    if not URL:
        return None
    if is_paused():
        return f"⏸️ Latido a {host()}: pausado hasta las {time.strftime('%H:%M', time.localtime(_pause['until']))}"
    if _state["ok"] is None:
        return f"💓 Latido a {host()}: aún sin enviar"
    ago = c.fmt_ago(time.time() - _state["ok"])
    return f"💓 Latido a {host()}: " + ("correcto" if not _state["fail"] else f"{_state['fail']} fallos seguidos") + \
        f" (último hace {ago})"


def status_text():
    """Texto de /latido: estado detallado, o cómo configurarlo si no hay URL."""
    if not URL:
        return ("💓 El latido no está configurado.\n\n"
                "Es la alarma de «se ha caído la conexión»: la Pi avisa cada minuto a un servicio externo y es "
                "ese servicio quien avisa a Telegram cuando dejan de llegar los latidos.\n"
                "Pasos en el README, sección «Alarma cuando se cae la conexión (latido)». "
                "Después, en /etc/internet-check/config.env:\nHEARTBEAT_URL=https://hc-ping.com/tu-codigo-secreto")
    lines = [status_line(), f"Cada {INTERVAL:g} s a {host()} (la URL no se muestra: lleva un código secreto)."]
    if _state["sent"]:
        lines.append(f"Latidos entregados desde el arranque: {_state['sent']}.")
    return "\n".join(lines)
