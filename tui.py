#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""TUI estilo Turbo Vision (curses): escritorio, barra de menú, ventanas con sombra y diálogos.

Estado, test de velocidad, IP pública, historiales y dispositivos de la red.
El test de velocidad y la IP se envían además al bot de Telegram.
"""
import curses
import locale
import os
import re
import sys
import textwrap

import common as c
import export
import info
import reports
import updates

# ---------------------------------------------------------------- datos

LIST_ITEMS = [
    ("Estado", "F2", "status"),
    ("Test de velocidad", "F3", "speed"),
    ("IP pública", "F4", "ip"),
    ("Historial de caídas", "F5", "outages"),
    ("Histórico de velocidad", "F6", "speeds"),
    ("Dispositivos de la red", "F7", "devices"),
    ("Calidad de la conexión", "F8", "quality"),
    ("Salud de la Pi", "F9", "health"),
    ("Ayuda", "F1", "help"),
    ("Salir", "q", "quit"),
]
# (título de la barra, [(etiqueta con ~tecla~, atajo, acción)])
MENUS = [
    ("≡", [("~A~cerca de...", "", "about"), ("~S~alir", "q", "quit")]),
    ("Monitor", [("~E~stado", "F2", "status"), ("~I~P pública", "F4", "ip"),
                 ("~H~istorial de caídas", "F5", "outages"), ("~C~alidad de la conexión", "F8", "quality"),
                 ("~S~alud de la Pi", "F9", "health")]),
    ("Velocidad", [("~T~est de velocidad", "F3", "speed"), ("~H~istórico", "F6", "speeds")]),
    ("Red", [("~D~ispositivos", "F7", "devices"), ("~P~resencia", "", "presence"),
             ("~S~ervicios vigilados", "", "watch")]),
    ("Informes", [("~D~iario (24 h)", "", "report24"), ("~S~emanal (7 días)", "", "report168"),
                  ("~M~ensual (30 días)", "", "report720"),
                  ("~E~xportar CSV (30 días)", "", "export30"), ("Exportar CSV (~t~odo)", "", "export0")]),
    ("Ayuda", [("~C~ontenido", "F1", "help"), ("~T~eclas y atajos", "", "keys"),
               ("~B~uscar actualización", "", "update"), ("~A~cerca de...", "", "about")]),
]
FKEYS = {
    curses.KEY_F1: "help", curses.KEY_F2: "status", curses.KEY_F3: "speed", curses.KEY_F4: "ip",
    curses.KEY_F5: "outages", curses.KEY_F6: "speeds", curses.KEY_F7: "devices",
    curses.KEY_F8: "quality", curses.KEY_F9: "health",
}
REPORTS = {
    "status": ("Estado", reports.status_text),
    "outages": ("Historial de caídas", reports.history_text),
    "speeds": ("Histórico de velocidad", reports.speed_history_text),
    "devices": ("Dispositivos de la red", reports.devices_text),
    "help": ("Ayuda", info.tui_help),
    "keys": ("Teclas y atajos", info.tui_keys),
    "watch": ("Servicios vigilados", reports.watch_text),
    "presence": ("Presencia", reports.presence_text),
    "quality": ("Calidad de la conexión", reports.quality_text),
    "health": ("Salud de la Pi", reports.health_text),
    "report24": ("Informe diario", lambda: reports.period_report_text(24)),
    "report168": ("Informe semanal", lambda: reports.period_report_text(168)),
    "report720": ("Informe mensual", lambda: reports.period_report_text(720)),
}
DEFAULT_STATUS = "~F1~ Ayuda ~F2~ Estado ~F3~ Test ~F4~ IP ~F5~ Caídas ~F7~ Red ~F8~ Calidad ~F9~ Salud ~F10~ Menú"

# Emojis: ocupan ancho doble y descuadran curses
EMOJI = re.compile("[\U00010000-\U0010ffff☀-➿⬀-⯿️‍]")

UTF = {
    "desk": "░", "dbl": "╔╗╚╝═║", "sgl": "┌┐└┘─│", "closer": "[■]",
    "bar_on": "█", "bar_off": "░", "track": "▒", "thumb": "■",
    "bshadow_r": "▄", "bshadow_b": "▀", "arrow": "►",
}
ASCII = {
    "desk": ".", "dbl": "++++=|", "sgl": "++++-|", "closer": "[*]",
    "bar_on": "#", "bar_off": ".", "track": ":", "thumb": "#",
    "bshadow_r": "_", "bshadow_b": "-", "arrow": ">",
}

scr = None
A = {}
G = UTF
STATE = {"sel": 0}


def clean(text):
    return EMOJI.sub("", text).replace("•", "-").replace("≡", "=") if G is ASCII else \
        EMOJI.sub("", text).replace("•", "-")


# ---------------------------------------------------------------- primitivas

def init_colors():
    curses.start_color()
    C = curses
    defs = {
        # nombre: (texto, fondo, extra)
        "desk": (C.COLOR_CYAN, C.COLOR_BLUE, 0),
        "win": (C.COLOR_WHITE, C.COLOR_BLUE, C.A_BOLD),
        "win_hi": (C.COLOR_YELLOW, C.COLOR_BLUE, C.A_BOLD),
        "win_dim": (C.COLOR_CYAN, C.COLOR_BLUE, 0),
        "closer": (C.COLOR_GREEN, C.COLOR_BLUE, C.A_BOLD),
        "scroll": (C.COLOR_CYAN, C.COLOR_BLUE, 0),
        "gray": (C.COLOR_BLACK, C.COLOR_WHITE, 0),
        "gray_hot": (C.COLOR_RED, C.COLOR_WHITE, 0),
        "gray_border": (C.COLOR_WHITE, C.COLOR_WHITE, C.A_BOLD),
        "sel": (C.COLOR_BLACK, C.COLOR_GREEN, 0),
        "sel_hot": (C.COLOR_RED, C.COLOR_GREEN, 0),
        "list_sel": (C.COLOR_BLACK, C.COLOR_CYAN, 0),
        "shadow": (C.COLOR_BLACK, C.COLOR_BLACK, 0),
        "btn": (C.COLOR_BLACK, C.COLOR_GREEN, 0),
        "btn_shadow": (C.COLOR_BLACK, C.COLOR_WHITE, 0),
        "error": (C.COLOR_RED, C.COLOR_WHITE, C.A_BOLD),
    }
    for i, (name, (fg, bg, extra)) in enumerate(defs.items(), start=1):
        curses.init_pair(i, fg, bg)
        A[name] = curses.color_pair(i) | extra
    A["win_border"] = A["win"]


def put(y, x, text, attr=0):
    h, w = scr.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    if x < 0:
        text, x = text[-x:], 0
    try:
        scr.addstr(y, x, text[: w - x], attr)
    except curses.error:  # esquina inferior derecha / pantalla pequeña
        pass


def strip_tilde(s):
    return s.replace("~", "")


def put_tilde(y, x, text, attr, hot):
    """Dibuja texto con ~tecla~ resaltada (como las etiquetas de Turbo Vision)."""
    for i, part in enumerate(text.split("~")):
        put(y, x, part, hot if i % 2 else attr)
        x += len(part)


def frame(y, x, h, w, glyphs, attr):
    tl, tr, bl, br, hz, vt = glyphs
    put(y, x, tl + hz * (w - 2) + tr, attr)
    for r in range(1, h - 1):
        put(y + r, x, vt, attr)
        put(y + r, x + w - 1, vt, attr)
    put(y + h - 1, x, bl + hz * (w - 2) + br, attr)


def box(y, x, h, w, title="", kind="blue", closer=True):
    """Ventana con sombra. kind: blue (ventana), gray (diálogo), menu (desplegable)."""
    for r in range(1, h + 1):
        put(y + r, x + w, "  ", A["shadow"])
    put(y + h, x + 2, " " * (w - 2), A["shadow"])
    body = A["win"] if kind == "blue" else A["gray"]
    border = A["win"] if kind == "blue" else A["gray_border"]
    for r in range(h):
        put(y + r, x, " " * w, body)
    frame(y, x, h, w, G["sgl"] if kind == "menu" else G["dbl"], border)
    if kind == "blue" and closer:
        put(y, x + 2, G["closer"], A["closer"])
    if title:
        t = f" {title} "
        put(y, x + (w - len(t)) // 2, t, A["win_hi"] if kind == "blue" else A["gray"] | curses.A_BOLD)


# ---------------------------------------------------------------- elementos fijos

def desktop():
    h, w = scr.getmaxyx()
    for r in range(1, h - 1):
        put(r, 0, G["desk"] * w, A["desk"])


def menubar(active=None):
    _, w = scr.getmaxyx()
    put(0, 0, " " * w, A["gray"])
    x, xs = 1, []
    for i, (title, _) in enumerate(MENUS):
        label = f" {title} "
        put(0, x, label, A["sel"] if i == active else A["gray"])
        xs.append(x)
        x += len(label) + 1
    put(0, max(x, w - len(c.NAME) - 2), c.NAME, A["gray"])
    return xs


def statusbar(text=None):
    h, w = scr.getmaxyx()
    put(h - 1, 0, " " * w, A["gray"])
    put_tilde(h - 1, 1, text or DEFAULT_STATUS, A["gray"], A["gray_hot"])


def main_window(sel):
    h, w = scr.getmaxyx()
    n = len(LIST_ITEMS)
    wh, ww = n + 8, 52
    y, x = max(1, (h - wh) // 2), max(0, (w - ww) // 2)
    box(y, x, wh, ww, "internet-check", "blue")
    put(y + 2, x + 3, "Equipo:", A["win_hi"])
    put(y + 2, x + 11, c.NAME[: ww - 14], A["win"])
    put(y + 3, x + 3, "Bot:", A["win_hi"])
    ok = bool(c.TOKEN and c.CHAT_ID)
    put(y + 3, x + 11, "configurado" if ok else "NO configurado (¿sudo?)", A["win"])
    for i, (label, shortcut, _) in enumerate(LIST_ITEMS):
        attr = A["list_sel"] if i == sel else A["win"]
        row = y + 5 + i
        put(row, x + 2, " " * (ww - 4), attr)
        put(row, x + 3, (G["arrow"] + " " if i == sel else "  ") + label, attr)
        put(row, x + ww - 3 - len(shortcut), shortcut, attr)
    put(y + wh - 2, x + 3, "Enter: abrir  -  F10: menu", A["win_dim"])


def base(status=None, active=None):
    scr.erase()
    desktop()
    main_window(STATE["sel"])
    xs = menubar(active)
    statusbar(status)
    return xs


# ---------------------------------------------------------------- diálogos

def draw_dialog(title, lines, button="OK", width=None, attr_error=False):
    h, w = scr.getmaxyx()
    limit = max(24, min(60, w - 12))
    lines = [part for s in lines for part in (textwrap.wrap(clean(s), limit) or [""])]
    inner = max([len(s) for s in lines] + [len(button or "") + 6, 24])
    dw = min(w - 4, width or inner + 6)
    dh = len(lines) + 4 + (3 if button else 0)
    y, x = max(1, (h - dh) // 2), max(0, (w - dw) // 2)
    box(y, x, dh, dw, title, "gray")
    for i, s in enumerate(lines):
        put(y + 2 + i, x + 3, s[: dw - 6], A["error"] if attr_error else A["gray"])
    if button:
        label = f"  {button}  "
        bx = x + (dw - len(label)) // 2
        by = y + 3 + len(lines)
        put(by, bx, label, A["btn"] | curses.A_BOLD)
        put(by, bx + len(label), G["bshadow_r"], A["btn_shadow"])
        put(by + 1, bx + 1, G["bshadow_b"] * len(label), A["btn_shadow"])


def msgbox(title, lines, error=False):
    base("~Enter~ Aceptar")
    draw_dialog(title, lines, "OK", attr_error=error)
    while True:
        k = scr.getch()
        if k in (10, 13, 27, ord(" "), ord("q"), curses.KEY_ENTER):
            return
        if k == curses.KEY_RESIZE:
            base("~Enter~ Aceptar")
            draw_dialog(title, lines, "OK", attr_error=error)


def busy(message):
    base("Espera...")
    draw_dialog("Espera", [message], button=None)
    scr.refresh()


def scrollable(title, text):
    """Ventana azul con barra de desplazamiento. Esc / Enter / q para cerrar."""
    top = 0
    while True:
        h, w = scr.getmaxyx()
        ww, wh = min(w - 6, 96), max(8, h - 6)
        y, x = 2 if h > 14 else 1, (w - ww) // 2
        inner, room = ww - 6, wh - 2
        lines = []
        for line in clean(text).splitlines():
            lines += textwrap.wrap(line, inner) or [""]
        top = max(0, min(top, max(0, len(lines) - room)))
        base("~Esc~ Cerrar  ~↑↓~ Desplazar  ~PgUp/PgDn~ Página")
        box(y, x, wh, ww, title, "blue")
        for i, line in enumerate(lines[top: top + room]):
            put(y + 1 + i, x + 3, line, A["win"])
        # barra de desplazamiento sobre el borde derecho
        for r in range(room):
            put(y + 1 + r, x + ww - 1, G["track"], A["scroll"])
        if len(lines) > room:
            pos = int(top / (len(lines) - room) * (room - 1))
            put(y + 1 + pos, x + ww - 1, G["thumb"], A["win"])
        k = scr.getch()
        if k in (27, 10, 13, ord("q"), curses.KEY_ENTER):
            return
        if k in (curses.KEY_DOWN, ord("j")):
            top += 1
        elif k in (curses.KEY_UP, ord("k")):
            top -= 1
        elif k == curses.KEY_NPAGE:
            top += room
        elif k == curses.KEY_PPAGE:
            top -= room
        elif k == curses.KEY_HOME:
            top = 0
        elif k == curses.KEY_END:
            top = len(lines)


# ---------------------------------------------------------------- menús desplegables

def run_menu(start=0):
    """Barra de menú con desplegables. Devuelve la acción elegida o None."""
    idx, item = start, 0
    while True:
        xs = base("~←→~ Menú  ~↑↓~ Opción  ~Enter~ Elegir  ~Esc~ Cerrar", active=idx)
        items = MENUS[idx][1]
        w = max(len(strip_tilde(lbl)) + len(sc) for lbl, sc, _ in items) + 8
        h = len(items) + 2
        x = min(xs[idx], scr.getmaxyx()[1] - w - 2)
        box(1, x, h, w, kind="menu")
        for i, (lbl, sc, _) in enumerate(items):
            attr, hot = (A["sel"], A["sel_hot"]) if i == item else (A["gray"], A["gray_hot"])
            put(2 + i, x + 1, " " * (w - 2), attr)
            put_tilde(2 + i, x + 2, lbl, attr, hot)
            put(2 + i, x + w - 2 - len(sc), sc, attr)
        k = scr.getch()
        if k in (27, curses.KEY_F10):
            return None
        if k == curses.KEY_LEFT:
            idx, item = (idx - 1) % len(MENUS), 0
        elif k == curses.KEY_RIGHT:
            idx, item = (idx + 1) % len(MENUS), 0
        elif k == curses.KEY_UP:
            item = (item - 1) % len(items)
        elif k == curses.KEY_DOWN:
            item = (item + 1) % len(items)
        elif k in (10, 13, curses.KEY_ENTER):
            return items[item][2]
        elif 32 <= k < 127:
            for lbl, _, action in items:
                m = re.search(r"~(.)~", lbl)
                if m and m.group(1).lower() == chr(k).lower():
                    return action


# ---------------------------------------------------------------- acciones

def send_to_bot(text):
    if not (c.TOKEN and c.CHAT_ID):
        return "Bot no configurado: no se envio (usa sudo)."
    return "Enviado al bot." if c.send_telegram(text) else "No se pudo enviar al bot."


def bar(frac, width=22):
    n = int(max(0.0, min(frac, 1.0)) * width)
    return G["bar_on"] * n + G["bar_off"] * (width - n)


def run_speed():
    st = {"ping": None, "down": (0.0, 0.0), "up": (0.0, 0.0)}

    def paint():
        base("Midiendo...")
        ping = "..." if st["ping"] is None else f"{st['ping']:.0f} ms"
        draw_dialog("Test de velocidad", [
            f"Latencia   {ping}",
            f"Bajada     {bar(st['down'][1])} {st['down'][0]:7.1f} Mbps",
            f"Subida     {bar(st['up'][1])} {st['up'][0]:7.1f} Mbps",
        ], button=None, width=58)
        scr.refresh()

    def on_progress(phase, value, frac):
        st[phase] = value if phase == "ping" else (value, frac)
        paint()

    paint()
    try:
        res = reports.run_speedtest("tui", on_progress)
    except Exception as e:  # noqa: BLE001
        msgbox("Error", [f"El test ha fallado: {e}"], error=True)
        return
    busy("Enviando al bot...")
    msgbox("Resultado", [
        f"Bajada:    {res['down_mbps']:.1f} Mbps",
        f"Subida:    {res['up_mbps']:.1f} Mbps",
        f"Latencia:  {res['ping_ms']:.0f} ms",
        "",
        send_to_bot(c.fmt_speed(res)),
    ])


def run_ip():
    busy("Consultando la IP publica...")
    ip = c.public_ip()
    if not ip:
        msgbox("Error", ["No se pudo obtener la IP publica."], error=True)
        return
    busy("Enviando al bot...")
    msgbox("IP pública", [f"IP publica:  {ip}", "", send_to_bot(c.fmt_ip(ip))])


def run_report(action):
    title, fn = REPORTS[action]
    busy(f"Preparando: {title.lower()}...")
    try:
        text = fn()
    except Exception as e:  # noqa: BLE001
        msgbox("Error", [str(e)], error=True)
        return
    scrollable(title, text)


def about():
    msgbox("Acerca de", info.about_lines())


def run_update():
    busy("Buscando una versión nueva...")
    rel, newer, error = updates.check()
    if error:
        msgbox("Actualización", [f"No se pudo consultar la última versión: {error}"], error=True)
        return
    msgbox("Actualización", updates.message(rel, newer).splitlines())


def run_export(days):
    """Genera el zip de CSV y lo envía al bot; sin bot, lo guarda en la carpeta actual."""
    busy("Preparando la exportación...")
    try:
        data, counts = export.build_zip(days or None)
    except Exception as e:  # noqa: BLE001
        msgbox("Error", [f"No se pudo exportar: {e}"], error=True)
        return
    name = export.filename(days or None)
    lines = export.summary_text(counts, days or None).splitlines()
    if c.TOKEN and c.CHAT_ID:
        busy("Enviando al bot...")
        sent = c.send_document(data, name, lines[0], to=c.CHAT_ID, content_type="application/zip")
        lines += ["", "Enviado al bot." if sent else "No se pudo enviar al bot."]
    else:
        try:
            with open(name, "wb") as f:
                f.write(data)
            lines += ["", f"Bot no configurado: guardado en {os.path.abspath(name)}"]
        except OSError as e:
            lines += ["", f"No se pudo guardar el archivo: {e}"]
    msgbox("Exportación", lines)


def act(action):
    """Ejecuta una acción; devuelve True si hay que salir."""
    if action == "quit":
        return True
    if action == "speed":
        run_speed()
    elif action == "ip":
        run_ip()
    elif action == "update":
        run_update()
    elif action in ("export30", "export0"):
        run_export(int(action[6:]))
    elif action == "about":
        about()
    elif action in REPORTS:
        run_report(action)
    return False


# ---------------------------------------------------------------- bucle principal

def ui(stdscr):
    global scr, G
    scr = stdscr
    G = UTF if "utf" in (locale.getpreferredencoding() or "").lower() else ASCII
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    scr.keypad(True)
    init_colors()
    n = len(LIST_ITEMS)
    while True:
        base()
        k = scr.getch()
        action = None
        if k in (curses.KEY_UP, ord("k")):
            STATE["sel"] = (STATE["sel"] - 1) % n
        elif k in (curses.KEY_DOWN, ord("j")):
            STATE["sel"] = (STATE["sel"] + 1) % n
        elif k in (10, 13, curses.KEY_ENTER):
            action = LIST_ITEMS[STATE["sel"]][2]
        elif k in FKEYS:
            action = FKEYS[k]
        elif k in (curses.KEY_F10, ord("m")):
            action = run_menu()
        elif k in (ord("q"), 27):
            action = "quit"
        if action and act(action):
            return


def main() -> int:
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(ui)
    return 0


if __name__ == "__main__":
    sys.exit(main())
