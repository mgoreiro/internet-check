# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Tareas periódicas: cambio de IP, dispositivos nuevos, presencia, calidad, salud, vigilancia y latido."""
from __future__ import division, print_function, unicode_literals

import logging
import threading
import time

import common as c
import heartbeat
import lan
import metrics
import quiet
import state
import watch

log = logging.getLogger("internet-check.jobs")

IP_CHECK_MINUTES = float(c.env("IP_CHECK_MINUTES", "5"))       # 0 = desactivado
LAN_SCAN_MINUTES = float(c.env("LAN_SCAN_MINUTES", "10"))      # 0 = desactivado
PRESENCE_MISSES = int(c.env("PRESENCE_MISSES", "3"))           # escaneos sin verlo para darlo por ausente
QUALITY_INTERVAL = float(c.env("QUALITY_INTERVAL", "60"))      # 0 = desactivado
QUALITY_LOSS_ALERT = float(c.env("QUALITY_LOSS_ALERT", "10"))
QUALITY_RTT_ALERT = float(c.env("QUALITY_RTT_ALERT", "300"))
QUALITY_ALERT_BURSTS = int(c.env("QUALITY_ALERT_BURSTS", "3"))
HEALTH_MINUTES = float(c.env("HEALTH_MINUTES", "5"))           # 0 = desactivado
HEALTH_TEMP_ALERT = float(c.env("HEALTH_TEMP_ALERT", "85"))
HEALTH_DISK_ALERT = float(c.env("HEALTH_DISK_ALERT", "90"))
HEALTH_MEM_ALERT = float(c.env("HEALTH_MEM_ALERT", "90"))

_mem = {"ip": None, "macs": None, "present": {}, "misses": {}}


def _loop(name, interval_s, fn, first_delay=30):
    time.sleep(first_delay)
    while True:
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Fallo en la tarea %s", name)
        time.sleep(interval_s)


def ip_tick():
    ip = c.public_ip()
    if not ip:
        return
    old = _mem["ip"]
    if old and old != ip:
        if quiet.notify("🔄 La IP pública de %s ha cambiado:\n%s → %s" % (c.NAME, old, ip)):
            _mem["ip"] = ip
    else:
        _mem["ip"] = ip


def lan_tick():
    devs = lan.scan()
    if devs is None:
        return
    seen = dict((d["mac"], d) for d in devs)
    if _mem["macs"] is None:  # primera pasada: solo memoriza lo que hay
        _mem["macs"] = set(seen)
        log.info("Red local memorizada: %d dispositivos", len(seen))
    else:
        new = [d for m, d in seen.items() if m not in _mem["macs"]]
        _mem["macs"] |= set(seen)
        if new:
            quiet.notify("🆕 Dispositivo nuevo en la red de %s:\n%s" % (c.NAME, "\n".join(lan.describe(d) for d in new)))
    for name, mac in lan.presence_targets():
        was = _mem["present"].get(mac)  # None = aún no se había mirado: sin aviso
        if mac in seen:
            _mem["misses"][mac] = 0
            if was is False:
                quiet.notify("🏠 %s ha llegado a casa." % name)
            _mem["present"][mac] = True
        elif was is None:
            _mem["present"][mac] = False
        elif was:
            _mem["misses"][mac] = _mem["misses"].get(mac, 0) + 1
            if _mem["misses"][mac] >= PRESENCE_MISSES:
                _mem["present"][mac] = False
                quiet.notify("🚪 %s se ha ido: no se ve en la red." % name)


# ---- calidad de la conexión ----
_q = {"bad": 0, "good": 0, "degraded": False, "dns_bad": 0, "dns_down": False}


def evaluate_quality(q):
    """Avisa de degradación y de fallos de DNS con histéresis (varias ráfagas seguidas)."""
    if q["loss"] >= 100:  # corte total: ya lo gestiona el monitor
        return
    bad = q["loss"] >= QUALITY_LOSS_ALERT or (q["rtt_avg"] or 0) >= QUALITY_RTT_ALERT
    _q["bad"], _q["good"] = (_q["bad"] + 1, 0) if bad else (0, _q["good"] + 1)
    detail = "pérdida %.0f %% · latencia %.0f ms (máx %.0f) · jitter %.0f ms" % (
        q["loss"], q["rtt_avg"] or 0, q["rtt_max"] or 0, q["jitter"])
    if not _q["degraded"] and _q["bad"] >= QUALITY_ALERT_BURSTS:
        _q["degraded"] = True
        quiet.notify("⚠️ Conexión degradada en %s\n%s" % (c.NAME, detail), broadcast=True)
    elif _q["degraded"] and _q["good"] >= QUALITY_ALERT_BURSTS:
        _q["degraded"] = False
        quiet.notify("✅ Conexión estable de nuevo en %s\n%s" % (c.NAME, detail), broadcast=True)

    _q["dns_bad"] = 0 if q["dns_ok"] else _q["dns_bad"] + 1
    if not _q["dns_down"] and _q["dns_bad"] >= QUALITY_ALERT_BURSTS:
        _q["dns_down"] = True
        quiet.notify("⚠️ El DNS no responde en %s, pero hay conexión a Internet." % c.NAME, broadcast=True)
    elif _q["dns_down"] and q["dns_ok"]:
        _q["dns_down"] = False
        quiet.notify("✅ El DNS vuelve a responder en %s (%.0f ms)." % (c.NAME, q["dns_ms"]), broadcast=True)


def quality_tick():
    if c.SPEED_BUSY.is_set():  # medir mientras se satura la línea falsearía la latencia
        return
    q = metrics.measure_quality()
    if q is None:
        return
    state.add_quality(q)
    evaluate_quality(q)


# ---- salud del router ----
_alerted = {}


def _watch(key, value, limit, clear_margin, on_msg, off_msg):
    if value is None:
        return
    if not _alerted.get(key) and value >= limit:
        _alerted[key] = True
        quiet.notify(on_msg)
    elif _alerted.get(key) and value < limit - clear_margin:
        _alerted[key] = False
        quiet.notify(off_msg)


def health_tick():
    h = metrics.read_health()
    n = c.NAME
    _watch("temp", h["temp"], HEALTH_TEMP_ALERT, 5,
           "🌡️ %s: CPU a %.0f °C (umbral %g °C)" % (n, h["temp"] or 0, HEALTH_TEMP_ALERT),
           "✅ %s: la temperatura vuelve a la normalidad (%.0f °C)" % (n, h["temp"] or 0))
    _watch("disk", h["disk_pct"], HEALTH_DISK_ALERT, 3,
           "💾 %s: flash al %.0f %% (umbral %g %%)" % (n, h["disk_pct"] or 0, HEALTH_DISK_ALERT),
           "✅ %s: el espacio en flash vuelve a la normalidad (%.0f %%)" % (n, h["disk_pct"] or 0))
    _watch("mem", h["mem_pct"], HEALTH_MEM_ALERT, 5,
           "🧠 %s: memoria al %.0f %% (umbral %g %%)" % (n, h["mem_pct"] or 0, HEALTH_MEM_ALERT),
           "✅ %s: la memoria vuelve a la normalidad (%.0f %%)" % (n, h["mem_pct"] or 0))


def watch_tick():
    # Las caídas de los servicios vigilados son urgentes: llegan aunque esté activo el modo no molestar
    watch.tick(lambda text: c.send_telegram(text, broadcast=True))


def start_all():
    # (nombre, valor de activación, segundos entre ejecuciones, función, espera inicial)
    jobs = [
        ("ip", IP_CHECK_MINUTES, IP_CHECK_MINUTES * 60, ip_tick, 20),
        ("lan", 1 if LAN_SCAN_MINUTES > 0 and (lan.network() or lan.presence_targets()) else 0,
         LAN_SCAN_MINUTES * 60, lan_tick, 45),
        ("quality", QUALITY_INTERVAL, QUALITY_INTERVAL, quality_tick, 30),
        ("health", HEALTH_MINUTES, HEALTH_MINUTES * 60, health_tick, 15),
        ("watch", watch.WATCH_INTERVAL if watch.parse_targets() else 0, watch.WATCH_INTERVAL, watch_tick, 40),
        ("heartbeat", heartbeat.INTERVAL if heartbeat.URL else 0, heartbeat.INTERVAL, heartbeat.tick, 5),
        ("quiet", 1, 60, quiet.flush, 25),
    ]
    for name, enabled, interval, fn, delay in jobs:
        if enabled <= 0:
            log.info("Tarea %s desactivada", name)
            continue
        t = threading.Thread(target=_loop, args=(name, interval, fn, delay))
        t.daemon = True
        t.start()
