# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Calidad de la conexión (latencia, jitter, pérdida, DNS) y salud del router."""
from __future__ import division, print_function, unicode_literals

import glob
import os
import socket
import threading
import time

import common as c

PROBES = int(c.env("QUALITY_PROBES", "10"))
PROBE_TIMEOUT = float(c.env("QUALITY_TIMEOUT", "1.0"))
DNS_TIMEOUT = 4.0
DNS_NAMES = ["cloudflare.com", "wikipedia.org", "debian.org", "example.com"]
_dns_next = [0]


def pick_target():
    """Primer destino de CHECK_HOSTS que responde, como (host, puerto), o None."""
    for item in c.HOSTS:
        host, _, port = item.rpartition(":")
        try:
            socket.create_connection((host, int(port)), timeout=c.TIMEOUT).close()
            return host, int(port)
        except (socket.error, ValueError):
            continue
    return None


def dns_check():
    """Milisegundos que tarda el resolutor en resolver un nombre, o None si falla."""
    name = DNS_NAMES[_dns_next[0] % len(DNS_NAMES)]
    _dns_next[0] += 1
    out = []

    def work():
        try:
            socket.getaddrinfo(name, None, socket.AF_INET)
            out.append(True)
        except socket.error:
            pass

    t0 = time.time()
    t = threading.Thread(target=work)
    t.daemon = True  # getaddrinfo no se puede cancelar: no esperamos a que termine
    t.start()
    t.join(DNS_TIMEOUT)
    return (time.time() - t0) * 1000 if out else None


def burst(target=None):
    """Ráfaga de conexiones TCP: latencia media/máxima, jitter y % de pérdida. None si no hay destino."""
    target = target or pick_target()
    if not target:
        return None
    rtts, lost = [], 0
    for _ in range(PROBES):
        t0 = time.time()
        try:
            socket.create_connection(target, timeout=PROBE_TIMEOUT).close()
            rtts.append((time.time() - t0) * 1000)
        except socket.error:
            lost += 1
        time.sleep(0.25)
    return {
        "ts": time.time(),
        "rtt_avg": c.mean(rtts), "rtt_max": max(rtts) if rtts else None,
        "jitter": c.pstdev(rtts) if len(rtts) > 1 else 0.0,
        "loss": 100.0 * lost / PROBES,
    }


def measure_quality():
    q = burst()
    if q is None:
        return None
    dns = dns_check()
    q["dns_ms"], q["dns_ok"] = dns, dns is not None
    return q


# ---------------------------------------------------------------- salud

def parse_meminfo(text):
    """% de memoria usada. El kernel del ER-X no tiene MemAvailable: se estima y se descuenta tmpfs."""
    vals = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            vals[key] = int(parts[0])
    total = vals.get("MemTotal")
    if not total:
        return None
    avail = vals.get("MemAvailable")
    if avail is None:
        avail = vals.get("MemFree", 0) + vals.get("Buffers", 0) + vals.get("Cached", 0) - vals.get("Shmem", 0)
    return 100.0 * (1 - max(avail, 0) / total)


def cpu_temp(pattern="/sys/class/thermal/thermal_zone*"):
    """Temperatura de la CPU en °C o None (el ER-X normalmente no tiene sensor)."""
    best = None
    for zone in sorted(glob.glob(pattern)):
        try:
            with open(os.path.join(zone, "temp")) as f:
                value = int(f.read().strip()) / 1000.0
        except (IOError, OSError, ValueError):
            continue
        best = value if best is None else max(best, value)
    return best


def read_health():
    h = {"temp": cpu_temp(), "load": None, "mem_pct": None, "disk_pct": None}
    try:
        h["load"] = os.getloadavg()[0]
    except (OSError, AttributeError):
        pass
    try:
        with open("/proc/meminfo") as f:
            h["mem_pct"] = parse_meminfo(f.read())
    except (IOError, OSError):
        pass
    try:
        st = os.statvfs("/")
        h["disk_pct"] = 100.0 * (1 - st.f_bavail / st.f_blocks) if st.f_blocks else None
    except (OSError, AttributeError):
        pass
    return h
