# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Gráficas PNG dibujadas a mano con la librería estándar (sin Pillow ni matplotlib).

Un lienzo RGB en memoria, una fuente de bitmap 5x7 y un codificador PNG con zlib.
"""
import math
import struct
import time
import unicodedata
import zlib
from datetime import datetime

import common as c
import db

# ---------------------------------------------------------------- fuente 5x7
# Cada glifo son 7 filas de 5 columnas separadas por «|» («#» = píxel encendido).
_GLYPHS = {
    " ": ".....|.....|.....|.....|.....|.....|.....",
    "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    "2": ".###.|#...#|....#|...#.|..#..|.#...|#####",
    "3": "#####|...#.|..#..|...#.|....#|#...#|.###.",
    "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
    "5": "#####|#....|####.|....#|....#|#...#|.###.",
    "6": "..##.|.#...|#....|####.|#...#|#...#|.###.",
    "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
    "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
    "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
    "C": ".###.|#...#|#....|#....|#....|#...#|.###.",
    "D": "###..|#..#.|#...#|#...#|#...#|#..#.|###..",
    "E": "#####|#....|#....|####.|#....|#....|#####",
    "F": "#####|#....|#....|####.|#....|#....|#....",
    "G": ".###.|#...#|#....|#.###|#...#|#...#|.####",
    "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
    "I": ".###.|..#..|..#..|..#..|..#..|..#..|.###.",
    "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
    "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    "L": "#....|#....|#....|#....|#....|#....|#####",
    "M": "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#",
    "N": "#...#|##..#|#.#.#|#..##|#...#|#...#|#...#",
    "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    "P": "####.|#...#|#...#|####.|#....|#....|#....",
    "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
    "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    "S": ".####|#....|#....|.###.|....#|....#|####.",
    "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
    "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.",
    "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
    "W": "#...#|#...#|#...#|#.#.#|#.#.#|##.##|#...#",
    "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
    "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..",
    "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
    ".": ".....|.....|.....|.....|.....|.##..|.##..",
    ",": ".....|.....|.....|.....|.##..|..#..|.#...",
    ":": ".....|.##..|.##..|.....|.##..|.##..|.....",
    "-": ".....|.....|.....|#####|.....|.....|.....",
    "/": "....#|....#|...#.|..#..|.#...|#....|#....",
    "%": "##..#|##..#|...#.|..#..|.#...|#..##|#..##",
    "(": "...#.|..#..|.#...|.#...|.#...|..#..|...#.",
    ")": ".#...|..#..|...#.|...#.|...#.|..#..|.#...",
    "+": ".....|..#..|..#..|#####|..#..|..#..|.....",
    "_": ".....|.....|.....|.....|.....|.....|#####",
    "°": ".##..|#..#.|#..#.|.##..|.....|.....|.....",
    "?": ".###.|#...#|....#|...#.|..#..|.....|..#..",
}
FONT = {ch: [[px == "#" for px in row] for row in g.split("|")] for ch, g in _GLYPHS.items()}

PALETTE = {
    "bg": (255, 255, 255), "grid": (225, 229, 235), "axis": (70, 76, 86), "text": (40, 44, 52),
    "blue": (37, 99, 235), "orange": (245, 158, 11), "red": (220, 38, 38), "green": (22, 163, 74),
    "violet": (124, 58, 237), "gray": (156, 163, 175),
}


def _normalize(text: str) -> str:
    """Mayúsculas y sin acentos (la fuente solo tiene ASCII); la ñ pasa a N."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in nfd if not unicodedata.combining(ch)).upper()


# ---------------------------------------------------------------- lienzo y PNG

class Canvas:
    def __init__(self, width, height, bg=PALETTE["bg"]):
        self.w, self.h = width, height
        self.px = bytearray(bytes(bg) * (width * height))

    def rect(self, x0, y0, x1, y1, color):
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.w - 1, x1), min(self.h - 1, y1)
        if x1 < x0 or y1 < y0:
            return
        row = bytes(color) * (x1 - x0 + 1)
        for y in range(y0, y1 + 1):
            i = (y * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def line(self, x0, y0, x1, y1, color, thick=1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, r = dx + dy, thick // 2
        while True:
            self.rect(x0 - r, y0 - r, x0 - r + thick - 1, y0 - r + thick - 1, color)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    @staticmethod
    def text_width(text, scale=1):
        return len(text) * 6 * scale - scale if text else 0

    def text(self, x, y, text, color, scale=1):
        for ch in _normalize(text):
            glyph = FONT.get(ch, FONT["?"])
            for row, bits in enumerate(glyph):
                for col, on in enumerate(bits):
                    if on:
                        self.rect(x + col * scale, y + row * scale,
                                  x + (col + 1) * scale - 1, y + (row + 1) * scale - 1, color)
            x += 6 * scale

    def png(self) -> bytes:
        stride = self.w * 3
        raw = b"".join(b"\x00" + bytes(self.px[y * stride:(y + 1) * stride]) for y in range(self.h))

        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6))
                + chunk(b"IEND", b""))


# ---------------------------------------------------------------- dibujo de la gráfica

def nice_ticks(lo, hi, target=5):
    """Marcas 'redondas' (1, 2, 5 × 10^n) que cubren [lo, hi]."""
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v < hi + step * 0.999:
        ticks.append(round(v, 10))
        v += step
        if len(ticks) > 20:
            break
    return ticks


def downsample(points, limit, agg):
    """Reduce una serie a `limit` puntos agrupando por tramos de tiempo."""
    if len(points) <= limit:
        return points
    t0, t1 = points[0][0], points[-1][0]
    width = (t1 - t0) / limit or 1
    buckets = {}
    for t, v in points:
        buckets.setdefault(min(int((t - t0) / width), limit - 1), []).append((t, v))
    return [(sum(t for t, _ in b) / len(b), agg([v for _, v in b])) for _, b in sorted(buckets.items())]


def _fmt_tick(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:.1f}"


def draw_chart(title, series, width=760, height=400, y_min=0.0):
    """series: [{name, color, points[(ts, valor)], style: 'line'|'bars'|'dots'}]. None si no hay datos."""
    pts = [p for s in series for p in s["points"]]
    if not pts:
        return None
    t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
    if t1 <= t0:
        t1 = t0 + 60
    vmax = max(p[1] for p in pts)
    ticks = nice_ticks(y_min, max(vmax, y_min + 1) * 1.05)
    lo, hi = ticks[0], ticks[-1]

    cv = Canvas(width, height)
    left, right, top, bottom = 64, 20, 50, 46
    x0, x1, y0, y1 = left, width - right, top, height - bottom

    def X(t):
        return x0 + int((t - t0) / (t1 - t0) * (x1 - x0))

    def Y(v):
        return y1 - int((min(max(v, lo), hi) - lo) / (hi - lo) * (y1 - y0))

    for tick in ticks:  # rejilla y escala vertical
        y = Y(tick)
        cv.line(x0, y, x1, y, PALETTE["grid"])
        label = _fmt_tick(tick)
        cv.text(x0 - 8 - cv.text_width(label), y - 3, label, PALETTE["text"])
    span = t1 - t0  # escala horizontal
    fmt = "%d/%m" if span > 2 * 86400 else "%H:%M"
    for i in range(6):
        t = t0 + span * i / 5
        x = X(t)
        cv.line(x, y0, x, y1, PALETTE["grid"])
        label = datetime.fromtimestamp(t).strftime(fmt)
        cv.text(min(max(x - cv.text_width(label) // 2, 2), width - cv.text_width(label) - 2), y1 + 10,
                label, PALETTE["text"])
    cv.line(x0, y0, x0, y1, PALETTE["axis"])
    cv.line(x0, y1, x1, y1, PALETTE["axis"])

    for s in series:
        col, data, style = PALETTE[s["color"]], s["points"], s.get("style", "line")
        if style == "bars":
            for t, v in data:
                cv.rect(X(t) - 1, Y(v), X(t), y1 - 1, col)
            continue
        gaps = sorted(b[0] - a[0] for a, b in zip(data, data[1:]))
        gap_max = max(gaps[len(gaps) // 2] * 4, 120) if gaps else 120  # corta la línea si faltan datos
        prev = None
        for t, v in data:
            x, y = X(t), Y(v)
            if prev and t - prev[0] <= gap_max:
                cv.line(prev[1], prev[2], x, y, col, 2)
            if style == "dots" or len(data) == 1:
                cv.rect(x - 2, y - 2, x + 2, y + 2, col)
            prev = (t, x, y)

    cv.text(left, 14, title, PALETTE["text"], 2)  # título y leyenda
    lx = width - right
    for s in reversed(series):
        w = cv.text_width(s["name"])
        lx -= w
        cv.text(lx, 34, s["name"], PALETTE["text"])
        cv.rect(lx - 14, 34, lx - 6, 41, PALETTE[s["color"]])
        lx -= 26
    return cv.png()


# ---------------------------------------------------------------- gráficas del sistema

def _label(hours):
    return {24: "24 H", 168: "7 DIAS", 720: "30 DIAS"}.get(hours, f"{hours} H")


def _mean(values):
    return sum(values) / len(values) if values else None


def latency_chart(hours=24):
    now = time.time()
    rows = db.quality_between(now - hours * 3600, now)
    avg = [(r["ts"], r["rtt_avg"]) for r in rows if r["rtt_avg"] is not None]
    top = [(r["ts"], r["rtt_max"]) for r in rows if r["rtt_max"] is not None]
    if not avg:
        return None
    png = draw_chart(f"LATENCIA (MS) - {_label(hours)}", [
        {"name": "MAXIMA", "color": "orange", "points": downsample(top, 240, max)},
        {"name": "MEDIA", "color": "blue", "points": downsample(avg, 240, _mean)}])
    vals = [v for _, v in avg]
    return png, (f"📶 Latencia · {c.NAME}\nmedia {_mean(vals):.0f} ms · mínima {min(vals):.0f} · "
                 f"máxima {max(v for _, v in top):.0f} ms ({len(rows)} medidas)")


def loss_chart(hours=24):
    now = time.time()
    rows = db.quality_between(now - hours * 3600, now)
    loss = [(r["ts"], r["loss"]) for r in rows if r["loss"] is not None]
    if not loss:
        return None
    png = draw_chart(f"PERDIDA DE PAQUETES (%) - {_label(hours)}", [
        {"name": "PERDIDA", "color": "red", "style": "bars", "points": downsample(loss, 300, max)}])
    vals = [v for _, v in loss]
    bad = sum(1 for v in vals if v > 0)
    return png, (f"📉 Pérdida · {c.NAME}\nmedia {_mean(vals):.2f} % · máxima {max(vals):.0f} % · "
                 f"{bad} de {len(vals)} medidas con pérdidas")


def speed_chart(hours=168):
    now = time.time()
    rows = db.speedtests_between(now - hours * 3600, now)
    down = [(r["ts"], r["down"]) for r in rows if r["down"] is not None]
    up = [(r["ts"], r["up"]) for r in rows if r["up"] is not None]
    if not down:
        return None
    png = draw_chart(f"VELOCIDAD (MBPS) - {_label(hours)}", [
        {"name": "SUBIDA", "color": "green", "style": "dots", "points": up},
        {"name": "BAJADA", "color": "blue", "style": "dots", "points": down}])
    d, u = [v for _, v in down], [v for _, v in up]
    return png, (f"🚀 Velocidad · {c.NAME}\n⬇️ media {_mean(d):.1f} Mbps (mín {min(d):.1f} · máx {max(d):.1f})\n"
                 f"⬆️ media {_mean(u):.1f} Mbps (mín {min(u):.1f} · máx {max(u):.1f}) · {len(rows)} tests")


def health_chart(hours=24):
    now = time.time()
    rows = db.health_between(now - hours * 3600, now)
    temp = [(r["ts"], r["temp"]) for r in rows if r["temp"] is not None]
    mem = [(r["ts"], r["mem_pct"]) for r in rows if r["mem_pct"] is not None]
    if not (temp or mem):
        return None
    png = draw_chart(f"TEMPERATURA (C) Y MEMORIA (%) - {_label(hours)}", [
        {"name": "MEMORIA", "color": "violet", "points": downsample(mem, 240, _mean)},
        {"name": "CPU", "color": "red", "points": downsample(temp, 240, _mean)}])
    caption = f"🩺 Salud · {c.NAME}"
    if temp:
        caption += f"\nCPU media {_mean([v for _, v in temp]):.0f} °C · máx {max(v for _, v in temp):.0f} °C"
    if mem:
        caption += f"\nMemoria usada máx {max(v for _, v in mem):.0f} %"
    return png, caption


CHARTS = {  # clave del botón -> función
    "latency": latency_chart,
    "loss": loss_chart,
    "speed": speed_chart,
    "health": health_chart,
}
