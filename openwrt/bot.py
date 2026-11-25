# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Bot de Telegram bidireccional (long polling) con menú de botones.

Roles: los administradores (TELEGRAM_CHAT_ID y TELEGRAM_ADMINS) pueden todo; los espectadores
(TELEGRAM_VIEWERS) solo consultan. Cualquier otro chat se ignora.
"""
from __future__ import division, print_function, unicode_literals

import logging
import subprocess
import threading
import time

import common as c
import heartbeat
import info
import lan
import quiet
import reports

log = logging.getLogger("internet-check.bot")

MENU = {
    "inline_keyboard": [
        [{"text": "📊 Estado", "callback_data": "status"},
         {"text": "🚀 Test velocidad", "callback_data": "speed"}],
        [{"text": "🌍 IP pública", "callback_data": "ip"},
         {"text": "📉 Caídas", "callback_data": "outages"}],
        [{"text": "📡 Dispositivos", "callback_data": "devices"},
         {"text": "📶 Calidad", "callback_data": "quality"}],
        [{"text": "🩺 Salud", "callback_data": "health"},
         {"text": "👁️ Vigilancia", "callback_data": "watch"}],
        [{"text": "🌙 No molestar", "callback_data": "quiet"},
         {"text": "🏠 Presencia", "callback_data": "presence"}],
        [{"text": "💡 Encender equipo", "callback_data": "wol"},
         {"text": "🔄 Reiniciar", "callback_data": "reboot"}],
        [{"text": "❓ Ayuda", "callback_data": "help"},
         {"text": "ℹ️ Acerca de", "callback_data": "about"}],
    ]
}
ADMIN_ONLY = set(["wol", "reboot", "reboot_yes", "cancel", "/encender", "/reiniciar",
                  "presence", "/presencia", "quiet", "/silencio", "/latido"])
COMMANDS = [
    {"command": "menu", "description": "Mostrar el menú"},
    {"command": "estado", "description": "Estado de la conexión"},
    {"command": "velocidad", "description": "Test de velocidad"},
    {"command": "ip", "description": "IP pública"},
    {"command": "caidas", "description": "Caídas desde el arranque"},
    {"command": "dispositivos", "description": "Dispositivos de la red"},
    {"command": "calidad", "description": "Latencia, pérdida y DNS"},
    {"command": "salud", "description": "Carga, memoria y flash del router"},
    {"command": "vigilancia", "description": "Estado de los servicios vigilados"},
    {"command": "presencia", "description": "Quién está en casa"},
    {"command": "silencio", "description": "Modo no molestar"},
    {"command": "latido", "description": "Estado, prueba y pausa del latido de alarma"},
    {"command": "encender", "description": "Encender un equipo (Wake-on-LAN)"},
    {"command": "reiniciar", "description": "Reiniciar el router"},
    {"command": "ayuda", "description": "Ayuda y lista de comandos"},
    {"command": "acerca", "description": "Versión, autor y licencia"},
]
REBOOT_ENABLED = c.env("REBOOT_ENABLED", "1") != "0"
REBOOT_CONFIRM_SECONDS = 60
_reboot_asked = [0.0]


def menu():
    """Los espectadores no ven los botones de administración."""
    if c.current_role() == "admin":
        return MENU
    rows = [[b for b in row if b["callback_data"] not in ADMIN_ONLY] for row in MENU["inline_keyboard"]]
    return {"inline_keyboard": [row for row in rows if row]}


def _require_admin():
    if c.current_role() == "admin":
        return True
    c.send_telegram("🔒 Solo el administrador puede hacer esto.", menu())
    return False


def _say(text):
    c.send_telegram(text, menu())


# ---------------------------------------------------------------- consultas

def do_menu():
    c.send_telegram("¿Qué quieres hacer?", menu())


def do_status():
    _say(reports.status_text())


def do_speed():
    if not reports.SPEED_LOCK.acquire(False):
        c.send_telegram("⏳ Ya hay un test en curso.")
        return
    try:
        c.send_telegram("⏳ Midiendo velocidad (unos 20 s)…")
        try:
            res = reports.run_speedtest()
        except Exception as e:  # noqa: BLE001
            _say("❌ Error en el test: %s" % e)
            return
        _say(c.fmt_speed(res))
    finally:
        reports.SPEED_LOCK.release()


def do_ip():
    _say(c.fmt_ip(c.public_ip()))


def do_outages():
    _say(reports.history_text())


def do_devices():
    c.send_telegram("⏳ Escaneando la red…")
    _say(reports.devices_text())


def do_help():
    _say(info.bot_help())


def do_about():
    _say(info.bot_about())


def do_quality():
    _say(reports.quality_text())


def do_health():
    _say(reports.health_text())


def do_watch():
    import watch
    _say(watch.status_text())


def do_presence(args=""):
    if not _require_admin():
        return
    targets = lan.presence_targets()
    if not targets:
        _say("🏠 No hay nadie configurado. Añade en config.env:\nPRESENCE=Ana=AA:BB:CC:DD:EE:FF,Pepe=11:22:33:44:55:66")
        return
    import jobs
    lines = ["🏠 Presencia · %s" % c.NAME]
    for name, mac in targets:
        state = jobs._mem["present"].get(mac)
        lines.append("%s %s" % ("🟢" if state else "⚪" if state is None else "🔴", name) +
                     ("" if state is not None else " (aún sin escanear)"))
    _say("\n".join(lines))


def do_quiet_menu():
    if not _require_admin():
        return
    c.send_telegram(quiet.status_text() + "\n\n¿Qué quieres hacer?", {"inline_keyboard": [[
        {"text": "🌙 2 horas", "callback_data": "dnd:2"},
        {"text": "🌙 8 horas", "callback_data": "dnd:8"},
        {"text": "🔔 Desactivar", "callback_data": "dnd:0"}]]})


def do_quiet_set(hours):
    if not _require_admin():
        return
    quiet.set_manual(hours)
    _say(quiet.status_text())


def do_quiet_cmd(args=""):
    """/silencio [horas | off]"""
    if not _require_admin():
        return
    text = args.strip().lower().rstrip("h").strip()
    if not text:
        do_quiet_menu()
    elif text in ("off", "0", "no"):
        do_quiet_set(0)
    elif text.replace(".", "", 1).isdigit() and 0 < float(text) <= 72:
        do_quiet_set(float(text))
    else:
        _say("🌙 Uso:  /silencio <horas>   (por ejemplo /silencio 8)\n/silencio off para desactivarlo.")


def _heartbeat_keyboard():
    return {"inline_keyboard": [[
        {"text": "🔔 Probar envío", "callback_data": "hb:test"},
        {"text": "⏸️ Pausar 5 min", "callback_data": "hb:pause"},
        {"text": "▶️ Reanudar", "callback_data": "hb:resume"}]]}


def do_heartbeat(args="", action=None):
    """/latido [prueba | pausa [minutos] | reanudar]"""
    if not _require_admin():
        return
    word, _, rest = (action or args).strip().lower().partition(" ")
    if not heartbeat.URL or not word:
        c.send_telegram(heartbeat.status_text(), _heartbeat_keyboard() if heartbeat.URL else menu())
    elif word in ("prueba", "test"):
        ok = heartbeat.ping()
        c.send_telegram("%s a %s." % ("✅ Latido entregado" if ok else "❌ No se pudo entregar el latido",
                                      heartbeat.host()), _heartbeat_keyboard())
    elif word in ("pausa", "pause"):
        try:
            minutes = float(rest) if rest else 5.0
        except ValueError:
            minutes = 5.0
        until = heartbeat.pause(minutes)
        c.send_telegram("⏸️ Latidos pausados hasta las %s.\nSe reanudan solos al acabar, o antes con /latido reanudar."
                        % time.strftime(str("%H:%M"), time.localtime(until)), _heartbeat_keyboard())
    elif word in ("reanudar", "resume"):
        heartbeat.resume()
        c.send_telegram("▶️ Latidos reanudados.\n" + heartbeat.status_text(), _heartbeat_keyboard())
    else:
        _say("💓 Uso:  /latido  ·  /latido prueba  ·  /latido pausa [minutos]  ·  /latido reanudar")


# ---------------------------------------------------------------- administración

def do_wol_menu():
    if not _require_admin():
        return
    devs = lan.wol_devices()
    if not devs:
        _say("💡 No hay equipos configurados. Añade en config.env:\nWOL_DEVICES=PC=AA:BB:CC:DD:EE:FF,NAS=11:22:33:44:55:66")
        return
    kb = [[{"text": "💡 %s" % name, "callback_data": "wol:%d" % i}] for i, (name, _) in enumerate(devs)]
    c.send_telegram("¿Qué equipo quieres encender?", {"inline_keyboard": kb})


def do_wol_send(index):
    if not _require_admin():
        return
    devs = lan.wol_devices()
    if index >= len(devs):
        _say("❌ Equipo no encontrado.")
        return
    name, mac = devs[index]
    try:
        lan.send_magic(mac)
    except (IOError, OSError) as e:
        _say("❌ No se pudo enviar el paquete: %s" % e)
        return
    _say("✅ Paquete Wake-on-LAN enviado a %s (%s)." % (name, mac))


def do_reboot_ask():
    if not _require_admin():
        return
    if not REBOOT_ENABLED:
        _say("🔒 El reinicio remoto está desactivado (REBOOT_ENABLED=0).")
        return
    _reboot_asked[0] = time.time()
    c.send_telegram("⚠️ ¿Reiniciar %s?\nSe perderá la conexión durante aproximadamente un minuto "
                    "y se borrará el historial en memoria." % c.NAME,
                    {"inline_keyboard": [[
                        {"text": "✅ Sí, reiniciar", "callback_data": "reboot_yes"},
                        {"text": "❌ Cancelar", "callback_data": "cancel"}]]})


def do_reboot_confirm():
    if not _require_admin():
        return
    # La confirmación caduca: un botón antiguo no debe poder reiniciar el equipo
    if not REBOOT_ENABLED or time.time() - _reboot_asked[0] > REBOOT_CONFIRM_SECONDS:
        _reboot_asked[0] = 0.0
        _say("⌛ La confirmación ha caducado. Pide el reinicio de nuevo.")
        return
    _reboot_asked[0] = 0.0
    c.send_telegram("🔄 Reiniciando %s… te aviso cuando vuelva." % c.NAME)
    log.warning("Reinicio solicitado desde Telegram")
    time.sleep(2)  # deja salir el mensaje
    for cmd in (["/sbin/reboot"], ["reboot"]):
        try:
            if subprocess.call(cmd) == 0:
                return
        except OSError:
            continue
    _say("❌ No se pudo reiniciar (¿el servicio no se ejecuta como root?).")


def do_cancel():
    if not _require_admin():
        return
    _reboot_asked[0] = 0.0
    _say("👍 Cancelado.")


ACTIONS = {
    "status": do_status, "/estado": do_status,
    "speed": do_speed, "/velocidad": do_speed, "/speed": do_speed,
    "ip": do_ip, "/ip": do_ip,
    "outages": do_outages, "/caidas": do_outages,
    "devices": do_devices, "/dispositivos": do_devices,
    "help": do_help, "/ayuda": do_help, "/help": do_help,
    "about": do_about, "/acerca": do_about,
    "quality": do_quality, "/calidad": do_quality,
    "health": do_health, "/salud": do_health,
    "watch": do_watch, "/vigilancia": do_watch,
    "presence": do_presence,
    "quiet": do_quiet_menu,
    "wol": do_wol_menu, "/encender": do_wol_menu,
    "reboot": do_reboot_ask, "/reiniciar": do_reboot_ask,
    "reboot_yes": do_reboot_confirm, "cancel": do_cancel,
    "/start": do_menu, "/menu": do_menu,
}
ARG_COMMANDS = {"/presencia": do_presence, "/silencio": do_quiet_cmd, "/latido": do_heartbeat}


def resolve(key, args=""):
    """Convierte la clave de un botón o comando en una función sin argumentos, o None."""
    if not key:
        return None
    if key in ARG_COMMANDS:
        return lambda: ARG_COMMANDS[key](args)
    name, _, arg = key.partition(":")
    if arg:
        if name == "dnd" and arg in ("0", "2", "8"):
            return lambda: do_quiet_set(int(arg))
        if name == "hb" and arg in ("test", "pause", "resume"):
            return lambda: do_heartbeat(action={"test": "prueba", "pause": "pausa 5", "resume": "reanudar"}[arg])
        if name == "wol" and arg.isdigit():
            return lambda: do_wol_send(int(arg))
        return None
    return ACTIONS.get(key)


def is_admin_only(key):
    return bool(key) and (key in ADMIN_ONLY or key.startswith(("wol:", "dnd:", "hb:")))


def _spawn(fn, chat, role):
    """Ejecuta la acción en su hilo, con el chat y el rol de quien la pidió (no bloquea el polling)."""
    def runner():
        c.set_context(chat, role)
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.exception("Error ejecutando una acción")
            c.send_telegram("❌ Error interno ejecutando la acción.", menu())
        finally:
            c.clear_context()
    t = threading.Thread(target=runner)
    t.daemon = True
    t.start()


def handle(update):
    cb = update.get("callback_query")
    msg = update.get("message")
    if cb:
        chat = (cb.get("message") or {}).get("chat", {}).get("id")
        key = cb.get("data")
        args = ""
        c.tg_api("answerCallbackQuery", {"callback_query_id": cb["id"]}, quiet=True)
    elif msg:
        chat = msg.get("chat", {}).get("id")
        words = (msg.get("text") or "").split()
        key = words[0].split("@")[0].lower() if words else None
        args = " ".join(words[1:])
    else:
        return
    role = c.role_of(chat)
    if role is None:
        log.warning("Mensaje ignorado de chat no autorizado: %s", chat)
        return
    log.info("Recibido %r del chat %s (%s)", key, chat, role)
    if role != "admin" and is_admin_only(key):
        _spawn(lambda: c.send_telegram("🔒 Solo el administrador puede hacer esto.", menu()), chat, role)
        return
    action = resolve(key, args)
    if action is None:
        if msg:  # texto cualquiera: mostrar el menú
            _spawn(do_menu, chat, role)
        return
    _spawn(action, chat, role)


def run_bot():
    offset = None
    ready = False
    failing = False
    while True:
        if not ready:
            # Descarta lo pendiente de cuando estuvo apagado o sin Internet
            r = c.tg_api("getUpdates", {"offset": -1, "timeout": 0}, quiet=True)
            if r is None:
                time.sleep(5)
                continue
            if r["result"]:
                offset = r["result"][-1]["update_id"] + 1
            c.tg_api("setMyCommands", {"commands": COMMANDS}, quiet=True)
            ready = True
            log.info("Bot escuchando (%d admin, %d espectadores)", len(c.ADMINS), len(c.VIEWERS))
        params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
        if offset:
            params["offset"] = offset
        r = c.tg_api("getUpdates", params, timeout=40, quiet=True)
        if r is None:
            if not failing:
                log.warning("No se puede consultar Telegram; reintentando")
                failing = True
            time.sleep(5)
            continue
        failing = False
        for upd in r["result"]:
            offset = upd["update_id"] + 1
            try:
                handle(upd)
            except Exception:  # noqa: BLE001
                log.exception("Error procesando update")
