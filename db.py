# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
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
CREATE TABLE IF NOT EXISTS quality(
    ts REAL NOT NULL, rtt_avg REAL, rtt_max REAL, jitter REAL, loss REAL, dns_ms REAL, dns_ok INTEGER);
CREATE INDEX IF NOT EXISTS idx_quality_ts ON quality(ts);
CREATE TABLE IF NOT EXISTS health(
    ts REAL NOT NULL, temp REAL, load REAL, mem_pct REAL, disk_pct REAL, db_kb REAL);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health(ts);
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


# ---- calidad de la conexión y salud del equipo ----

def add_quality(q):
    _exec("INSERT INTO quality(ts,rtt_avg,rtt_max,jitter,loss,dns_ms,dns_ok) VALUES(?,?,?,?,?,?,?)",
          (q["ts"], q.get("rtt_avg"), q.get("rtt_max"), q.get("jitter"), q.get("loss"),
           q.get("dns_ms"), None if q.get("dns_ok") is None else int(q["dns_ok"])))


def quality_between(t0, t1):
    return _query("SELECT * FROM quality WHERE ts >= ? AND ts <= ? ORDER BY ts", (t0, t1))


def add_health(h):
    _exec("INSERT INTO health(ts,temp,load,mem_pct,disk_pct,db_kb) VALUES(?,?,?,?,?,?)",
          (h["ts"], h.get("temp"), h.get("load"), h.get("mem_pct"), h.get("disk_pct"), h.get("db_kb")))


def health_between(t0, t1):
    return _query("SELECT * FROM health WHERE ts >= ? AND ts <= ? ORDER BY ts", (t0, t1))


def prune(before):
    """Borra medidas antiguas (calidad y salud). Caídas y tests de velocidad se conservan."""
    return _exec("DELETE FROM quality WHERE ts < ?", (before,)) + _exec("DELETE FROM health WHERE ts < ?", (before,))


# ---- consultas por periodo (informes) ----

def outages_between(t0, t1):
    return _query("SELECT * FROM outages WHERE COALESCE(end,?) > ? AND start < ? ORDER BY start", (t1, t0, t1))


def speedtests_between(t0, t1):
    return _query("SELECT * FROM speedtests WHERE ts >= ? AND ts <= ? ORDER BY ts", (t0, t1))


def devices_first_seen_between(t0, t1):
    return _query("SELECT * FROM devices WHERE first_seen >= ? AND first_seen <= ? ORDER BY first_seen", (t0, t1))
