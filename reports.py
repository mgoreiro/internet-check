# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Textos de informe compartidos por el bot y la TUI, y el test de velocidad con histórico."""
import logging
import sqlite3
import threading
import time

import common as c
import db
import lan

log = logging.getLogger("internet-check.reports")

# Un solo test de velocidad a la vez (bot, tarea programada)
SPEED_LOCK = threading.Lock()
SPARKS = "▁▂▃▄▅▆▇█"


def run_speedtest(source, on_progress=None) -> dict:
    """Mide, guarda en el histórico y devuelve el resultado."""
    res = c.speedtest(on_progress)
    try:
        db.add_speedtest(res, source)
    except (sqlite3.Error, OSError) as e:
        log.warning("No se pudo guardar el test en el histórico: %s", e)
    return res


def availability(window_s):
    """Porcentaje de disponibilidad en la ventana (acotada al inicio de la monitorización)."""
    now = time.time()
    start = max(now - window_s, db.ensure_installed_at())
    span = now - start
    if span < 60:
        return None
    down = min(db.downtime_between(start, now), span)
    return 100 * (1 - down / span)


def _avail_str(window_s):
    a = availability(window_s)
    return "—" if a is None else f"{a:.2f} %"


def _uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError):
        return None


def spark(values):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return SPARKS[3] * len(values)
    return "".join(SPARKS[int((v - lo) / (hi - lo) * (len(SPARKS) - 1))] for v in values)


def status_text() -> str:
    now = time.time()
    online = c.is_online()
    installed = db.ensure_installed_at()
    outs = db.outages_recent(1)
    lines = [f"📊 Estado · {c.NAME}"]
    if online:
        last_end = outs[0]["end"] if outs and outs[0]["end"] else None
        since = last_end or installed
        lines.append(f"🟢 Internet: conectado desde hace {c.fmt_ago(now - since)}")
    else:
        lines.append("🔴 Internet: SIN conexión")
    if outs and outs[0]["end"]:
        o = outs[0]
        lines.append(f"🕒 Última caída: {c.fmt_short(o['start'])} · {c.fmt_duration(o['end'] - o['start'])}")
    else:
        lines.append(f"✨ Sin caídas desde {c.fmt_short(installed)}")
    lines.append(f"📈 Disponibilidad: 24 h {_avail_str(86400)} · 7 d {_avail_str(7 * 86400)}")
    up = _uptime()
    if up is not None:
        lines.append(f"⏱️ Equipo encendido hace {c.fmt_ago(up)}")
    ip = c.public_ip() if online else None
    if ip:
        lines.append(f"🌍 IP pública: {ip}")
    t = db.last_speedtest()
    if t:
        lines.append(f"🚀 Último test: ⬇️ {t['down']:.1f} / ⬆️ {t['up']:.1f} Mbps · {t['ping']:.0f} ms "
                     f"(hace {c.fmt_ago(now - t['ts'])})")
    return "\n".join(lines)


def history_text() -> str:
    installed = db.ensure_installed_at()
    outs = db.outages_recent(10)
    lines = [f"📉 Caídas recientes · {c.NAME}"]
    if not outs:
        lines.append(f"Ninguna desde {c.fmt_short(installed)}.")
    for o in outs:
        icon = {"power": "⚡ apagado", "reboot": "🔄 reinicio"}.get(o["kind"], "🌐 internet")
        if o["end"]:
            lines.append(f"• {c.fmt_short(o['start'])} → {c.fmt_short(o['end'])} · "
                         f"{c.fmt_duration(o['end'] - o['start'])} ({icon})")
        else:
            lines.append(f"• {c.fmt_short(o['start'])} → en curso ({icon})")
    lines.append("")
    lines.append(f"Disponibilidad: 24 h {_avail_str(86400)} · 7 d {_avail_str(7 * 86400)} "
                 f"· 30 d {_avail_str(30 * 86400)}")
    lines.append(f"Monitorizando desde {c.fmt_short(installed)}")
    return "\n".join(lines)


def speed_history_text() -> str:
    rows = db.speedtests_recent(24)
    if not rows:
        return "📈 Aún no hay tests de velocidad guardados."
    rows = list(reversed(rows))  # de más antiguo a más reciente
    downs = [r["down"] for r in rows]
    ups = [r["up"] for r in rows]
    lines = [
        f"📈 Velocidad · últimos {len(rows)} tests",
        f"⬇️ {spark(downs)}  media {sum(downs) / len(downs):.1f} · mín {min(downs):.1f} · máx {max(downs):.1f} Mbps",
        f"⬆️ {spark(ups)}  media {sum(ups) / len(ups):.1f} · mín {min(ups):.1f} · máx {max(ups):.1f} Mbps",
        "",
    ]
    for r in reversed(rows[-5:]):
        lines.append(f"• {c.fmt_short(r['ts'])} · ⬇️ {r['down']:.1f} · ⬆️ {r['up']:.1f} Mbps · {r['ping']:.0f} ms")
    return "\n".join(lines)


def devices_text() -> str:
    try:
        devs = lan.scan()
    except ValueError as e:
        return f"❌ {e}"
    if devs is None:
        return "❌ No se pudo determinar la red local (define LAN_CIDR en la configuración)."
    lines = [f"📡 Dispositivos en la red · {len(devs) + 1}", f"• {lan.local_ip()} · {c.NAME} (este equipo)"]
    for d in devs:
        new = db.upsert_device(d["mac"], d["ip"], d.get("netbios") or d["hostname"])
        lines.append(lan.describe(d, new))
    return "\n".join(lines)
