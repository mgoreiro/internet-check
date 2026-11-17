# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Textos de estado, caídas, dispositivos, calidad y salud, calculados con los datos en memoria."""
from __future__ import division, print_function, unicode_literals

import threading
import time

import common as c
import heartbeat
import lan
import metrics
import quiet
import state
import watch

SPEED_LOCK = threading.Lock()  # un solo test de velocidad a la vez
SPARKS = "▁▂▃▄▅▆▇█"


def run_speedtest():
    res = c.speedtest()
    state.S["speed"] = res
    return res


def _fmt(value, unit="", digits=0):
    return "—" if value is None else "%.*f%s" % (digits, value, unit)


def status_text():
    now = time.time()
    online = c.is_online()
    S = state.S
    lines = ["📊 Estado · %s" % c.NAME]
    if online:
        lines.append("🟢 Internet: conectado desde hace %s" % c.fmt_ago(now - S["since"]))
    else:
        lines.append("🔴 Internet: SIN conexión")
    if S["outages"]:
        a, b = S["outages"][-1]
        lines.append("🕒 Última caída: %s · %s" % (c.fmt_short(a), c.fmt_duration(b - a)))
    else:
        lines.append("✨ Sin caídas desde %s" % c.fmt_short(state.STARTED))
    avail = state.availability()
    lines.append("📈 Disponibilidad desde el arranque del servicio: %s" % ("—" if avail is None else "%.2f %%" % avail))
    up = c.uptime()
    if up is not None:
        lines.append("⏱️ Router encendido hace %s" % c.fmt_ago(up))
    ip = c.public_ip() if online else None
    if ip:
        lines.append("🌍 IP pública: %s" % ip)
    t = S["speed"]
    if t:
        lines.append("🚀 Último test: ⬇️ %.1f / ⬆️ %.1f Mbps · %.0f ms (hace %s)"
                     % (t["down_mbps"], t["up_mbps"], t["ping_ms"], c.fmt_ago(now - t["ts"])))
    targets = watch.parse_targets()
    if targets:
        bad = watch.down_names() & set(t["name"] for t in targets)
        lines.append("👁️ Servicios vigilados: %d/%d respondiendo%s" % (
            len(targets) - len(bad), len(targets), " · caídos: " + ", ".join(sorted(bad)) if bad else ""))
    beat = heartbeat.status_line()
    if beat:
        lines.append(beat)
    if quiet.is_quiet(now):
        lines.append("🌙 Modo no molestar activo")
    lines.append("ℹ️ Sin base de datos: el historial se borra al reiniciar el servicio.")
    return "\n".join(lines)


def history_text():
    S = state.S
    lines = ["📉 Caídas desde el arranque del servicio · %s" % c.NAME]
    if not S["outages"] and not S["down_since"]:
        lines.append("Ninguna desde %s." % c.fmt_short(state.STARTED))
    for a, b in reversed(S["outages"][-10:]):
        lines.append("• %s → %s · %s" % (c.fmt_short(a), c.fmt_short(b), c.fmt_duration(b - a)))
    if S["down_since"]:
        lines.insert(1, "• %s → en curso" % c.fmt_short(S["down_since"]))
    avail = state.availability()
    lines += ["", "Disponibilidad: %s · monitorizando desde %s"
              % ("—" if avail is None else "%.2f %%" % avail, c.fmt_short(state.STARTED))]
    return "\n".join(lines)


def devices_text():
    try:
        devs = lan.scan()
    except ValueError as e:
        return "❌ %s" % e
    if devs is None:
        return "❌ LAN_CIDR no es válido (ejemplo: 192.168.1.0/24)."
    lines = ["📡 Dispositivos en la red · %d" % len(devs)]
    lines += [lan.describe(d) for d in devs]
    return "\n".join(lines)


def _spark(values):
    known = [v for v in values if v is not None]
    if not known:
        return ""
    lo, hi = min(known), max(known)
    return "".join(" " if v is None else SPARKS[0] if hi - lo < 1e-9 else
                   SPARKS[int((v - lo) / (hi - lo) * (len(SPARKS) - 1))] for v in values)


def _vals(rows, key):
    return [r[key] for r in rows if r[key] is not None]


def _quality_line(rows):
    top = max(_vals(rows, "rtt_max") or [None])
    return "latencia %s (máx %s) · jitter %s · pérdida %s · DNS %s" % (
        _fmt(c.mean(_vals(rows, "rtt_avg")), " ms"), _fmt(top, " ms"), _fmt(c.mean(_vals(rows, "jitter")), " ms"),
        _fmt(c.mean(_vals(rows, "loss")), " %", 1), _fmt(c.mean(_vals(rows, "dns_ms")), " ms"))


def quality_text():
    rows = list(state.S["quality"])
    if not rows:
        return "📶 Aún no hay medidas de calidad (se toman cada minuto)."
    hour = [r for r in rows if r["ts"] >= time.time() - 3600]
    lines = ["📶 Calidad de la conexión · %s" % c.NAME,
             "Última hora (%d medidas): %s" % (len(hour), _quality_line(hour or rows))]
    bad_dns = [r for r in hour if not r["dns_ok"]]
    if bad_dns:
        lines.append("⚠️ El DNS falló en %d de %d medidas" % (len(bad_dns), len(hour)))
    lines += ["", "Latencia (de antigua a reciente):", _spark([r["rtt_avg"] for r in rows]),
              "Pérdida:", _spark([r["loss"] for r in rows])]
    return "\n".join(lines)


def health_text():
    h = metrics.read_health()
    lines = ["🩺 Salud · %s" % c.NAME]
    if h["temp"] is not None:
        lines.append("🌡️ CPU: %s" % _fmt(h["temp"], " °C", 1))
    lines.append("⚙️ Carga: %s  ·  🧠 Memoria usada: %s" % (_fmt(h["load"], "", 2), _fmt(h["mem_pct"], " %")))
    lines.append("💾 Flash: %s usada" % _fmt(h["disk_pct"], " %"))
    up = c.uptime()
    if up is not None:
        lines.append("⏱️ Encendido hace %s" % c.fmt_ago(up))
    return "\n".join(lines)
