# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Funciones compartidas por el demonio (monitor.py), el bot (bot.py) y la TUI (tui.py).

Solo librería estándar (Python 3.7+).
"""
import ipaddress
import json
import logging
import os
import socket
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

CONFIG_FILE = os.environ.get("INTERNET_CHECK_CONFIG", "/etc/internet-check/config.env")      # ajustes
BOT_FILE = os.environ.get("INTERNET_CHECK_BOT_CONFIG", "/etc/internet-check/bot.env")        # credenciales del bot


def _load_env_file(path: str) -> None:
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
    except OSError:
        pass


# El demonio recibe las variables de systemd; la TUI las lee de los ficheros (bot.env requiere root).
# setdefault: lo que ya esté en el entorno tiene prioridad.
_load_env_file(BOT_FILE)
_load_env_file(CONFIG_FILE)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
HOSTS = [h.strip() for h in os.environ.get("CHECK_HOSTS", "1.1.1.1:53,8.8.8.8:53,9.9.9.9:53").split(",") if h.strip()]
TIMEOUT = float(os.environ.get("CHECK_TIMEOUT", "3"))
NAME = os.environ.get("DEVICE_NAME", socket.gethostname())
SPEEDTEST_SECONDS = float(os.environ.get("SPEEDTEST_SECONDS", "8"))  # por sentido (bajada / subida)
SPEEDTEST_STREAMS = int(os.environ.get("SPEEDTEST_STREAMS", "4"))

SPEED_SERVERS = [u.strip().rstrip("/") for u in os.environ.get(
    "SPEEDTEST_SERVERS",
    "https://fra.speedtest.clouvider.net/backend,https://lon.speedtest.clouvider.net/backend,"
    "https://ams.speedtest.clouvider.net/backend").split(",") if u.strip()]
IP_SERVICES = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]
USER_AGENT = "Mozilla/5.0 (internet-check)"

log = logging.getLogger("internet-check")

# Activo mientras se mide la velocidad: el monitor no debe contar fallos de ese rato
SPEED_BUSY = threading.Event()


# ---------- utilidades de formato ----------

def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    parts = [(d, "d"), (h, "h"), (m, "min")]
    if not (d or h):  # los segundos solo importan por debajo de la hora
        parts.append((s, "s"))
    out = " ".join(f"{v} {u}" for v, u in parts if v)
    return out or "0 s"


def fmt_ago(seconds: float) -> str:
    return fmt_duration(int(seconds) // 60 * 60) if seconds >= 60 else "unos segundos"


def fmt_short(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M:%S")


# ---------- conectividad ----------

def is_online() -> bool:
    """True si se puede abrir una conexión TCP a alguno de los hosts."""
    for item in HOSTS:
        host, _, port = item.rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=TIMEOUT):
                return True
        except OSError:
            continue
    return False


# ---------- Telegram ----------

def tg_api(method: str, params: dict = None, timeout: float = 15, quiet: bool = False):
    """Llama a la API de Telegram. Devuelve el JSON de respuesta o None si falla."""
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    req = urllib.request.Request(
        url, data=json.dumps(params or {}).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        return data if data.get("ok") else None
    except Exception as e:  # noqa: BLE001
        if not quiet:
            log.warning("Fallo en Telegram (%s): %s", method, e)
        return None


def send_telegram(text: str, reply_markup: dict = None) -> bool:
    params = {"chat_id": CHAT_ID, "text": text}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg_api("sendMessage", params) is not None


# ---------- IP pública ----------

def public_ip():
    """Devuelve la IP pública como str, o None si ningún servicio responde."""
    for url in IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as r:
                text = r.read(100).decode().strip()
            ipaddress.ip_address(text)  # valida
            return text
        except Exception:  # noqa: BLE001
            continue
    return None


def fmt_ip(ip) -> str:
    if ip:
        return f"🌍 IP pública de {NAME}:\n{ip}"
    return "❌ No se pudo obtener la IP pública."


# ---------- test de velocidad (servidores LibreSpeed) ----------
# Cada servidor es la URL base de un backend LibreSpeed: /empty.php (latencia y subida)
# y /garbage.php (bajada). Se prueban en orden hasta que uno responda.

_payload = None
_last_error = {"msg": None}  # último rechazo HTTP del servidor de pruebas


def _upload_payload() -> bytes:
    global _payload
    if _payload is None:
        _payload = os.urandom(2 << 20)
    return _payload


def _host(base: str) -> str:
    return urllib.parse.urlparse(base).hostname or base


def _dl_worker(base, add, stop):
    while time.monotonic() < stop:
        try:
            url = f"{base}/garbage.php?ckSize=100&r={time.time()}"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                        timeout=10) as r:
                while time.monotonic() < stop:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    add(len(chunk))
        except urllib.error.HTTPError as e:
            # 429 / 403...: el servidor nos limita. Reintentar empeora el bloqueo.
            _last_error["msg"] = f"HTTP {e.code} ({e.reason})"
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


def _ul_worker(base, add, stop):
    data = _upload_payload()
    while time.monotonic() < stop:
        try:
            req = urllib.request.Request(
                f"{base}/empty.php?r={time.time()}",
                data=data,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/octet-stream"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
            add(len(data))
        except urllib.error.HTTPError as e:
            _last_error["msg"] = f"HTTP {e.code} ({e.reason})"
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


def _transfer(worker, base, phase, on_progress) -> float:
    """Ejecuta `worker` en varios hilos durante SPEEDTEST_SECONDS y devuelve Mbps."""
    total = [0]
    lock = threading.Lock()

    def add(n):
        with lock:
            total[0] += n

    start = time.monotonic()
    stop = start + SPEEDTEST_SECONDS
    threads = [threading.Thread(target=worker, args=(base, add, stop), daemon=True)
               for _ in range(SPEEDTEST_STREAMS)]
    for t in threads:
        t.start()
    while time.monotonic() < stop and any(t.is_alive() for t in threads):
        time.sleep(0.25)
        if on_progress:
            el = max(time.monotonic() - start, 1e-6)
            on_progress(phase, total[0] * 8 / el / 1e6, min(el / SPEEDTEST_SECONDS, 1.0))
    for t in threads:
        t.join(timeout=10)
    el = max(time.monotonic() - start, 1e-6)
    return total[0] * 8 / el / 1e6


def speedtest(on_progress=None) -> dict:
    """Mide latencia, bajada y subida con el primer servidor que funcione.

    on_progress(fase, valor, fracción) se llama periódicamente desde el hilo que
    invoca (fase: "ping" | "down" | "up"). Lanza RuntimeError si fallan todos.
    Marca SPEED_BUSY mientras dura.
    """
    SPEED_BUSY.set()
    try:
        errors = []
        for base in SPEED_SERVERS:
            try:
                return _speedtest(base, on_progress)
            except RuntimeError as e:
                log.warning("Servidor de test %s: %s", _host(base), e)
                errors.append(str(e))
        raise RuntimeError(errors[0] if len(errors) == 1 else
                           f"fallaron los {len(errors)} servidores. Último: {errors[-1]}")
    finally:
        SPEED_BUSY.clear()


def _speedtest(base: str, on_progress=None) -> dict:
    host = _host(base)
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        try:
            with socket.create_connection((host, urllib.parse.urlparse(base).port or 443), timeout=TIMEOUT):
                times.append((time.perf_counter() - t0) * 1000)
        except OSError:
            pass
    if not times:
        raise RuntimeError(f"no se puede conectar con {host}")
    ping = statistics.median(times)
    if on_progress:
        on_progress("ping", ping, 1.0)

    _last_error["msg"] = None
    down = _transfer(_dl_worker, base, "down", on_progress)
    if down <= 0:
        raise RuntimeError(_refusal(host, "descarga"))
    up = _transfer(_ul_worker, base, "up", on_progress)
    if up <= 0:
        raise RuntimeError(_refusal(host, "subida"))
    return {"ping_ms": ping, "down_mbps": down, "up_mbps": up, "ts": time.time(), "server": host}


def _refusal(host: str, what: str) -> str:
    err = _last_error["msg"]
    if err:
        return f"{host} rechazó la {what}: {err}"
    return f"{host}: la {what} no recibió datos"


def fmt_speed(res: dict) -> str:
    return (
        f"🚀 Test de velocidad · {NAME}\n"
        f"⬇️ Bajada: {res['down_mbps']:.1f} Mbps\n"
        f"⬆️ Subida: {res['up_mbps']:.1f} Mbps\n"
        f"🏓 Latencia: {res['ping_ms']:.0f} ms\n"
        f"🌐 Servidor: {res.get('server', '?')}\n"
        f"🕒 {fmt_time(res['ts'])}"
    )
