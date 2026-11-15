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
CREATE TABLE IF NOT EXISTS service_outages(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, start REAL NOT NULL, end REAL);
CREATE INDEX IF NOT EXISTS idx_svc_name ON service_outages(name, start);
CREATE TABLE IF NOT EXISTS held(
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, text TEXT NOT NULL, broadcast INTEGER NOT NULL DEFAULT 0);
"""

# Columnas añadidas a `devices` después de la primera versión: se migran al abrir la base
DEVICE_COLUMNS = (
    ("alias", "TEXT"),                          # nombre puesto por el usuario
    ("watch", "INTEGER NOT NULL DEFAULT 0"),    # 1 = avisar cuando llega o se va
    ("present", "INTEGER"),                     # último estado conocido (1 en la red, 0 ausente)
    ("misses", "INTEGER NOT NULL DEFAULT 0"),   # escaneos seguidos sin verlo
)


def _connect():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    have = {r["name"] for r in con.execute("PRAGMA table_info(devices)")}
    for column, ddl in DEVICE_COLUMNS:
        if column not in have:
            con.execute(f"ALTER TABLE devices ADD COLUMN {column} {ddl}")
    con.commit()
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


# ---- nombres y presencia de dispositivos ----

def devices_all():
    return _query("SELECT * FROM devices ORDER BY COALESCE(alias, hostname, mac)")


def aliases():
    """{mac: nombre} de los dispositivos a los que el usuario ha puesto nombre."""
    return {r["mac"]: r["alias"] for r in _query("SELECT mac, alias FROM devices WHERE alias IS NOT NULL")}


def device_find(query):
    """Dispositivos que coinciden con una MAC, IP o nombre (exactos primero, luego parciales)."""
    q = (query or "").strip().lower().replace("-", ":")
    if not q:
        return []
    rows = devices_all()
    exact = [r for r in rows if q in (r["mac"].lower(), (r["ip"] or "").lower(), (r["alias"] or "").lower())]
    if exact:
        return exact
    return [r for r in rows if any(q in (r[k] or "").lower() for k in ("alias", "hostname", "mac", "ip"))]


def set_alias(mac, alias):
    _exec("UPDATE devices SET alias=? WHERE mac=?", (alias or None, mac))


def toggle_watch(mac) -> bool:
    """Activa o desactiva el aviso de llegada/salida y devuelve el nuevo estado."""
    _exec("UPDATE devices SET watch = 1 - watch WHERE mac=?", (mac,))
    return bool(_query("SELECT watch FROM devices WHERE mac=?", (mac,))[0]["watch"])


def presence_update(seen, misses_limit, now=None):
    """Actualiza quién está en la red. `seen` = MAC vistas en este escaneo.

    Un dispositivo se da por ausente tras `misses_limit` escaneos seguidos sin verlo. Devuelve los
    cambios de estado de los dispositivos vigilados: [(fila, 'arrived' | 'left')]."""
    events = []
    with closing(_connect()) as con, con:
        for r in con.execute("SELECT * FROM devices").fetchall():
            if r["mac"] in seen:
                if r["present"] == 0 and r["watch"]:
                    events.append((dict(r), "arrived"))
                con.execute("UPDATE devices SET present=1, misses=0 WHERE mac=?", (r["mac"],))
                continue
            misses = r["misses"] + 1
            if r["present"] != 0 and misses >= misses_limit:
                if r["watch"]:
                    events.append((dict(r), "left"))
                con.execute("UPDATE devices SET present=0, misses=? WHERE mac=?", (misses, r["mac"]))
            else:
                con.execute("UPDATE devices SET misses=? WHERE mac=?", (misses, r["mac"]))
    return events


# ---- servicios vigilados ----

def svc_open(name, start):
    """Abre una caída del servicio; idempotente si ya hay una abierta."""
    if _query("SELECT 1 FROM service_outages WHERE name=? AND end IS NULL", (name,)):
        return
    _exec("INSERT INTO service_outages(name,start,end) VALUES(?,?,NULL)", (name, start))


def svc_close(name, end) -> float:
    """Cierra la caída abierta y devuelve su inicio (None si no había)."""
    rows = _query("SELECT start FROM service_outages WHERE name=? AND end IS NULL", (name,))
    _exec("UPDATE service_outages SET end=? WHERE name=? AND end IS NULL", (end, name))
    return rows[0]["start"] if rows else None


def svc_open_names():
    return {r["name"] for r in _query("SELECT name FROM service_outages WHERE end IS NULL")}


def svc_outages(name, t0, t1):
    return _query("SELECT * FROM service_outages WHERE name=? AND COALESCE(end,?) > ? AND start < ? ORDER BY start",
                  (name, t1, t0, t1))


def svc_downtime(name, t0, t1) -> float:
    return sum(max(0.0, min(r["end"] or t1, t1) - max(r["start"], t0)) for r in svc_outages(name, t0, t1))


# ---- avisos retenidos por el modo no molestar ----

def held_add(text, broadcast=False, ts=None):
    _exec("INSERT INTO held(ts,text,broadcast) VALUES(?,?,?)", (ts or time.time(), text, int(broadcast)))


def held_all():
    return _query("SELECT * FROM held ORDER BY ts")


def held_clear():
    _exec("DELETE FROM held")
