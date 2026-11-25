#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Monitoriza la conexión a Internet de un router OpenWrt (Python 3) y avisa por Telegram al recuperarla.

Sin base de datos ni ficheros de estado: todo en memoria. Configuración en /etc/internet-check/*.env.
"""
from __future__ import division, print_function, unicode_literals

import logging
import logging.handlers
import signal
import sys
import threading
import time

import bot
import common as c
import jobs
import state

INTERVAL = int(c.env("CHECK_INTERVAL", "10"))        # segundos entre comprobaciones
FAIL_THRESHOLD = int(c.env("FAIL_THRESHOLD", "3"))   # fallos seguidos para dar por caída
LOG_FILE = c.env("LOG_FILE", "/tmp/internet-check.log")  # en RAM: no gasta flash
BOOT_WINDOW = 900  # si el router lleva menos de esto encendido, se avisa del arranque

log = logging.getLogger("internet-check")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handlers = [logging.StreamHandler()]
    if LOG_FILE and LOG_FILE != "-":
        try:  # rotación pequeña: 100 kB x 2 en RAM
            handlers = [logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=100000, backupCount=1)]
        except (IOError, OSError):
            pass
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)


def notify_until_sent(text, broadcast=True):
    """Reintenta hasta que Telegram acepte el mensaje."""
    while not c.send_telegram(text, broadcast=broadcast):
        time.sleep(15)
    log.info("Mensaje enviado: %s", text.replace("\n", " | "))


def main():
    setup_logging()
    if not c.TOKEN or not c.CHAT_ID:
        log.error("Faltan TELEGRAM_TOKEN y/o TELEGRAM_CHAT_ID en %s", c.BOT_FILE)
        return 1

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    t = threading.Thread(target=bot.run_bot)
    t.daemon = True
    t.start()
    jobs.start_all()

    # Sin disco no se puede distinguir un apagón de un reinicio: solo se avisa de que ha arrancado.
    up = c.uptime()
    boot_msg = None
    if up is not None and up < BOOT_WINDOW:
        boot_msg = "⚡ %s se ha (re)iniciado: lleva encendido %s.\nSe pierde el historial anterior." % (
            c.NAME, c.fmt_duration(up))

    fails = 0
    online = None
    log.info("Iniciado. Hosts=%s intervalo=%ss umbral=%s", c.HOSTS, INTERVAL, FAIL_THRESHOLD)

    while True:
        ok = c.is_online()
        now = time.time()
        if not ok and c.SPEED_BUSY.is_set():
            time.sleep(INTERVAL)  # medir la velocidad satura la línea: no cuenta como fallo
            continue
        if ok:
            fails = 0
            if online is False:
                start = state.outage_close(now)
                notify_until_sent("✅ Internet recuperado en %s.\nCaída: %s\nDuración: %s"
                                  % (c.NAME, c.fmt_time(start), c.fmt_duration(now - start)))
            elif online is None:
                with state.lock:
                    state.S["online"] = True
            if boot_msg:
                notify_until_sent(boot_msg)
                boot_msg = None
            online = True
        else:
            fails += 1
            if online is not False and fails >= FAIL_THRESHOLD:
                online = False
                state.outage_open(now - fails * INTERVAL)
                log.warning("Conexión caída desde %s", c.fmt_time(state.S["down_since"]))
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
