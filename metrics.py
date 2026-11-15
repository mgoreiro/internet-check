# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Medidas del sistema: calidad de la conexión (latencia, jitter, pérdida, DNS) y salud de la Pi."""
import concurrent.futures as cf
import glob
import os
import shutil
import socket
import statistics
import time

import common as c
import db

PROBES = int(os.environ.get("QUALITY_PROBES", "10"))               # conexiones por ráfaga
PROBE_TIMEOUT = float(os.environ.get("QUALITY_TIMEOUT", "1.0"))    # sin respuesta en este plazo = perdido
DNS_TIMEOUT = 4.0
DNS_NAMES = ["cloudflare.com", "wikipedia.org", "debian.org", "example.com"]
_dns_next = [0]


# ---------------------------------------------------------------- calidad

def pick_target():
    """Primer destino de CHECK_HOSTS que responde, como (host, puerto), o None."""
    for item in c.HOSTS:
        host, _, port = item.rpartition(":")
        try:
            socket.create_connection((host, int(port)), timeout=c.TIMEOUT).close()
            return host, int(port)
        except OSError:
            continue
    return None


def dns_check():
    """Milisegundos que tarda el resolutor del sistema en resolver un nombre, o None si falla."""
    name = DNS_NAMES[_dns_next[0] % len(DNS_NAMES)]
    _dns_next[0] += 1
    ex = cf.ThreadPoolExecutor(1)
    t0 = time.perf_counter()
    try:
        ex.submit(socket.getaddrinfo, name, None, socket.AF_INET).result(timeout=DNS_TIMEOUT)
        return (time.perf_counter() - t0) * 1000
    except Exception:  # noqa: BLE001 (gaierror, timeout...)
        return None
    finally:
        ex.shutdown(wait=False)  # getaddrinfo no se puede cancelar: no esperamos a que termine


def burst(target=None):
    """Ráfaga de conexiones TCP: latencia media/máxima, jitter y % de pérdida. None si no hay destino."""
    target = target or pick_target()
    if not target:
        return None
    rtts, lost = [], 0
    for _ in range(PROBES):
        t0 = time.perf_counter()
        try:
            socket.create_connection(target, timeout=PROBE_TIMEOUT).close()
            rtts.append((time.perf_counter() - t0) * 1000)
        except OSError:
            lost += 1
        time.sleep(0.25)
    return {
        "ts": time.time(),
        "rtt_avg": statistics.mean(rtts) if rtts else None,
        "rtt_max": max(rtts) if rtts else None,
        "jitter": statistics.pstdev(rtts) if len(rtts) > 1 else 0.0,
        "loss": 100.0 * lost / PROBES,
    }


def measure_quality():
    """Una medida completa (ráfaga + DNS) lista para guardar, o None."""
    q = burst()
    if q is None:
        return None
    dns = dns_check()
    q["dns_ms"] = dns
    q["dns_ok"] = dns is not None
    return q


# ---------------------------------------------------------------- salud

def parse_meminfo(text):
    """Porcentaje de memoria usada a partir del texto de /proc/meminfo, o None."""
    vals = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            vals[key] = int(parts[0])
    total, avail = vals.get("MemTotal"), vals.get("MemAvailable")
    if not total or avail is None:
        return None
    return 100.0 * (1 - avail / total)


def cpu_temp(pattern="/sys/class/thermal/thermal_zone*"):
    """Temperatura de la CPU en °C: la zona 'cpu*' si existe y, si no, la más alta."""
    best, cpu = None, None
    for zone in sorted(glob.glob(pattern)):
        try:
            with open(os.path.join(zone, "temp")) as f:
                value = int(f.read().strip()) / 1000.0
            with open(os.path.join(zone, "type")) as f:
                kind = f.read().strip()
        except (OSError, ValueError):
            continue
        if kind.startswith("cpu") and cpu is None:
            cpu = value
        best = value if best is None else max(best, value)
    return cpu if cpu is not None else best


def read_health():
    """Foto del estado del equipo. Los campos que no se pueden leer quedan en None."""
    h = {"ts": time.time(), "temp": cpu_temp(), "load": None, "mem_pct": None, "disk_pct": None, "db_kb": None}
    try:
        h["load"] = os.getloadavg()[0]
    except (OSError, AttributeError):
        pass
    try:
        with open("/proc/meminfo") as f:
            h["mem_pct"] = parse_meminfo(f.read())
    except OSError:
        pass
    try:
        usage = shutil.disk_usage("/")
        h["disk_pct"] = 100.0 * usage.used / usage.total
    except OSError:
        pass
    try:
        h["db_kb"] = os.path.getsize(db.DB_FILE) / 1024.0
    except OSError:
        pass
    return h
