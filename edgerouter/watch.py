# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Vigilancia de equipos y servicios propios (NAS, una web...). Todo en memoria.

WATCH_TARGETS="Nombre=destino,Otro=destino". Un destino puede ser:
  host:puerto        conexión TCP                    NAS=192.168.1.50:5000
  ping://host        ping del sistema                PC=ping://192.168.1.20
  http(s)://...      GET; falla con error de red o código >= 400 (salvo 401 y 403)
Avisa tras WATCH_FAILS fallos seguidos y de nuevo al recuperarse, con la duración de la caída.
"""
from __future__ import division, print_function, unicode_literals

import logging
import socket
import subprocess
import time

import common as c
import lan

log = logging.getLogger("internet-check.watch")

WATCH_TARGETS = c.env("WATCH_TARGETS")
WATCH_INTERVAL = float(c.env("WATCH_INTERVAL", "60"))
WATCH_FAILS = int(c.env("WATCH_FAILS", "3"))
WATCH_TIMEOUT = float(c.env("WATCH_TIMEOUT", "4"))

LAST = {}     # nombre -> (ok | None, ms | None, hora)
_fails = {}   # nombre -> fallos seguidos
_down = {}    # nombre -> hora de inicio de la caída


def parse_targets(text=None):
    targets = []
    for item in (WATCH_TARGETS if text is None else text).split(","):
        name, _, spec = item.partition("=")
        name, spec = name.strip(), spec.strip()
        if not name or not spec:
            continue
        low = spec.lower()
        if low.startswith(("http://", "https://")):
            target = {"kind": "http", "host": c.urlparse(spec).hostname, "port": None}
        elif low.startswith("ping://"):
            target = {"kind": "ping", "host": spec[7:].strip("/"), "port": None}
        else:
            hostport = spec[6:] if low.startswith("tcp://") else spec
            host, _, port = hostport.rpartition(":")
            if not host or not port.isdigit():
                continue
            target = {"kind": "tcp", "host": host, "port": int(port)}
        if target["host"]:
            target.update(name=name, spec=spec)
            targets.append(target)
    return targets


def label(t):
    """Texto corto del destino (sin rutas ni parámetros, que pueden llevar secretos)."""
    if t["kind"] == "tcp":
        return "%s:%s" % (t["host"], t["port"])
    return t["host"] if t["kind"] == "ping" else "%s (web)" % t["host"]


def is_local(host):
    """Equipos de la red local: se vigilan siempre. El resto no se comprueba si no hay Internet."""
    try:
        n = lan.ip2int(host)
    except (socket.error, ValueError):
        return host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host
    return any(n & ((0xFFFFFFFF << (32 - b)) & 0xFFFFFFFF) == base
               for base, b in ((0x0A000000, 8), (0xAC100000, 12), (0xC0A80000, 16), (0x7F000000, 8), (0xA9FE0000, 16)))


def _ping(host):
    """ping -c 1 con plazo propio (subprocess.run(timeout=) no existe en Python 2)."""
    wait = max(1, int(WATCH_TIMEOUT))
    try:
        p = subprocess.Popen(["ping", "-c", "1", "-W", str(wait), host],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return None  # no hay comando ping
    deadline = time.time() + wait + 3
    while p.poll() is None:
        if time.time() > deadline:
            p.kill()
            p.wait()
            return False
        time.sleep(0.1)
    p.communicate()
    return p.returncode == 0


def check(t):
    """Una comprobación: (ok | None, milisegundos | None)."""
    t0 = time.time()
    try:
        if t["kind"] == "tcp":
            socket.create_connection((t["host"], t["port"]), timeout=WATCH_TIMEOUT).close()
        elif t["kind"] == "ping":
            ok = _ping(t["host"])
            if ok is None:
                return None, None
            if not ok:
                return False, None
        else:
            try:
                c.http_get(t["spec"], WATCH_TIMEOUT, 1)
            except c.HTTPError as e:
                if e.code >= 400 and e.code not in (401, 403):  # 401/403: el servicio responde
                    return False, None
    except (socket.error, ValueError, IOError):
        return False, None
    except Exception:  # noqa: BLE001 (URLError, errores TLS...)
        return False, None
    return True, (time.time() - t0) * 1000


def run_once(targets=None):
    """Comprueba todos los destinos en paralelo: [(destino, ok | None, ms)]. None = no comprobado."""
    targets = parse_targets() if targets is None else targets
    if not targets:
        return []
    online = c.is_online() if any(not is_local(t["host"]) for t in targets) else True
    todo = [t for t in targets if online or is_local(t["host"])]
    done = dict((t["name"], r) for t, r in zip(todo, c.pmap(check, todo, workers=8, timeout=WATCH_TIMEOUT + 6)))
    results = []
    for t in targets:
        ok, ms = done.get(t["name"]) or (None, None)  # sin Internet no es culpa del servicio
        results.append((t, ok, ms))
        LAST[t["name"]] = (ok, ms, time.time())
    return results


def evaluate(results, send, now=None):
    now = time.time() if now is None else now
    for t, ok, _ms in results:
        name = t["name"]
        if ok is None:
            continue
        if ok:
            _fails[name] = 0
            if name in _down:
                start = _down.pop(name)
                send("🟢 %s vuelve a responder (%s).\nCaída: %s · duración %s"
                     % (name, label(t), c.fmt_time(start), c.fmt_duration(now - start)))
            continue
        _fails[name] = _fails.get(name, 0) + 1
        if _fails[name] >= WATCH_FAILS and name not in _down:
            _down[name] = now - _fails[name] * WATCH_INTERVAL
            send("🔴 %s no responde (%s) desde %s." % (name, label(t), c.fmt_time(_down[name])))


def tick(send):
    targets = parse_targets()
    if targets:
        evaluate(run_once(targets), send)


def down_names():
    return set(_down)


def status_text():
    targets = parse_targets()
    if not targets:
        return ("👁️ No hay nada vigilado. Añade en config.env:\n"
                "WATCH_TARGETS=NAS=192.168.1.50:5000,PC=ping://192.168.1.20,Web=https://example.com")
    lines = ["👁️ Vigilancia · %s" % c.NAME]
    for t in targets:
        ok, ms, ts = LAST.get(t["name"], (None, None, None))
        if t["name"] in _down:
            lines.append("🔴 %s · %s · caído desde %s" % (t["name"], label(t), c.fmt_short(_down[t["name"]])))
        elif ok:
            lines.append("🟢 %s · %s · %.0f ms" % (t["name"], label(t), ms or 0))
        else:
            lines.append("⚪ %s · %s · %s" % (t["name"], label(t), "sin comprobar" if ts is None else "sin datos"))
    return "\n".join(lines)
