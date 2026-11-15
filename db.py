# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Almacenamiento SQLite (caídas, tests de velocidad, dispositivos, pares clave/valor).

Se abre una conexión por operación: es seguro entre hilos y entre procesos
(el servicio y la TUI). Solo librería estándar.
"""
import os
import sqlite3
import time
from contextlib import closing

DB_FILE = os.environ.get("DB_FILE", "/var/lib/internet-check/data.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS outages(
    id INTEGER PRIMARY KEY, start REAL NOT NULL, end REAL, kind TEXT NOT NULL DEFAULT 'internet');
CREATE TABLE IF NOT EXISTS speedtests(
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, down REAL, up REAL, ping REAL, source TEXT);
CREATE TABLE IF NOT EXISTS devices(
    mac TEXT PRIMARY KEY, ip TEXT, hostname TEXT, first_seen REAL, last_seen REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""


def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _exec(sql, args=()):
    """Ejecuta una escritura y devuelve el nº de filas afectadas."""
    with closing(_connect()) as con, con:
        return con.execute(sql, args).rowcount


def _query(sql, args=()):
    with closing(_connect()) as con:
        return con.execute(sql, args).fetchall()


# ---- clave/valor ----

def kv_get(key, default=None):
    rows = _query("SELECT value FROM kv WHERE key=?", (key,))
    return rows[0]["value"] if rows else default


def kv_set(key, value):
    _exec("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, str(value)))


def kv_del(key):
    _exec("DELETE FROM kv WHERE key=?", (key,))


def ensure_installed_at() -> float:
    """Momento en que empezó la monitorización (se fija la primera vez)."""
    v = kv_get("installed_at")
    if v is None:
        v = time.time()
        kv_set("installed_at", v)
    return float(v)


# ---- caídas ----

def outage_open(start, kind="internet"):
    """Abre una caída; idempotente si ya hay una abierta."""
    if _query("SELECT 1 FROM outages WHERE end IS NULL AND kind=?", (kind,)):
        return
    _exec("INSERT INTO outages(start,end,kind) VALUES(?,NULL,?)", (start, kind))


def outage_close(end, kind="internet") -> int:
    return _exec("UPDATE outages SET end=? WHERE end IS NULL AND kind=?", (end, kind))


def outage_add_closed(start, end, kind="internet"):
    _exec("INSERT INTO outages(start,end,kind) VALUES(?,?,?)", (start, end, kind))


def outages_recent(limit=10):
    return _query("SELECT * FROM outages ORDER BY start DESC LIMIT ?", (limit,))


def downtime_between(t0, t1) -> float:
    total = 0.0
    for r in _query("SELECT start,end FROM outages WHERE COALESCE(end,?) > ? AND start < ?", (t1, t0, t1)):
        total += max(0.0, min(r["end"] or t1, t1) - max(r["start"], t0))
    return total


# ---- tests de velocidad ----

def add_speedtest(res, source):
    _exec("INSERT INTO speedtests(ts,down,up,ping,source) VALUES(?,?,?,?,?)",
          (res["ts"], res["down_mbps"], res["up_mbps"], res["ping_ms"], source))


def speedtests_recent(limit=24):
    return _query("SELECT * FROM speedtests ORDER BY ts DESC LIMIT ?", (limit,))


def last_speedtest():
    rows = speedtests_recent(1)
    return rows[0] if rows else None


# ---- dispositivos de la LAN ----

def upsert_device(mac, ip, hostname, now=None) -> bool:
    """Guarda/actualiza un dispositivo. Devuelve True si es nuevo."""
    now = now or time.time()
    with closing(_connect()) as con, con:
        known = con.execute("SELECT 1 FROM devices WHERE mac=?", (mac,)).fetchone()
        if known:
            con.execute("UPDATE devices SET ip=?, hostname=COALESCE(?,hostname), last_seen=? WHERE mac=?",
                        (ip, hostname, now, mac))
            return False
        con.execute("INSERT INTO devices(mac,ip,hostname,first_seen,last_seen) VALUES(?,?,?,?,?)",
                    (mac, ip, hostname, now, now))
        return True
