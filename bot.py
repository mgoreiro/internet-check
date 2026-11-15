# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Bot de Telegram bidireccional (long polling) con menú de botones.

Solo responde al chat configurado en TELEGRAM_CHAT_ID.
"""
import logging
import os
import subprocess
import threading
import time

import common as c
import db
import lan
import reports

log = logging.getLogger("internet-check.bot")

MENU = {
    "inline_keyboard": [
        [{"text": "📊 Estado", "callback_data": "status"},
         {"text": "🚀 Test velocidad", "callback_data": "speed"}],
        [{"text": "🌍 IP pública", "callback_data": "ip"},
         {"text": "📉 Caídas", "callback_data": "outages"}],
        [{"text": "📈 Velocidad (histórico)", "callback_data": "speeds"},
         {"text": "📡 Dispositivos", "callback_data": "devices"}],
        [{"text": "💡 Encender equipo", "callback_data": "wol"},
         {"text": "🔄 Reiniciar", "callback_data": "reboot"}],
    ]
}
COMMANDS = [
    {"command": "menu", "description": "Mostrar el menú"},
    {"command": "estado", "description": "Estado de la conexión"},
    {"command": "velocidad", "description": "Test de velocidad"},
    {"command": "ip", "description": "IP pública"},
    {"command": "caidas", "description": "Historial de caídas"},
    {"command": "historico", "description": "Histórico de velocidad"},
    {"command": "dispositivos", "description": "Dispositivos de la red"},
    {"command": "encender", "description": "Encender un equipo (Wake-on-LAN)"},
    {"command": "reiniciar", "description": "Reiniciar la Orange Pi"},
]
REBOOT_ENABLED = os.environ.get("REBOOT_ENABLED", "1") != "0"
REBOOT_CONFIRM_SECONDS = 60
_reboot_asked = [0.0]  # cuándo se pidió la confirmación


def do_menu():
    c.send_telegram("¿Qué quieres hacer?", MENU)


def do_status():
    c.send_telegram(reports.status_text(), MENU)


def do_speed():
    if not reports.SPEED_LOCK.acquire(blocking=False):
        c.send_telegram("⏳ Ya hay un test en curso.")
        return
    try:
        c.send_telegram("⏳ Midiendo velocidad (unos 20 s)…")
        try:
            res = reports.run_speedtest("bot")
        except Exception as e:  # noqa: BLE001
            c.send_telegram(f"❌ Error en el test: {e}", MENU)
            return
        c.send_telegram(c.fmt_speed(res), MENU)
    finally:
        reports.SPEED_LOCK.release()


def do_ip():
    c.send_telegram(c.fmt_ip(c.public_ip()), MENU)


def do_outages():
    c.send_telegram(reports.history_text(), MENU)


def do_speeds():
    c.send_telegram(reports.speed_history_text(), MENU)


def do_devices():
    c.send_telegram("⏳ Escaneando la red…")
    c.send_telegram(reports.devices_text(), MENU)


def do_wol_menu():
    devs = lan.wol_devices()
    if not devs:
        c.send_telegram("💡 No hay equipos configurados. Añade en /etc/internet-check/config.env:\n"
                        "WOL_DEVICES=PC=AA:BB:CC:DD:EE:FF,NAS=11:22:33:44:55:66", MENU)
        return
    kb = [[{"text": f"💡 {name}", "callback_data": f"wol:{i}"}] for i, (name, _) in enumerate(devs)]
    c.send_telegram("¿Qué equipo quieres encender?", {"inline_keyboard": kb})


def do_wol_send(index):
    devs = lan.wol_devices()
    if index >= len(devs):
        c.send_telegram("❌ Equipo no encontrado.", MENU)
        return
    name, mac = devs[index]
    try:
        lan.send_magic(mac)
    except OSError as e:
        c.send_telegram(f"❌ No se pudo enviar el paquete: {e}", MENU)
        return
    c.send_telegram(f"✅ Paquete Wake-on-LAN enviado a {name} ({mac}).", MENU)


def do_reboot_ask():
    if not REBOOT_ENABLED:
        c.send_telegram("🔒 El reinicio remoto está desactivado (REBOOT_ENABLED=0).", MENU)
        return
    _reboot_asked[0] = time.time()
    c.send_telegram(f"⚠️ ¿Reiniciar {c.NAME}?\nSe perderá la conexión durante aproximadamente un minuto.",
                    {"inline_keyboard": [[
                        {"text": "✅ Sí, reiniciar", "callback_data": "reboot_yes"},
                        {"text": "❌ Cancelar", "callback_data": "cancel"}]]})


def do_reboot_confirm():
    # La confirmación caduca: un botón antiguo no debe poder reiniciar el equipo
    if not REBOOT_ENABLED or time.time() - _reboot_asked[0] > REBOOT_CONFIRM_SECONDS:
        _reboot_asked[0] = 0.0
        c.send_telegram("⌛ La confirmación ha caducado. Pide el reinicio de nuevo.", MENU)
        return
    _reboot_asked[0] = 0.0
    try:
        db.kv_set("reboot_requested", time.time())
    except Exception:  # noqa: BLE001
        log.exception("No se pudo anotar el reinicio")
    c.send_telegram(f"🔄 Reiniciando {c.NAME}… te aviso cuando vuelva.")
    log.warning("Reinicio solicitado desde Telegram")
    time.sleep(2)  # deja salir el mensaje
    for cmd in (["systemctl", "reboot"], ["/sbin/reboot"]):
        try:
            if subprocess.run(cmd, timeout=30).returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            continue
    db.kv_del("reboot_requested")
    c.send_telegram("❌ No se pudo reiniciar (¿el servicio no se ejecuta como root?).", MENU)


def do_cancel():
    _reboot_asked[0] = 0.0
    c.send_telegram("👍 Cancelado.", MENU)


ACTIONS = {
    "status": do_status, "/estado": do_status,
    "speed": do_speed, "/velocidad": do_speed, "/speed": do_speed,
    "ip": do_ip, "/ip": do_ip,
    "outages": do_outages, "/caidas": do_outages,
    "speeds": do_speeds, "/historico": do_speeds,
    "devices": do_devices, "/dispositivos": do_devices,
    "wol": do_wol_menu, "/encender": do_wol_menu,
    "reboot": do_reboot_ask, "/reiniciar": do_reboot_ask,
    "reboot_yes": do_reboot_confirm, "cancel": do_cancel,
    "/start": do_menu, "/menu": do_menu,
}


def handle(update: dict) -> None:
    cb = update.get("callback_query")
    msg = update.get("message")
    if cb:
        chat = (cb.get("message") or {}).get("chat", {}).get("id")
        key = cb.get("data")
        c.tg_api("answerCallbackQuery", {"callback_query_id": cb["id"]}, quiet=True)
    elif msg:
        chat = msg.get("chat", {}).get("id")
        words = (msg.get("text") or "").split()
        key = words[0].split("@")[0].lower() if words else None
    else:
        return
    if str(chat) != str(c.CHAT_ID):
        log.warning("Mensaje ignorado de chat no autorizado: %s", chat)
        return
    log.info("Recibido %r del chat %s", key, chat)
    if key and key.startswith("wol:") and key[4:].isdigit():
        threading.Thread(target=do_wol_send, args=(int(key[4:]),), daemon=True).start()
        return
    action = ACTIONS.get(key)
    if action is None:
        if msg:  # texto cualquiera: mostrar el menú
            do_menu()
        return
    threading.Thread(target=_safe, args=(action,), daemon=True).start()  # no bloquear el polling


def _safe(action):
    try:
        action()
    except Exception:  # noqa: BLE001
        log.exception("Error ejecutando %s", action.__name__)
        c.send_telegram("❌ Error interno ejecutando la acción.", MENU)


def run_bot() -> None:
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
            log.info("Bot escuchando")
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
