# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Funciones compartidas. Versión para OpenWrt (Python 3).

Sin base de datos ni ficheros de estado: todo vive en memoria y se pierde al reiniciar el servicio.
"""
from __future__ import division, print_function, unicode_literals

import contextlib
import io
import json
import logging
import os
import re
import socket
import threading
import time
from datetime import datetime

try:  # Python 2
    import Queue as _queue
    import urllib2 as _u
    from urlparse import urlparse
    HTTPError = _u.HTTPError
    urlopen, Request = _u.urlopen, _u.Request
except ImportError:  # Python 3 (solo para pruebas en otro equipo)
    import queue as _queue
    import urllib.request as _u
    from urllib.error import HTTPError
    from urllib.parse import urlparse
    urlopen, Request = _u.urlopen, _u.Request

CONFIG_DIR = os.environ.get("INTERNET_CHECK_DIR", "/etc/internet-check")
BOT_FILE = os.path.join(CONFIG_DIR, "bot.env")        # credenciales del bot
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.env")  # ajustes

_FILE_CONF = {}


def _text(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


text_of = _text


def _load_env_file(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                _FILE_CONF.setdefault(k.strip(), v.strip().strip("\"'"))
    except (IOError, OSError):
        pass


def env(name, default=""):
    """Ajuste: variable de entorno, si no el valor de los .env y si no el valor por defecto."""
    value = os.environ.get(name)
    if value is None:
        value = _FILE_CONF.get(name)
    return default if value is None else _text(value)


_load_env_file(BOT_FILE)
_load_env_file(CONFIG_FILE)

TOKEN = env("TELEGRAM_TOKEN")
CHAT_ID = env("TELEGRAM_CHAT_ID")
HOSTS = [h.strip() for h in env("CHECK_HOSTS", "1.1.1.1:53,8.8.8.8:53,9.9.9.9:53").split(",") if h.strip()]
TIMEOUT = float(env("CHECK_TIMEOUT", "3"))
NAME = env("DEVICE_NAME") or _text(socket.gethostname())
SPEEDTEST_SECONDS = float(env("SPEEDTEST_SECONDS", "8"))
SPEEDTEST_STREAMS = int(env("SPEEDTEST_STREAMS", "2"))   # el ER-X tiene poca CPU para TLS

SPEED_SERVERS = [u.strip().rstrip("/") for u in env(
    "SPEEDTEST_SERVERS",
    "https://fra.speedtest.clouvider.net/backend,https://lon.speedtest.clouvider.net/backend,"
    "https://ams.speedtest.clouvider.net/backend").split(",") if u.strip()]
IP_SERVICES = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]
USER_AGENT = "Mozilla/5.0 (internet-check)"

log = logging.getLogger("internet-check")

# Activo mientras se mide la velocidad: el monitor no cuenta los fallos de ese rato
SPEED_BUSY = threading.Event()
mono = getattr(time, "monotonic", time.time)


# ---------- utilidades de formato ----------

def fmt_duration(seconds):
    s = int(seconds)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = [(d, "d"), (h, "h"), (m, "min")]
    if not (d or h):
        parts.append((s, "s"))
    out = " ".join("%d %s" % (v, u) for v, u in parts if v)
    return out or "0 s"


def fmt_ago(seconds):
    return fmt_duration(int(seconds) // 60 * 60) if seconds >= 60 else "unos segundos"


def fmt_short(ts):
    return datetime.fromtimestamp(ts).strftime(str("%d/%m %H:%M"))


def fmt_time(ts):
    return datetime.fromtimestamp(ts).strftime(str("%d/%m/%Y %H:%M:%S"))


def mean(values):
    return sum(values) / len(values) if values else None


def median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def pstdev(values):
    m = mean(values)
    return (sum((v - m) ** 2 for v in values) / len(values)) ** 0.5 if values else 0.0


def pmap(fn, items, workers=16, timeout=None):
    """fn(item) en varios hilos; devuelve la lista de resultados (None si falló o no llegó a tiempo).
    Sustituye a concurrent.futures, que no existe en Python 2."""
    items = list(items)
    results = [None] * len(items)
    todo = _queue.Queue()
    for i, item in enumerate(items):
        todo.put((i, item))

    def work():
        while True:
            try:
                i, item = todo.get_nowait()
            except _queue.Empty:
                return
            try:
                results[i] = fn(item)
            except Exception:  # noqa: BLE001
                pass

    threads = [threading.Thread(target=work) for _ in range(min(workers, len(items)))]
    deadline = None if timeout is None else mono() + timeout
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(None if deadline is None else max(deadline - mono(), 0.01))
    return results


def uptime():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (IOError, OSError, ValueError):
        return None


# ---------- HTTP ----------

def make_request(url, data=None, headers=None):
    """Request con URL y cabeceras como `str` nativo. En Python 2, si alguna fuera `unicode`, httplib
    convierte toda la petición a unicode y falla al añadir un cuerpo binario (la subida del test)."""
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    return Request(str(url), data=data, headers=dict((str(k), str(v)) for k, v in h.items()))


def http_get(url, timeout=10, nbytes=None, data=None, headers=None):
    """GET (o POST si hay `data`) y devuelve el cuerpo en bytes."""
    with contextlib.closing(urlopen(make_request(url, data, headers), timeout=timeout)) as r:
        return r.read(nbytes) if nbytes else r.read()


# ---------- conectividad ----------

def is_online():
    """True si se puede abrir una conexión TCP a alguno de los hosts."""
    for item in HOSTS:
        host, _, port = item.rpartition(":")
        try:
            socket.create_connection((host, int(port)), timeout=TIMEOUT).close()
            return True
        except (socket.error, ValueError):
            continue
    return False


# ---------- Telegram ----------

def tg_api(method, params=None, timeout=15, quiet=False):
    """Llama a la API de Telegram. Devuelve el JSON de respuesta o None si falla."""
    url = "https://api.telegram.org/bot%s/%s" % (TOKEN, method)
    try:
        body = http_get(url, timeout, data=json.dumps(params or {}).encode("utf-8"),
                        headers={"Content-Type": "application/json"})
        data = json.loads(body.decode("utf-8"))
        return data if data.get("ok") else None
    except Exception as e:  # noqa: BLE001
        if not quiet:
            log.warning("Fallo en Telegram (%s): %s", method, type(e).__name__)  # sin el token de la URL
        return None


def _id_list(name):
    return [x.strip() for x in env(name).split(",") if x.strip()]


ADMINS = ([CHAT_ID] if CHAT_ID else []) + [x for x in _id_list("TELEGRAM_ADMINS") if x != CHAT_ID]
VIEWERS = [x for x in _id_list("TELEGRAM_VIEWERS") if x not in ADMINS]
NOTIFY_VIEWERS = env("TELEGRAM_NOTIFY_VIEWERS", "0") == "1"

_ctx = threading.local()  # chat y rol de la petición que se atiende (por hilo)


def role_of(chat):
    chat = "%s" % chat
    return "admin" if chat in ADMINS else "viewer" if chat in VIEWERS else None


def set_context(chat, role):
    _ctx.chat, _ctx.role = "%s" % chat, role


def clear_context():
    _ctx.chat = _ctx.role = None


def current_role():
    return getattr(_ctx, "role", None) or "admin"


def _targets(to=None, broadcast=False):
    if to:
        return ["%s" % to]
    chat = getattr(_ctx, "chat", None)
    if chat:
        return [chat]
    if broadcast and NOTIFY_VIEWERS:
        return ADMINS + VIEWERS
    return [CHAT_ID]


def send_telegram(text, reply_markup=None, to=None, broadcast=False):
    """Envía un mensaje al chat de la petición en curso o, en las tareas del servicio, al administrador."""
    first = None
    for chat in _targets(to, broadcast):
        params = {"chat_id": chat, "text": text}
        if reply_markup:
            params["reply_markup"] = reply_markup
        ok = tg_api("sendMessage", params) is not None
        first = ok if first is None else first
    return bool(first)


# ---------- IP pública ----------

_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def public_ip():
    for url in IP_SERVICES:
        try:
            text = http_get(url, 8, 100).decode("ascii", "replace").strip()
        except Exception:  # noqa: BLE001
            continue
        if _IPV4.match(text):
            return text
    return None


def fmt_ip(ip):
    return "🌍 IP pública de %s:\n%s" % (NAME, ip) if ip else "❌ No se pudo obtener la IP pública."


# ---------- test de velocidad (servidores LibreSpeed) ----------

_payload = [None]
_last_error = {"msg": None}


def _upload_payload():
    if _payload[0] is None:
        _payload[0] = os.urandom(1 << 20)
    return _payload[0]


def _host(base):
    return urlparse(base).hostname or base


def _dl_worker(base, add, stop):
    while mono() < stop:
        try:
            url = "%s/garbage.php?ckSize=100&r=%s" % (base, time.time())
            with contextlib.closing(urlopen(make_request(url), timeout=10)) as r:
                while mono() < stop:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    add(len(chunk))
        except HTTPError as e:
            _last_error["msg"] = "HTTP %s (%s)" % (e.code, e.reason)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


def _ul_worker(base, add, stop):
    data = _upload_payload()
    while mono() < stop:
        try:
            http_get("%s/empty.php?r=%s" % (base, time.time()), 15, data=data,
                     headers={"Content-Type": "application/octet-stream"})
            add(len(data))
        except HTTPError as e:
            _last_error["msg"] = "HTTP %s (%s)" % (e.code, e.reason)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


def _transfer(worker, base):
    """Ejecuta `worker` en varios hilos durante SPEEDTEST_SECONDS y devuelve Mbps."""
    total = [0]
    lock = threading.Lock()

    def add(n):
        with lock:
            total[0] += n

    start = mono()
    stop = start + SPEEDTEST_SECONDS
    threads = [threading.Thread(target=worker, args=(base, add, stop)) for _ in range(SPEEDTEST_STREAMS)]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(SPEEDTEST_SECONDS + 12)
    return total[0] * 8 / max(mono() - start, 1e-6) / 1e6


def _refusal(host, what):
    err = _last_error["msg"]
    return "%s rechazó la %s: %s" % (host, what, err) if err else "%s: la %s no recibió datos" % (host, what)


def _speedtest(base):
    host = _host(base)
    port = urlparse(base).port or 443
    times = []
    for _ in range(5):
        t0 = time.time()
        try:
            socket.create_connection((host, port), timeout=TIMEOUT).close()
            times.append((time.time() - t0) * 1000)
        except socket.error:
            pass
    if not times:
        raise RuntimeError("no se puede conectar con %s" % host)
    _last_error["msg"] = None
    down = _transfer(_dl_worker, base)
    if down <= 0:
        raise RuntimeError(_refusal(host, "descarga"))
    up = _transfer(_ul_worker, base)
    if up <= 0:
        raise RuntimeError(_refusal(host, "subida"))
    return {"ping_ms": median(times), "down_mbps": down, "up_mbps": up, "ts": time.time(), "server": host}


def speedtest():
    """Mide latencia, bajada y subida con el primer servidor que funcione (RuntimeError si fallan todos)."""
    SPEED_BUSY.set()
    try:
        errors = []
        for base in SPEED_SERVERS:
            try:
                return _speedtest(base)
            except RuntimeError as e:
                log.warning("Servidor de test %s: %s", _host(base), e)
                errors.append("%s" % e)
        raise RuntimeError(errors[0] if len(errors) == 1 else
                           "fallaron los %d servidores. Último: %s" % (len(errors), errors[-1]))
    finally:
        SPEED_BUSY.clear()


def fmt_speed(res):
    return ("🚀 Test de velocidad · %s\n⬇️ Bajada: %.1f Mbps\n⬆️ Subida: %.1f Mbps\n"
            "🏓 Latencia: %.0f ms\n🌐 Servidor: %s\n🕒 %s"
            % (NAME, res["down_mbps"], res["up_mbps"], res["ping_ms"], res.get("server", "?"), fmt_time(res["ts"])))
