# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Tareas periódicas del demonio: test de velocidad programado, cambios de IP, dispositivos nuevos."""
import logging
import os
import time

import common as c
import db
import lan
import reports

log = logging.getLogger("internet-check.jobs")

SPEED_EVERY_HOURS = float(os.environ.get("SPEEDTEST_EVERY_HOURS", "6"))   # 0 = desactivado
SPEED_MIN_DOWN = float(os.environ.get("SPEED_MIN_DOWN_MBPS", "0"))        # 0 = sin alerta
IP_CHECK_MINUTES = float(os.environ.get("IP_CHECK_MINUTES", "5"))         # 0 = desactivado
LAN_SCAN_MINUTES = float(os.environ.get("LAN_SCAN_MINUTES", "10"))        # 0 = desactivado


def _loop(name, interval_s, fn, first_delay=30):
    time.sleep(first_delay)
    while True:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Fallo en la tarea %s", name)
        time.sleep(interval_s)


def speed_tick():
    last = db.last_speedtest()
    if last and time.time() - last["ts"] < SPEED_EVERY_HOURS * 3600:
        return
    if not c.is_online() or not reports.SPEED_LOCK.acquire(blocking=False):
        return
    try:
        res = reports.run_speedtest("auto")
    except Exception as e:  # noqa: BLE001
        log.warning("Test programado fallido: %s", e)
        time.sleep(300)  # no reintentar al minuto siguiente
        return
    finally:
        reports.SPEED_LOCK.release()
    log.info("Test programado: %.1f/%.1f Mbps, %.0f ms", res["down_mbps"], res["up_mbps"], res["ping_ms"])
    if SPEED_MIN_DOWN and res["down_mbps"] < SPEED_MIN_DOWN:
        c.send_telegram(f"⚠️ Velocidad baja en {c.NAME}: ⬇️ {res['down_mbps']:.1f} Mbps "
                        f"(umbral {SPEED_MIN_DOWN:g} Mbps)\n⬆️ {res['up_mbps']:.1f} Mbps · {res['ping_ms']:.0f} ms")


def ip_tick():
    ip = c.public_ip()
    if not ip:
        return
    old = db.kv_get("public_ip")
    if old and old != ip:
        if c.send_telegram(f"🔄 La IP pública de {c.NAME} ha cambiado:\n{old} → {ip}"):
            db.kv_set("public_ip", ip)
    else:
        db.kv_set("public_ip", ip)


def lan_tick():
    devs = lan.scan()
    if devs is None:
        return
    first = db.kv_get("lan_baseline") is None
    new = [d for d in devs if db.upsert_device(d["mac"], d["ip"], d.get("netbios") or d["hostname"])]
    if first:
        db.kv_set("lan_baseline", "1")  # primera pasada: solo memoriza lo que hay
        log.info("Red local memorizada: %d dispositivos", len(devs))
        return
    if new:
        rows = "\n".join(lan.describe(d) for d in new)
        c.send_telegram(f"🆕 Dispositivo nuevo en la red de {c.NAME}:\n{rows}")


def start_all():
    import threading
    # (nombre, valor de activación, segundos entre ejecuciones, función, espera inicial)
    # El test programado se evalúa cada minuto y decide por su último resultado guardado.
    jobs = [
        ("speedtest", SPEED_EVERY_HOURS, 60, speed_tick, 60),
        ("ip", IP_CHECK_MINUTES, IP_CHECK_MINUTES * 60, ip_tick, 20),
        ("lan", LAN_SCAN_MINUTES, LAN_SCAN_MINUTES * 60, lan_tick, 45),
    ]
    for name, enabled, interval, fn, delay in jobs:
        if enabled <= 0:
            log.info("Tarea %s desactivada", name)
            continue
        threading.Thread(target=_loop, args=(name, interval, fn, delay), daemon=True).start()
