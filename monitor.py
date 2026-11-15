#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Monitoriza la conexión a Internet y avisa por Telegram al recuperarla.

Además atiende un bot bidireccional (test de velocidad, IP pública).
Solo usa la librería estándar (Python 3.7+). Configuración por variables de
entorno (ver config.env.example).
"""
import json
import logging
import os
import signal
import sys
import threading
import time

import bot
import common as c
import db
import jobs

INTERVAL = int(os.environ.get("CHECK_INTERVAL", "10"))      # segundos entre comprobaciones
FAIL_THRESHOLD = int(os.environ.get("FAIL_THRESHOLD", "3"))  # fallos seguidos para dar por caída
STATE_FILE = os.environ.get("STATE_FILE", "/var/lib/internet-check/state.json")

log = logging.getLogger("internet-check")


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        log.warning("No se pudo guardar el estado: %s", e)


def notify_until_sent(text: str) -> None:
    """Reintenta hasta que Telegram acepte el mensaje."""
    while not c.send_telegram(text):
        time.sleep(15)
    log.info("Mensaje enviado: %s", text.replace("\n", " | "))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not c.TOKEN or not c.CHAT_ID:
        log.error("Faltan TELEGRAM_TOKEN y/o TELEGRAM_CHAT_ID")
        return 1

    def on_term(*_):
        # Parada limpia (apt, systemctl stop): que el próximo arranque no avise de "reinicio"
        st = load_state()
        st["clean"] = True
        save_state(st)
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_term)
    db.ensure_installed_at()
    threading.Thread(target=bot.run_bot, daemon=True).start()
    jobs.start_all()

    state = load_state()
    last_alive = state.get("last_alive")
    down_since = state.get("down_since")  # corte de Internet en curso al reiniciar
    boot_msg = None
    requested = db.kv_get("reboot_requested")
    if requested:
        db.kv_del("reboot_requested")
    if requested and time.time() - float(requested) < 1800:
        # Reinicio pedido desde Telegram: no es un apagón ni una caída
        t0 = float(requested)
        db.outage_add_closed(t0, time.time(), "reboot")
        boot_msg = (f"✅ {c.NAME} ha vuelto tras el reinicio solicitado.\n"
                    f"Tardó {c.fmt_duration(time.time() - t0)}.")
    elif last_alive and not state.get("clean") and time.time() - last_alive > INTERVAL * (FAIL_THRESHOLD + 2):
        # Si el último latido es muy antiguo, el equipo estuvo apagado (corte de luz, etc.)
        db.outage_add_closed(last_alive, time.time(), "power")
        boot_msg = (f"⚡ {c.NAME} se ha reiniciado.\nSin servicio desde {c.fmt_time(last_alive)} "
                    f"({c.fmt_duration(time.time() - last_alive)}).")

    fails = 0
    online = None
    log.info("Iniciado. Hosts=%s intervalo=%ss umbral=%s", c.HOSTS, INTERVAL, FAIL_THRESHOLD)

    while True:
        ok = c.is_online()
        now = time.time()
        if not ok and c.SPEED_BUSY.is_set():
            # Medir la velocidad satura la línea: no cuenta como fallo
            save_state({"last_alive": now, "down_since": down_since})
            time.sleep(INTERVAL)
            continue
        if ok:
            fails = 0
            if online is False or down_since:
                start = down_since or now
                if not db.outage_close(now):
                    db.outage_add_closed(start, now)
                notify_until_sent(f"✅ Internet recuperado en {c.NAME}.\n"
                                  f"Caída: {c.fmt_time(start)}\nDuración: {c.fmt_duration(now - start)}")
                down_since = None
            elif boot_msg:
                notify_until_sent(boot_msg)
            boot_msg = None
            online = True
        else:
            fails += 1
            if online is not False and fails >= FAIL_THRESHOLD:
                online = False
                if down_since is None:  # si venía de antes del reinicio, se conserva
                    down_since = now - fails * INTERVAL
                    db.outage_open(down_since)
                log.warning("Conexión caída desde %s", c.fmt_time(down_since))
        state = {"last_alive": now, "down_since": down_since}
        save_state(state)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
