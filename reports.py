# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Textos de informe compartidos por el bot y la TUI, y el test de velocidad con histórico."""
import logging
import sqlite3
import threading
import time

import common as c
import db
import lan
import metrics

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


# ---------------------------------------------------------------- calidad y salud

def _vals(rows, key):
    return [r[key] for r in rows if r[key] is not None]


def _mean(values):
    return sum(values) / len(values) if values else None


def _fmt(value, unit="", digits=0):
    return "—" if value is None else f"{value:.{digits}f}{unit}"


def _hourly(rows, key, now, hours=24, agg=_mean):
    """Valor agregado por hora, de más antiguo a más reciente (huecos = None)."""
    buckets = [[] for _ in range(hours)]
    for r in rows:
        idx = hours - 1 - int((now - r["ts"]) // 3600)
        if 0 <= idx < hours and r[key] is not None:
            buckets[idx].append(r[key])
    return [agg(b) if b else None for b in buckets]


def _spark_gaps(values):
    """Sparkline que deja un espacio donde no hay datos."""
    known = [v for v in values if v is not None]
    if not known:
        return ""
    lo, hi = min(known), max(known)
    out = []
    for v in values:
        if v is None:
            out.append(" ")
        elif hi - lo < 1e-9:
            out.append(SPARKS[0])
        else:
            out.append(SPARKS[int((v - lo) / (hi - lo) * (len(SPARKS) - 1))])
    return "".join(out)


def _quality_line(rows):
    rtt, jit, loss = _mean(_vals(rows, "rtt_avg")), _mean(_vals(rows, "jitter")), _mean(_vals(rows, "loss"))
    dns = _mean(_vals(rows, "dns_ms"))
    top = max(_vals(rows, "rtt_max"), default=None)
    return (f"latencia {_fmt(rtt, ' ms')} (máx {_fmt(top, ' ms')}) · jitter {_fmt(jit, ' ms')} · "
            f"pérdida {_fmt(loss, ' %', 1)} · DNS {_fmt(dns, ' ms')}")


def quality_text() -> str:
    now = time.time()
    day = db.quality_between(now - 86400, now)
    if not day:
        return "📶 Aún no hay medidas de calidad (se toman cada minuto)."
    hour = [r for r in day if r["ts"] >= now - 3600]
    lines = [f"📶 Calidad de la conexión · {c.NAME}"]
    if hour:
        lines.append(f"Última hora: {_quality_line(hour)}")
    lines.append(f"Últimas 24 h: {_quality_line(day)}")
    dns_fail = [r for r in day if r["dns_ok"] == 0]
    if dns_fail:
        lines.append(f"⚠️ El DNS falló en {len(dns_fail)} de {len(day)} medidas")
    lines += ["", "Latencia por hora (24 h, de antigua a reciente):",
              _spark_gaps(_hourly(day, "rtt_avg", now)),
              "Pérdida por hora:",
              _spark_gaps(_hourly(day, "loss", now))]
    return "\n".join(lines)


def health_text() -> str:
    now = time.time()
    h = metrics.read_health()
    day = db.health_between(now - 86400, now)
    lines = [f"🩺 Salud · {c.NAME}"]
    temps = _vals(day, "temp")
    t_hist = f"  (24 h: media {_fmt(_mean(temps), ' °C')}, máx {_fmt(max(temps, default=None), ' °C')})" if temps else ""
    lines.append(f"🌡️ CPU: {_fmt(h['temp'], ' °C', 1)}{t_hist}")
    lines.append(f"⚙️ Carga: {_fmt(h['load'], '', 2)}  ·  🧠 Memoria usada: {_fmt(h['mem_pct'], ' %')}")
    lines.append(f"💾 Disco: {_fmt(h['disk_pct'], ' %')} usado  ·  🗄️ Base de datos: "
                 f"{_fmt(None if h['db_kb'] is None else h['db_kb'] / 1024, ' MB', 1)}")
    up = _uptime()
    if up is not None:
        lines.append(f"⏱️ Encendido hace {c.fmt_ago(up)}")
    if temps:
        lines += ["", "Temperatura por hora (24 h):", _spark_gaps(_hourly(day, "temp", now, agg=max))]
    return "\n".join(lines)


# ---------------------------------------------------------------- informe por periodo

def period_report_text(hours: int = 24) -> str:
    now = time.time()
    installed = db.ensure_installed_at()
    t0 = max(now - hours * 3600, installed)
    span = now - t0
    label = {24: "últimas 24 horas", 168: "última semana", 720: "último mes"}.get(hours, f"últimas {hours} h")
    lines = [f"📰 Informe · {c.NAME} · {label}",
             f"{c.fmt_short(t0)} → {c.fmt_short(now)}"]
    if span < 3600:
        return "\n".join(lines + ["", "Aún no hay datos suficientes (menos de una hora de monitorización)."])

    # Disponibilidad y caídas
    outs = db.outages_between(t0, now)
    down = min(db.downtime_between(t0, now), span)
    lines += ["", f"🌐 Disponibilidad: {100 * (1 - down / span):.2f} %"]
    if outs:
        biggest = max(min(o["end"] or now, now) - max(o["start"], t0) for o in outs)
        kinds = {}
        for o in outs:
            kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
        names = {"internet": "internet", "power": "apagón", "reboot": "reinicio"}
        detail = ", ".join(f"{n} {names.get(k, k)}" for k, n in kinds.items())
        lines.append(f"   {len(outs)} caída(s) ({detail}) · total {c.fmt_duration(down)} · "
                     f"la mayor {c.fmt_duration(biggest)}")
    else:
        lines.append("   Sin caídas 🎉")

    # Velocidad
    tests = db.speedtests_between(t0, now)
    if tests:
        d, u = _vals(tests, "down"), _vals(tests, "up")
        lines += ["", f"🚀 Velocidad ({len(tests)} test{'s' if len(tests) != 1 else ''}):",
                  f"   ⬇️ media {_fmt(_mean(d), '', 1)} Mbps (mín {_fmt(min(d), '', 1)} · máx {_fmt(max(d), '', 1)})",
                  f"   ⬆️ media {_fmt(_mean(u), '', 1)} Mbps (mín {_fmt(min(u), '', 1)} · máx {_fmt(max(u), '', 1)})"]

    # Calidad
    qual = db.quality_between(t0, now)
    if qual:
        dns_ok = [r["dns_ok"] for r in qual if r["dns_ok"] is not None]
        lines += ["", f"📶 Calidad: {_quality_line(qual)}"]
        if dns_ok and min(dns_ok) == 0:
            lines.append(f"   ⚠️ DNS correcto en el {100 * sum(dns_ok) / len(dns_ok):.1f} % de las medidas")

    # Equipo
    hl = db.health_between(t0, now)
    if hl:
        temps = _vals(hl, "temp")
        lines += ["", f"🩺 Equipo: CPU {_fmt(_mean(temps), ' °C')} de media (máx {_fmt(max(temps, default=None), ' °C')}) · "
                      f"memoria máx {_fmt(max(_vals(hl, 'mem_pct'), default=None), ' %')} · "
                      f"disco {_fmt(hl[-1]['disk_pct'], ' %')}"]

    # Dispositivos nuevos (se ignora la primera pasada, que solo memoriza lo que había)
    new = db.devices_first_seen_between(max(t0, installed + 600), now)
    if new:
        names = ", ".join((d["hostname"] or d["mac"]) for d in new[:8])
        lines += ["", f"🆕 Dispositivos nuevos: {len(new)} ({names}{'…' if len(new) > 8 else ''})"]
    return "\n".join(lines)
