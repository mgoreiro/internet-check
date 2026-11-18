#!/usr/bin/env python3
"""Crea una base de datos con 30 días de datos ficticios en /tmp/internet-check-demo
para grabar docs/demo.gif con vhs. No usa la red ni datos reales.
Uso:  python3 docs/demo-seed.py"""
import os, random, shutil, sys, time

D = "/tmp/internet-check-demo"
shutil.rmtree(D, ignore_errors=True)
os.makedirs(D)
os.environ["DB_FILE"] = f"{D}/data.db"
os.environ["STATE_FILE"] = f"{D}/state.json"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db  # noqa: E402

random.seed(7)
now = time.time()
DAY, HOUR = 86400, 3600
db.kv_set("installed_at", now - 30 * DAY)

# caídas: (hace cuántos días, minutos, tipo)
for days, mins, kind in [(26, 7, "internet"), (19, 41, "internet"), (12, 3, "reboot"),
                         (9, 95, "power"), (5, 12, "internet"), (2, 4, "internet")]:
    s = now - days * DAY
    db.outage_add_closed(s, s + mins * 60, kind)

# tests de velocidad cada 6 h
for i in range(30 * 4):
    ts = now - i * 6 * HOUR
    db.add_speedtest({"ts": ts, "down_mbps": random.gauss(480, 25), "up_mbps": random.gauss(88, 5),
                      "ping_ms": random.gauss(11, 2)}, "librespeed")

# calidad y salud cada 30 min durante 3 días
for i in range(3 * 48):
    ts = now - i * 1800
    bad = i in (20, 21)
    db.add_quality({"ts": ts, "rtt_avg": random.gauss(14 if not bad else 180, 2), "rtt_max": random.gauss(30, 5),
                    "jitter": random.gauss(1.6, 0.4), "loss": 0 if not bad else 20, "dns_ms": random.gauss(18, 3),
                    "dns_ok": True})
    db.add_health({"ts": ts, "temp": random.gauss(52 + 6 * ((i % 48) < 20), 1.5), "load": random.gauss(0.2, 0.05),
                  "mem_pct": random.gauss(34, 1.5), "disk_pct": 41, "db_kb": 2300})

# dispositivos ficticios (MAC de ejemplo)
for mac, ip, name in [("aa:bb:cc:00:00:01", "192.168.1.1", "router"), ("aa:bb:cc:00:00:02", "192.168.1.20", "nas"),
                      ("aa:bb:cc:00:00:03", "192.168.1.31", "tv-salon")]:
    db.upsert_device(mac, ip, name, now - 20 * DAY)
print("Base de datos de demostración en", D)
