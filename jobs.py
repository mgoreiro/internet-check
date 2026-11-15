# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Tareas periódicas del demonio: test de velocidad programado, cambios de IP, dispositivos nuevos."""
import logging
import os
import time
from datetime import datetime

import common as c
import db
import heartbeat
import lan
import metrics
import quiet
import reports
import updates
import watch

log = logging.getLogger("internet-check.jobs")

SPEED_EVERY_HOURS = float(os.environ.get("SPEEDTEST_EVERY_HOURS", "6"))   # 0 = desactivado
SPEED_MIN_DOWN = float(os.environ.get("SPEED_MIN_DOWN_MBPS", "0"))        # 0 = sin alerta
IP_CHECK_MINUTES = float(os.environ.get("IP_CHECK_MINUTES", "5"))         # 0 = desactivado
LAN_SCAN_MINUTES = float(os.environ.get("LAN_SCAN_MINUTES", "10"))        # 0 = desactivado
UPDATE_CHECK_HOURS = float(os.environ.get("UPDATE_CHECK_HOURS", "24"))    # busca versión nueva; 0 = desactivado
PRESENCE_MISSES = int(os.environ.get("PRESENCE_MISSES", "3"))             # escaneos sin verlo para darlo por ausente

QUALITY_INTERVAL = float(os.environ.get("QUALITY_INTERVAL", "60"))        # s entre ráfagas; 0 = desactivado
QUALITY_LOSS_ALERT = float(os.environ.get("QUALITY_LOSS_ALERT", "10"))    # % de pérdida que se considera mala
QUALITY_RTT_ALERT = float(os.environ.get("QUALITY_RTT_ALERT", "300"))     # ms de latencia que se considera mala
QUALITY_ALERT_BURSTS = int(os.environ.get("QUALITY_ALERT_BURSTS", "3"))   # ráfagas seguidas para avisar
HEALTH_MINUTES = float(os.environ.get("HEALTH_MINUTES", "5"))             # 0 = desactivado
HEALTH_TEMP_ALERT = float(os.environ.get("HEALTH_TEMP_ALERT", "75"))      # °C
HEALTH_DISK_ALERT = float(os.environ.get("HEALTH_DISK_ALERT", "90"))      # % usado
HEALTH_MEM_ALERT = float(os.environ.get("HEALTH_MEM_ALERT", "90"))        # % usado
RETENTION_DAYS = float(os.environ.get("RETENTION_DAYS", "30"))            # calidad y salud
REPORT_DAILY_TIME = os.environ.get("REPORT_DAILY_TIME", "08:00").strip().lower()   # HH:MM; "off" = desactivado
REPORT_WEEKLY_DAY = os.environ.get("REPORT_WEEKLY_DAY", "mon").strip().lower()     # mon..sun; "off" = solo diario

WEEKDAYS = {"mon": 0, "lun": 0, "tue": 1, "mar": 1, "wed": 2, "mie": 2, "thu": 3, "jue": 3,
            "fri": 4, "vie": 4, "sat": 5, "sab": 5, "sun": 6, "dom": 6}


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
        quiet.notify(f"⚠️ Velocidad baja en {c.NAME}: ⬇️ {res['down_mbps']:.1f} Mbps "
                     f"(umbral {SPEED_MIN_DOWN:g} Mbps)\n⬆️ {res['up_mbps']:.1f} Mbps · {res['ping_ms']:.0f} ms")


def ip_tick():
    ip = c.public_ip()
    if not ip:
        return
    old = db.kv_get("public_ip")
    if old and old != ip:
        if quiet.notify(f"🔄 La IP pública de {c.NAME} ha cambiado:\n{old} → {ip}"):
            db.kv_set("public_ip", ip)
    else:
        db.kv_set("public_ip", ip)


def lan_tick():
    devs = lan.scan()
    if devs is None:
        return
    first = db.kv_get("lan_baseline") is None
    new = [d for d in devs if db.upsert_device(d["mac"], d["ip"], d.get("netbios") or d["hostname"])]
    events = db.presence_update({d["mac"] for d in devs}, PRESENCE_MISSES)
    if first:
        db.kv_set("lan_baseline", "1")  # primera pasada: solo memoriza lo que hay
        log.info("Red local memorizada: %d dispositivos", len(devs))
        return
    if new:
        names = db.aliases()
        rows = "\n".join(lan.describe(d, alias=names.get(d["mac"])) for d in new)
        quiet.notify(f"🆕 Dispositivo nuevo en la red de {c.NAME}:\n{rows}")
    for row, kind in events:  # llegadas y salidas de los dispositivos vigilados
        who = row["alias"] or row["hostname"] or row["mac"]
        if kind == "arrived":
            quiet.notify(f"🏠 {who} ha llegado a casa.")
        else:
            quiet.notify(f"🚪 {who} se ha ido: no se ve en la red desde hace {c.fmt_ago(time.time() - (row['last_seen'] or 0))}.")


# ---- calidad de la conexión ----
_q = {"bad": 0, "good": 0, "degraded": False, "dns_bad": 0, "dns_down": False}


def evaluate_quality(q):
    """Avisa de degradación y de fallos de DNS con histéresis (varias ráfagas seguidas)."""
    if q["loss"] >= 100:  # corte total: ya lo gestiona el monitor
        return
    bad = q["loss"] >= QUALITY_LOSS_ALERT or (q["rtt_avg"] or 0) >= QUALITY_RTT_ALERT
    _q["bad"], _q["good"] = (_q["bad"] + 1, 0) if bad else (0, _q["good"] + 1)
    detail = (f"pérdida {q['loss']:.0f} % · latencia {q['rtt_avg'] or 0:.0f} ms "
              f"(máx {q['rtt_max'] or 0:.0f}) · jitter {q['jitter']:.0f} ms")
    if not _q["degraded"] and _q["bad"] >= QUALITY_ALERT_BURSTS:
        _q["degraded"] = True
        quiet.notify(f"⚠️ Conexión degradada en {c.NAME}\n{detail}", broadcast=True)
    elif _q["degraded"] and _q["good"] >= QUALITY_ALERT_BURSTS:
        _q["degraded"] = False
        quiet.notify(f"✅ Conexión estable de nuevo en {c.NAME}\n{detail}", broadcast=True)

    _q["dns_bad"] = 0 if q["dns_ok"] else _q["dns_bad"] + 1
    if not _q["dns_down"] and _q["dns_bad"] >= QUALITY_ALERT_BURSTS:
        _q["dns_down"] = True
        quiet.notify(f"⚠️ El DNS no responde en {c.NAME}, pero hay conexión a Internet.", broadcast=True)
    elif _q["dns_down"] and q["dns_ok"]:
        _q["dns_down"] = False
        quiet.notify(f"✅ El DNS vuelve a responder en {c.NAME} ({q['dns_ms']:.0f} ms).", broadcast=True)


def quality_tick():
    if c.SPEED_BUSY.is_set():  # medir mientras se satura la línea falsearía la latencia
        return
    q = metrics.measure_quality()
    if q is None:
        return
    db.add_quality(q)
    evaluate_quality(q)


# ---- salud del equipo ----
_alerted = {}


def _watch(key, value, limit, clear_margin, on_msg, off_msg):
    """Avisa una vez al superar `limit` y otra al volver a la normalidad."""
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
    db.add_health(h)
    db.prune(time.time() - RETENTION_DAYS * 86400)
    n = c.NAME
    _watch("temp", h["temp"], HEALTH_TEMP_ALERT, 5,
           f"🌡️ {n}: CPU a {h['temp'] or 0:.0f} °C (umbral {HEALTH_TEMP_ALERT:g} °C)",
           f"✅ {n}: la temperatura de la CPU vuelve a la normalidad ({h['temp'] or 0:.0f} °C)")
    _watch("disk", h["disk_pct"], HEALTH_DISK_ALERT, 3,
           f"💾 {n}: disco al {h['disk_pct'] or 0:.0f} % (umbral {HEALTH_DISK_ALERT:g} %)",
           f"✅ {n}: el espacio en disco vuelve a la normalidad ({h['disk_pct'] or 0:.0f} %)")
    _watch("mem", h["mem_pct"], HEALTH_MEM_ALERT, 5,
           f"🧠 {n}: memoria al {h['mem_pct'] or 0:.0f} % (umbral {HEALTH_MEM_ALERT:g} %)",
           f"✅ {n}: la memoria vuelve a la normalidad ({h['mem_pct'] or 0:.0f} %)")


# ---- informes programados ----

def _report_time():
    try:
        hh, mm = REPORT_DAILY_TIME.split(":")
        return int(hh), int(mm)
    except ValueError:
        return None  # "off", vacío o mal escrito


def report_tick():
    when = _report_time()
    if when is None or quiet.is_quiet():  # en modo no molestar se espera a que termine
        return
    now = datetime.now()
    if (now.hour, now.minute) < when:
        return
    today = now.strftime("%Y-%m-%d")
    if db.kv_get("report_last") == today:
        return
    if time.time() - db.ensure_installed_at() < 3600:  # recién instalado: aún no hay nada que contar
        return
    weekly = WEEKDAYS.get(REPORT_WEEKLY_DAY) == now.weekday()
    if c.send_telegram(reports.period_report_text(168 if weekly else 24)):
        db.kv_set("report_last", today)  # si falla el envío, se reintenta en el siguiente ciclo


# ---- versión nueva ----

def update_tick():
    """Avisa una sola vez de cada versión nueva; nunca instala nada."""
    if quiet.is_quiet():
        return
    rel, newer, error = updates.check()
    if error:
        log.info("No se pudo comprobar si hay versión nueva: %s", error)
        return
    if newer and db.kv_get("update_notified") != rel["version"]:
        if c.send_telegram(updates.message(rel)):
            db.kv_set("update_notified", rel["version"])


# ---- vigilancia de servicios, latido y modo no molestar ----

def watch_tick():
    # Las caídas de los servicios vigilados son urgentes: llegan aunque esté activo el modo no molestar
    watch.tick(lambda text: c.send_telegram(text, broadcast=True))


def quiet_tick():
    quiet.flush()


def start_all():
    import threading
    # (nombre, valor de activación, segundos entre ejecuciones, función, espera inicial)
    # El test programado se evalúa cada minuto y decide por su último resultado guardado.
    jobs = [
        ("speedtest", SPEED_EVERY_HOURS, 60, speed_tick, 60),
        ("ip", IP_CHECK_MINUTES, IP_CHECK_MINUTES * 60, ip_tick, 20),
        ("lan", LAN_SCAN_MINUTES, LAN_SCAN_MINUTES * 60, lan_tick, 45),
        ("quality", QUALITY_INTERVAL, QUALITY_INTERVAL, quality_tick, 30),
        ("health", HEALTH_MINUTES, HEALTH_MINUTES * 60, health_tick, 15),
        ("report", 1 if _report_time() else 0, 60, report_tick, 90),
        ("update", UPDATE_CHECK_HOURS, UPDATE_CHECK_HOURS * 3600, update_tick, 180),
        ("watch", watch.WATCH_INTERVAL if watch.parse_targets() else 0, watch.WATCH_INTERVAL, watch_tick, 40),
        ("heartbeat", heartbeat.INTERVAL if heartbeat.URL else 0, heartbeat.INTERVAL, heartbeat.tick, 5),
        ("quiet", 1, 60, quiet_tick, 25),
    ]
    for name, enabled, interval, fn, delay in jobs:
        if enabled <= 0:
            log.info("Tarea %s desactivada", name)
            continue
        threading.Thread(target=_loop, args=(name, interval, fn, delay), daemon=True).start()
