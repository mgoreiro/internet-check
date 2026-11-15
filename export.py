# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Exportación del histórico a CSV, empaquetado en un .zip."""
import csv
import io
import time
import zipfile
from datetime import datetime

import common as c
import db


def _iso(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts is not None else ""


def _num(value, digits=2):
    return "" if value is None else round(value, digits)


def _csv(header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def build_zip(days=None):
    """Devuelve (bytes del zip, {fichero: nº de filas}). days=None exporta todo el histórico."""
    now = time.time()
    t0 = now - days * 86400 if days else 0
    tables = {}

    outages = db.outages_between(t0, now)
    tables["caidas.csv"] = (_csv(
        ["inicio", "fin", "duracion_s", "tipo", "inicio_epoch", "fin_epoch"],
        [[_iso(r["start"]), _iso(r["end"]) if r["end"] else "en curso", round((r["end"] or now) - r["start"]),
          r["kind"], round(r["start"]), round(r["end"]) if r["end"] else ""] for r in outages]), len(outages))

    tests = db.speedtests_between(t0, now)
    tables["velocidad.csv"] = (_csv(
        ["fecha", "bajada_mbps", "subida_mbps", "latencia_ms", "origen", "epoch"],
        [[_iso(r["ts"]), _num(r["down"]), _num(r["up"]), _num(r["ping"], 1), r["source"], round(r["ts"])]
         for r in tests]), len(tests))

    quality = db.quality_between(t0, now)
    tables["calidad.csv"] = (_csv(
        ["fecha", "latencia_media_ms", "latencia_max_ms", "jitter_ms", "perdida_pct", "dns_ms", "dns_ok", "epoch"],
        [[_iso(r["ts"]), _num(r["rtt_avg"], 1), _num(r["rtt_max"], 1), _num(r["jitter"], 1), _num(r["loss"], 1),
          _num(r["dns_ms"], 1), "" if r["dns_ok"] is None else r["dns_ok"], round(r["ts"])] for r in quality]),
        len(quality))

    health = db.health_between(t0, now)
    tables["salud.csv"] = (_csv(
        ["fecha", "temp_c", "carga", "memoria_pct", "disco_pct", "bd_kb", "epoch"],
        [[_iso(r["ts"]), _num(r["temp"], 1), _num(r["load"]), _num(r["mem_pct"], 1), _num(r["disk_pct"], 1),
          _num(r["db_kb"], 0), round(r["ts"])] for r in health]), len(health))

    period = f"últimos {days} días" if days else "todo el histórico"
    readme = (f"internet-check · exportación de {c.NAME}\n"
              f"Generado: {_iso(now)} (hora local del equipo)\n"
              f"Periodo: {period}\n\n"
              "Ficheros (CSV, UTF-8 con BOM, separador coma; la columna epoch es la hora en segundos Unix):\n"
              "  caidas.csv     caídas de internet, apagones y reinicios, con su duración\n"
              "  velocidad.csv  tests de velocidad (origen: auto, bot o tui)\n"
              "  calidad.csv    latencia, jitter, pérdida y DNS (una medida por minuto)\n"
              "  salud.csv      temperatura, carga, memoria y disco de la Pi\n\n"
              "La calidad y la salud solo se conservan el número de días indicado en RETENTION_DAYS.\n")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("LEEME.txt", readme)
        for name, (text, _) in tables.items():
            zf.writestr(name, text.encode("utf-8-sig"))  # el BOM hace que Excel respete los acentos
    return out.getvalue(), {name: count for name, (_, count) in tables.items()}


def filename(days=None):
    suffix = f"{days}d" if days else "todo"
    return f"internet-check_{c.NAME}_{datetime.now().strftime('%Y%m%d')}_{suffix}.zip"


def summary_text(counts, days=None):
    period = f"últimos {days} días" if days else "todo el histórico"
    return (f"📤 Exportación de {c.NAME} · {period}\n"
            f"caídas: {counts['caidas.csv']} · tests: {counts['velocidad.csv']} · "
            f"calidad: {counts['calidad.csv']} · salud: {counts['salud.csv']} filas")
