# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Textos de ayuda y «acerca de» del bot."""
from __future__ import division, print_function, unicode_literals

import os

import common as c

AUTHOR = "Miguel González Oreiro <mgoreiro@gmail.com>"
LICENSE_NAME = "GPL-3.0-or-later"
REPO = "https://github.com/mgoreiro/internet-check"


def version():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as f:
            return f.read().strip() or "desconocida"
    except (IOError, OSError):
        return "desconocida (desarrollo)"


def bot_about():
    return ("ℹ️ internet-check v%s (edición OpenWrt, Python 3)\n"
            "Monitor de conexión a Internet con bot de Telegram.\n\n"
            "👤 Autor: %s\n📜 Licencia: %s (software libre, sin garantía)\n🔗 %s\n\n🖥️ Equipo: %s"
            % (version(), AUTHOR, LICENSE_NAME, REPO, c.NAME))


def bot_help():
    return (
        "❓ Ayuda de internet-check (OpenWrt)\n\n"
        "Te aviso cuando se corta Internet y cuando vuelve, y vigilo la calidad de la línea y la salud "
        "del router. Usa los botones del /menu o estos comandos:\n\n"
        "📊 /estado — conexión, última caída, disponibilidad e IP\n"
        "🚀 /velocidad — test de velocidad (~20 s; el router tiene poca CPU, la cifra puede quedarse corta)\n"
        "🌍 /ip — IP pública\n"
        "📉 /caidas — caídas desde el arranque del servicio\n"
        "📡 /dispositivos — equipos de la red (fabricante, nombre DNS)\n"
        "📶 /calidad — latencia, pérdida y DNS de la última hora\n"
        "🩺 /salud — carga, memoria y flash\n"
        "👁️ /vigilancia — servicios y equipos vigilados\n"
        "🏠 /presencia — quién está en casa (admin)\n"
        "🌙 /silencio [horas|off] — modo no molestar (admin)\n"
        "💓 /latido [prueba|pausa|reanudar] — latido de la alarma de caída (admin)\n"
        "💡 /encender — Wake-on-LAN (admin)\n"
        "🔄 /reiniciar — reinicia el router, con confirmación (admin)\n"
        "ℹ️ /acerca — versión, autor y licencia\n\n"
        "No guardo nada en disco: el historial vive en memoria y se borra al reiniciar el servicio o el router.\n"
        "Ajustes en %s." % c.CONFIG_FILE)
