# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Bot de Telegram bidireccional (long polling) con menú de botones.

Roles (ver common.py): los administradores (TELEGRAM_CHAT_ID y TELEGRAM_ADMINS) pueden todo; los
espectadores (TELEGRAM_VIEWERS) solo consultan. Cualquier otro chat se ignora. Cada respuesta
se envía al chat que la pidió.
"""
import logging
import os
import subprocess
import threading
import time

import charts
import common as c
import db
import export
import info
import lan
import reports
import updates

log = logging.getLogger("internet-check.bot")

MENU = {
    "inline_keyboard": [
        [{"text": "📊 Estado", "callback_data": "status"},
         {"text": "🚀 Test velocidad", "callback_data": "speed"}],
        [{"text": "🌍 IP pública", "callback_data": "ip"},
         {"text": "📉 Caídas", "callback_data": "outages"}],
        [{"text": "📈 Velocidad (histórico)", "callback_data": "speeds"},
         {"text": "📡 Dispositivos", "callback_data": "devices"}],
        [{"text": "📶 Calidad", "callback_data": "quality"},
         {"text": "🩺 Salud", "callback_data": "health"}],
        [{"text": "🖼️ Gráficas", "callback_data": "chart"},
         {"text": "📰 Informe", "callback_data": "report"}],
        [{"text": "📤 Exportar", "callback_data": "export"},
         {"text": "🔎 Actualización", "callback_data": "update"}],
        [{"text": "💡 Encender equipo", "callback_data": "wol"},
         {"text": "🔄 Reiniciar", "callback_data": "reboot"}],
        [{"text": "❓ Ayuda", "callback_data": "help"},
         {"text": "ℹ️ Acerca de", "callback_data": "about"}],
    ]
}
# Acciones que solo puede pedir un administrador
ADMIN_ONLY = {"wol", "reboot", "reboot_yes", "cancel", "/encender", "/reiniciar"}
COMMANDS = [
    {"command": "menu", "description": "Mostrar el menú"},
    {"command": "estado", "description": "Estado de la conexión"},
    {"command": "velocidad", "description": "Test de velocidad"},
    {"command": "ip", "description": "IP pública"},
    {"command": "caidas", "description": "Historial de caídas"},
    {"command": "historico", "description": "Histórico de velocidad"},
    {"command": "dispositivos", "description": "Dispositivos de la red"},
    {"command": "calidad", "description": "Latencia, pérdida y DNS"},
    {"command": "salud", "description": "Temperatura, memoria y disco de la Pi"},
    {"command": "graficas", "description": "Gráficas de latencia, pérdida, velocidad y salud"},
    {"command": "informe", "description": "Informe de 24 h, semana o mes"},
    {"command": "exportar", "description": "Exportar el histórico a CSV"},
    {"command": "actualizar", "description": "Buscar una versión nueva"},
    {"command": "encender", "description": "Encender un equipo (Wake-on-LAN)"},
    {"command": "reiniciar", "description": "Reiniciar la Orange Pi"},
    {"command": "ayuda", "description": "Ayuda y lista de comandos"},
    {"command": "acerca", "description": "Versión, autor y licencia"},
]
REBOOT_ENABLED = os.environ.get("REBOOT_ENABLED", "1") != "0"
REBOOT_CONFIRM_SECONDS = 60
_reboot_asked = [0.0]  # cuándo se pidió la confirmación


def menu():
    """Teclado del menú según quién pregunta: los espectadores no ven los botones de administración."""
    if c.current_role() == "admin":
        return MENU
    rows = [[b for b in row if b["callback_data"] not in ADMIN_ONLY] for row in MENU["inline_keyboard"]]
    return {"inline_keyboard": [row for row in rows if row]}


def _require_admin() -> bool:
    if c.current_role() == "admin":
        return True
    c.send_telegram("🔒 Solo el administrador puede hacer esto.", menu())
    return False


# ---------------------------------------------------------------- consultas

def do_menu():
    c.send_telegram("¿Qué quieres hacer?", menu())


def do_status():
    c.send_telegram(reports.status_text(), menu())


def do_speed():
    if not reports.SPEED_LOCK.acquire(blocking=False):
        c.send_telegram("⏳ Ya hay un test en curso.")
        return
    try:
        c.send_telegram("⏳ Midiendo velocidad (unos 20 s)…")
        try:
            res = reports.run_speedtest("bot")
        except Exception as e:  # noqa: BLE001
            c.send_telegram(f"❌ Error en el test: {e}", menu())
            return
        c.send_telegram(c.fmt_speed(res), menu())
    finally:
        reports.SPEED_LOCK.release()


def do_ip():
    c.send_telegram(c.fmt_ip(c.public_ip()), menu())


def do_outages():
    c.send_telegram(reports.history_text(), menu())


def do_speeds():
    c.send_telegram(reports.speed_history_text(), menu())


def do_devices():
    c.send_telegram("⏳ Escaneando la red…")
    c.send_telegram(reports.devices_text(), menu())


def do_help():
    c.send_telegram(info.bot_help(), menu())


def do_about():
    c.send_telegram(info.bot_about(), menu())


def do_quality():
    c.send_telegram(reports.quality_text(), menu())


def do_health():
    c.send_telegram(reports.health_text(), menu())


def do_report_menu():
    c.send_telegram("¿Qué periodo quieres?", {"inline_keyboard": [[
        {"text": "24 horas", "callback_data": "report:24"},
        {"text": "Semana", "callback_data": "report:168"},
        {"text": "Mes", "callback_data": "report:720"}]]})


def do_report_send(hours):
    c.send_telegram(reports.period_report_text(hours), menu())


# ---------------------------------------------------------------- gráficas, exportación y versión

def do_chart_menu():
    c.send_telegram("¿Qué gráfica quieres?", {"inline_keyboard": [
        [{"text": "📶 Latencia 24 h", "callback_data": "chart:latency"},
         {"text": "📉 Pérdida 24 h", "callback_data": "chart:loss"}],
        [{"text": "🚀 Velocidad 7 días", "callback_data": "chart:speed"},
         {"text": "🩺 Salud 24 h", "callback_data": "chart:health"}]]})


def do_chart_send(kind):
    result = charts.CHARTS[kind]()
    if result is None:
        c.send_telegram("📊 Aún no hay datos suficientes para esa gráfica.", menu())
        return
    png, caption = result
    if not c.send_photo(png, caption, menu()):
        c.send_telegram("❌ No se pudo enviar la gráfica.", menu())


def do_export_menu():
    c.send_telegram("¿Qué periodo quieres exportar a CSV?", {"inline_keyboard": [[
        {"text": "7 días", "callback_data": "export:7"},
        {"text": "30 días", "callback_data": "export:30"},
        {"text": "Todo", "callback_data": "export:0"}]]})


def do_export_send(days):
    data, counts = export.build_zip(days or None)
    if not c.send_document(data, export.filename(days or None), export.summary_text(counts, days or None),
                           menu(), content_type="application/zip"):
        c.send_telegram("❌ No se pudo enviar el archivo.", menu())


def do_update():
    rel, newer, error = updates.check()
    if error:
        c.send_telegram(f"❌ No se pudo consultar la última versión: {error}", menu())
        return
    c.send_telegram(updates.message(rel, newer), menu())


# ---------------------------------------------------------------- administración

def do_wol_menu():
    if not _require_admin():
        return
    devs = lan.wol_devices()
    if not devs:
        c.send_telegram("💡 No hay equipos configurados. Añade en /etc/internet-check/config.env:\n"
                        "WOL_DEVICES=PC=AA:BB:CC:DD:EE:FF,NAS=11:22:33:44:55:66", menu())
        return
    kb = [[{"text": f"💡 {name}", "callback_data": f"wol:{i}"}] for i, (name, _) in enumerate(devs)]
    c.send_telegram("¿Qué equipo quieres encender?", {"inline_keyboard": kb})


def do_wol_send(index):
    if not _require_admin():
        return
    devs = lan.wol_devices()
    if index >= len(devs):
        c.send_telegram("❌ Equipo no encontrado.", menu())
        return
    name, mac = devs[index]
    try:
        lan.send_magic(mac)
    except OSError as e:
        c.send_telegram(f"❌ No se pudo enviar el paquete: {e}", menu())
        return
    c.send_telegram(f"✅ Paquete Wake-on-LAN enviado a {name} ({mac}).", menu())


def do_reboot_ask():
    if not _require_admin():
        return
    if not REBOOT_ENABLED:
        c.send_telegram("🔒 El reinicio remoto está desactivado (REBOOT_ENABLED=0).", menu())
        return
    _reboot_asked[0] = time.time()
    c.send_telegram(f"⚠️ ¿Reiniciar {c.NAME}?\nSe perderá la conexión durante aproximadamente un minuto.",
                    {"inline_keyboard": [[
                        {"text": "✅ Sí, reiniciar", "callback_data": "reboot_yes"},
                        {"text": "❌ Cancelar", "callback_data": "cancel"}]]})


def do_reboot_confirm():
    if not _require_admin():
        return
    # La confirmación caduca: un botón antiguo no debe poder reiniciar el equipo
    if not REBOOT_ENABLED or time.time() - _reboot_asked[0] > REBOOT_CONFIRM_SECONDS:
        _reboot_asked[0] = 0.0
        c.send_telegram("⌛ La confirmación ha caducado. Pide el reinicio de nuevo.", menu())
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
    c.send_telegram("❌ No se pudo reiniciar (¿el servicio no se ejecuta como root?).", menu())


def do_cancel():
    if not _require_admin():
        return
    _reboot_asked[0] = 0.0
    c.send_telegram("👍 Cancelado.", menu())


ACTIONS = {
    "status": do_status, "/estado": do_status,
    "speed": do_speed, "/velocidad": do_speed, "/speed": do_speed,
    "ip": do_ip, "/ip": do_ip,
    "outages": do_outages, "/caidas": do_outages,
    "speeds": do_speeds, "/historico": do_speeds,
    "devices": do_devices, "/dispositivos": do_devices,
    "help": do_help, "/ayuda": do_help, "/help": do_help,
    "about": do_about, "/acerca": do_about,
    "quality": do_quality, "/calidad": do_quality,
    "health": do_health, "/salud": do_health,
    "report": do_report_menu, "/informe": do_report_menu,
    "chart": do_chart_menu, "/graficas": do_chart_menu,
    "export": do_export_menu, "/exportar": do_export_menu,
    "update": do_update, "/actualizar": do_update,
    "wol": do_wol_menu, "/encender": do_wol_menu,
    "reboot": do_reboot_ask, "/reiniciar": do_reboot_ask,
    "reboot_yes": do_reboot_confirm, "cancel": do_cancel,
    "/start": do_menu, "/menu": do_menu,
}


def resolve(key):
    """Convierte la clave de un botón o comando en una función sin argumentos, o None."""
    if not key:
        return None
    name, _, arg = key.partition(":")
    if arg:
        if name == "wol" and arg.isdigit():
            return lambda: do_wol_send(int(arg))
        if name == "report" and arg in ("24", "168", "720"):
            return lambda: do_report_send(int(arg))
        if name == "chart" and arg in charts.CHARTS:
            return lambda: do_chart_send(arg)
        if name == "export" and arg in ("0", "7", "30"):
            return lambda: do_export_send(int(arg))
        return None
    return ACTIONS.get(key)


def is_admin_only(key) -> bool:
    return bool(key) and (key in ADMIN_ONLY or key.startswith("wol:"))


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
    threading.Thread(target=runner, daemon=True).start()


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
    role = c.role_of(chat)
    if role is None:
        log.warning("Mensaje ignorado de chat no autorizado: %s", chat)
        return
    log.info("Recibido %r del chat %s (%s)", key, chat, role)
    if role != "admin" and is_admin_only(key):
        _spawn(lambda: c.send_telegram("🔒 Solo el administrador puede hacer esto.", menu()), chat, role)
        return
    action = resolve(key)
    if action is None:
        if msg:  # texto cualquiera: mostrar el menú
            _spawn(do_menu, chat, role)
        return
    _spawn(action, chat, role)


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
