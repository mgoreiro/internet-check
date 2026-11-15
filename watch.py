# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro
"""Vigilancia de equipos y servicios propios (NAS, router, una web...).

Se configura con WATCH_TARGETS="Nombre=destino,Otro=destino". Un destino puede ser:
  host:puerto      conexión TCP                    NAS=192.168.1.50:5000
  tcp://host:puerto igual que el anterior
  ping://host      ping con el comando del sistema   Router=ping://192.168.1.1
  http(s)://...    petición GET; falla con error de red o código >= 400 (salvo 401 y 403)
Avisa tras WATCH_FAILS fallos seguidos y de nuevo al recuperarse, con la duración de la caída.
"""
import concurrent.futures as cf
import ipaddress
import logging
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

import common as c
import db

log = logging.getLogger("internet-check.watch")

WATCH_TARGETS = os.environ.get("WATCH_TARGETS", "")
WATCH_INTERVAL = float(os.environ.get("WATCH_INTERVAL", "60"))   # segundos entre comprobaciones
WATCH_FAILS = int(os.environ.get("WATCH_FAILS", "3"))            # fallos seguidos para avisar
WATCH_TIMEOUT = float(os.environ.get("WATCH_TIMEOUT", "4"))

LAST = {}        # nombre -> (ok | None, ms | None, hora) de la última comprobación
_fails = {}      # nombre -> fallos seguidos
_warned = set()  # avisos de configuración ya registrados


def parse_targets(text=None):
    """'A=host:80,B=ping://h' -> [{name, kind, spec, host, port}]. Las entradas mal escritas se ignoran."""
    targets = []
    for item in (WATCH_TARGETS if text is None else text).split(","):
        name, _, spec = item.partition("=")
        name, spec = name.strip(), spec.strip()
        if not name or not spec:
            continue
        low = spec.lower()
        if low.startswith(("http://", "https://")):
            host = urllib.parse.urlparse(spec).hostname
            target = {"kind": "http", "host": host, "port": None}
        elif low.startswith("ping://"):
            target = {"kind": "ping", "host": spec[7:].strip("/"), "port": None}
        else:
            hostport = spec[6:] if low.startswith("tcp://") else spec
            host, _, port = hostport.rpartition(":")
            if not host or not port.isdigit():
                continue
            target = {"kind": "tcp", "host": host, "port": int(port)}
        if target["host"]:
            targets.append(dict(target, name=name, spec=spec))
    return targets


def label(t) -> str:
    """Texto corto del destino para los mensajes (sin rutas ni parámetros, que pueden llevar secretos)."""
    if t["kind"] == "tcp":
        return f"{t['host']}:{t['port']}"
    return t["host"] if t["kind"] == "ping" else f"{t['host']} (web)"


def is_local(host) -> bool:
    """Equipos de la red local: se vigilan siempre. El resto no se comprueba si no hay Internet."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host


def check(t):
    """Una comprobación: (ok, milisegundos | None)."""
    t0 = time.perf_counter()
    try:
        if t["kind"] == "tcp":
            socket.create_connection((t["host"], t["port"]), timeout=WATCH_TIMEOUT).close()
        elif t["kind"] == "ping":
            if not shutil.which("ping"):
                if "ping" not in _warned:
                    _warned.add("ping")
                    log.warning("No hay comando 'ping' en el sistema: se ignoran los destinos ping://")
                return None, None
            done = subprocess.run(["ping", "-c", "1", "-W", str(max(1, int(WATCH_TIMEOUT))), t["host"]],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=WATCH_TIMEOUT + 3)
            if done.returncode != 0:
                return False, None
        else:
            req = urllib.request.Request(t["spec"], headers={"User-Agent": "internet-check"})
            try:
                with urllib.request.urlopen(req, timeout=WATCH_TIMEOUT) as r:
                    r.read(1)
            except urllib.error.HTTPError as e:
                if e.code >= 400 and e.code not in (401, 403):  # 401/403: el servicio responde
                    return False, None
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, None
    return True, (time.perf_counter() - t0) * 1000


def run_once(targets=None):
    """Comprueba todos los destinos en paralelo: [(destino, ok | None, ms)]. None = no comprobado."""
    targets = parse_targets() if targets is None else targets
    if not targets:
        return []
    online = c.is_online() if any(not is_local(t["host"]) for t in targets) else True
    with cf.ThreadPoolExecutor(min(8, len(targets))) as ex:
        futures = {t["name"]: ex.submit(check, t) for t in targets if online or is_local(t["host"])}
    results = []
    for t in targets:
        if t["name"] in futures:
            ok, ms = futures[t["name"]].result()
        else:
            ok, ms = None, None  # destino de Internet con Internet caído: no es culpa del servicio
        results.append((t, ok, ms))
        LAST[t["name"]] = (ok, ms, time.time())
    return results


def evaluate(results, send, now=None):
    """Lleva la cuenta de fallos y avisa de caídas y recuperaciones con `send(texto)`."""
    now = time.time() if now is None else now
    down = db.svc_open_names()
    for t, ok, _ms in results:
        name = t["name"]
        if ok is None:
            continue
        if ok:
            _fails[name] = 0
            if name in down:
                start = db.svc_close(name, now)
                send(f"🟢 {name} vuelve a responder ({label(t)}).\n"
                     f"Caída: {c.fmt_time(start)} · duración {c.fmt_duration(now - start)}")
            continue
        _fails[name] = _fails.get(name, 0) + 1
        if _fails[name] >= WATCH_FAILS and name not in down:
            start = now - _fails[name] * WATCH_INTERVAL
            db.svc_open(name, start)
            send(f"🔴 {name} no responde ({label(t)}) desde {c.fmt_time(start)}.")


def tick(send):
    targets = parse_targets()
    if targets:
        evaluate(run_once(targets), send)
