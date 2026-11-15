# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Textos de ayuda y «acerca de», compartidos por la TUI y el bot de Telegram."""
import os
import re

import common as c

AUTHOR = "Miguel González Oreiro <mgoreiro@gmail.com>"
LICENSE_NAME = "GPL-3.0-or-later"
REPO = "https://github.com/mgoreiro/internet-check"


def version() -> str:
    """Versión instalada (la escribe build-deb.sh) o, en desarrollo, la del CHANGELOG."""
    try:
        import _version
        return _version.VERSION
    except ImportError:
        pass
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"## \[([0-9][^\]]*)\]", line)
                if m:
                    return m.group(1) + " (desarrollo)"
    except OSError:
        pass
    return "desconocida"


# ---------------------------------------------------------------- acerca de

def about_lines():
    return [
        f"internet-check  v{version()}",
        "Monitor de conexión a Internet con bot de Telegram",
        "",
        f"Autor:     {AUTHOR}",
        f"Licencia:  {LICENSE_NAME} (software libre, sin garantía)",
        f"Web:       {REPO}",
        "",
        f"Equipo:    {c.NAME}",
        "Ajustes:   /etc/internet-check/config.env",
        "Bot:       /etc/internet-check/bot.env",
        "Datos:     /var/lib/internet-check/data.db",
        "",
        "Fabricantes: registro público del IEEE",
        "Test de velocidad: servidores LibreSpeed",
        "Interfaz inspirada en Turbo Vision de Borland",
    ]


def bot_about() -> str:
    return (f"ℹ️ internet-check v{version()}\n"
            "Monitor de conexión a Internet con bot de Telegram.\n\n"
            f"👤 Autor: {AUTHOR}\n"
            f"📜 Licencia: {LICENSE_NAME} (software libre, sin garantía)\n"
            f"🔗 {REPO}\n\n"
            f"🖥️ Equipo: {c.NAME}")


# ---------------------------------------------------------------- ayuda del bot

def bot_help() -> str:
    return (
        "❓ Ayuda de internet-check\n\n"
        "Te aviso cuando se corta Internet y cuando vuelve, y vigilo la calidad de la línea, la "
        "velocidad y la salud de la Pi. Usa los botones del /menu o estos comandos:\n\n"
        "📊 /estado — conexión, última caída, disponibilidad e IP\n"
        "🚀 /velocidad — test de velocidad (~20 s)\n"
        "🌍 /ip — IP pública\n"
        "📉 /caidas — historial de caídas\n"
        "📈 /historico — histórico de velocidad\n"
        "📡 /dispositivos — equipos de la red (fabricante, nombres)\n"
        "📶 /calidad — latencia, pérdida y DNS\n"
        "🩺 /salud — temperatura, memoria y disco\n"
        "🖼️ /graficas — gráficas de latencia, pérdida, velocidad y salud\n"
        "📰 /informe — resumen de 24 h, semana o mes\n"
        "📤 /exportar — histórico en CSV (zip)\n"
        "🔎 /actualizar — busca una versión nueva\n"
        "💡 /encender — Wake-on-LAN (solo administrador)\n"
        "🔄 /reiniciar — reinicia la Pi, con confirmación (solo administrador)\n"
        "ℹ️ /acerca — versión, autor y licencia\n\n"
        "Avisos automáticos: caídas y recuperación, conexión degradada, fallo de DNS, cambio de IP, "
        "dispositivos nuevos, temperatura/disco/memoria, versión nueva y el informe programado.\n\n"
        "Solo respondo a los chats autorizados: los administradores pueden todo y los espectadores "
        "solo consultan. Ajustes en /etc/internet-check/config.env."
    )


# ---------------------------------------------------------------- ayuda de la TUI

def tui_keys() -> str:
    return """\
ATAJOS DE TECLADO

Generales
  F1            Ayuda
  F10  o  m     Abrir la barra de menú
  Flechas       Mover por la lista y los menús (también j / k)
  Enter         Ejecutar la opción seleccionada
  Esc  o  q     Cerrar la ventana o salir

Atajos directos
  F2            Estado
  F3            Test de velocidad
  F4            IP pública
  F5            Historial de caídas
  F6            Histórico de velocidad
  F7            Dispositivos de la red
  F8            Calidad de la conexión
  F9            Salud de la Pi

En el menú
  Izquierda / Derecha   Cambiar de menú
  Arriba / Abajo        Cambiar de opción
  Letra resaltada       Ejecutar la opción con esa letra
  Esc  o  F10           Cerrar el menú

En una ventana de texto
  Arriba / Abajo        Desplazar una línea
  Re Pág / Av Pág       Desplazar una página
  Inicio / Fin          Ir al principio o al final
  Esc, Enter o q        Cerrar
"""


def tui_help() -> str:
    return f"""\
AYUDA DE INTERNET-CHECK · v{version()}

QUÉ HACE
internet-check vigila la conexión a Internet de este equipo y avisa por Telegram cuando se corta y \
cuando vuelve. Además mide la calidad de la línea, la velocidad y la salud de la Pi, y guarda un \
histórico para los informes.

CÓMO SE USA ESTA PANTALLA
Elige una opción de la lista con las flechas y pulsa Enter, o abre la barra de menú con F10. \
Los atajos F2 a F9 abren cada función directamente. Esc o q cierran una ventana. La lista \
completa de teclas está en Ayuda > Teclas y atajos.

FUNCIONES
Estado
  Conexión actual, última caída, disponibilidad de 24 h y 7 días, tiempo encendida, IP pública \
y último test de velocidad.

Test de velocidad
  Mide latencia, bajada y subida (unos 20 segundos), lo guarda en el histórico y lo envía al bot.

IP pública
  Consulta la IP pública y la envía al bot.

Historial de caídas
  Últimas caídas (internet, apagón o reinicio) con su duración y la disponibilidad.

Histórico de velocidad
  Tendencia, medias y últimos tests.

Dispositivos de la red
  Escanea la red local: IP, fabricante (por la MAC), nombre NetBIOS y DNS. Marca los nuevos.

Calidad de la conexión
  Latencia, jitter, pérdida de paquetes y tiempo de DNS de la última hora y de 24 horas.

Salud de la Pi
  Temperatura de CPU, carga, memoria, disco y tamaño de la base de datos.

Informes (menú Informes)
  Resumen diario, semanal o mensual: disponibilidad, caídas, velocidad, calidad y equipo. También \
exporta el histórico a CSV (zip): se envía al bot o, sin bot, se guarda en la carpeta actual.

Buscar actualización (menú Ayuda)
  Consulta la última versión publicada en GitHub. Nunca instala nada por su cuenta.

BOT DE TELEGRAM
Todas estas funciones están también en el bot: escribe /menu. Además permite encender equipos \
(Wake-on-LAN) y reiniciar la Pi, y envía avisos automáticos. Solo responde al chat configurado.

FICHEROS
  /etc/internet-check/bot.env      Token y chat id del bot (solo root)
  /etc/internet-check/config.env   Resto de ajustes
  /var/lib/internet-check/         Base de datos con el histórico
  Tras cambiar un ajuste:  sudo systemctl restart internet-check

SOLUCIÓN DE PROBLEMAS
  «BOT NO CONFIGURADO»
    Ejecuta la TUI con sudo o revisa bot.env (token y chat id).
  El test de velocidad falla con HTTP 429
    El servidor limita las peticiones. Espera unos minutos y reintenta.
  La lista de dispositivos sale vacía
    Define LAN_CIDR en config.env (por ejemplo 192.168.1.0/24).
  Las horas salen desfasadas
    Ajusta la zona horaria:  sudo timedatectl set-timezone Europe/Madrid
  Ver el registro del servicio
    journalctl -u internet-check -f

Autor: {AUTHOR}
Licencia {LICENSE_NAME} · {REPO}
"""
