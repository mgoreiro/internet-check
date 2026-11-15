# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

## [1.7.1] — 2026-11-15
### Añadido
- Comando `/latido`: estado del latido de la alarma de caída, envío de prueba y pausa de hasta 60
  minutos para probar la alarma sin tocar cables.
### Eliminado
- `tools/prueba_bot_a_bot.sh`: la alarma solo con Telegram no es viable hoy (Bot-to-Bot Communication
  Mode no aparece en los ajustes de BotFather); se usa el latido a un servicio externo.

## [1.7.0] — 2026-11-15
### Añadido
- Vigilancia de equipos y servicios propios (`WATCH_TARGETS`: TCP, ping y HTTP), con aviso de caída y
  recuperación, disponibilidad en `/vigilancia` y en los informes.
- Nombres de dispositivos (`/nombrar`) y presencia (`/presencia`): aviso cuando un dispositivo
  vigilado llega o se va.
- Modo no molestar (`QUIET_HOURS` y `/silencio`): retiene los avisos poco urgentes y los entrega en un
  resumen. Las caídas de Internet, los reinicios y las caídas de servicios llegan siempre.
- Latido (`HEARTBEAT_URL`): alarma de caída de la conexión a través de un servicio externo que avisa a
  Telegram cuando dejan de llegar los latidos.
- TUI: presencia y servicios vigilados en el menú Red.
### Cambiado
- La base de datos migra sola las columnas nuevas de `devices`.

## [1.6.0] — 2026-11-15
### Añadido
- Gráficas PNG de latencia, pérdida, velocidad y salud (botón 🖼️ y `/graficas`), dibujadas sin
  dependencias externas.
- Varios usuarios autorizados: administradores (`TELEGRAM_CHAT_ID`, `TELEGRAM_ADMINS`) y espectadores
  de solo consulta (`TELEGRAM_VIEWERS`, grupos incluidos), con copia opcional de los avisos
  (`TELEGRAM_NOTIFY_VIEWERS`). Cada respuesta va al chat que la pidió.
- Exportación del histórico a CSV en un zip (botón 📤 y `/exportar`; también desde la TUI).
- Aviso de versión nueva consultando las releases de GitHub (botón 🔎, `/actualizar` y aviso
  automático diario, `UPDATE_CHECK_HOURS`). No instala nada por su cuenta.
- TUI: exportar CSV y buscar actualización.

## [1.5.2] — 2026-11-15
### Corregido
- Autor: se identifica como Miguel González Oreiro en cabeceras, documentación, «Acerca de» y
  metadatos del paquete.
- Al desinstalar se elimina la carpeta `__pycache__` que Python crea en `/usr/lib/internet-check`.

## [1.5.1] — 2026-11-15
### Añadido
- Ayuda y «Acerca de» en la TUI (menú Ayuda, `F1`, teclas y atajos) y en el bot (`/ayuda`, `/acerca`).
- La versión instalada se muestra en «Acerca de».

## [1.5.0] — 2026-11-15
### Añadido
- Calidad de la conexión: latencia, jitter, pérdida y DNS, con aviso de conexión degradada y de
  fallo de DNS (botón 📶 y `/calidad`).
- Salud de la Pi: temperatura, carga, memoria, disco y base de datos, con alarmas (botón 🩺 y `/salud`).
- Informes de 24 h, semana y mes (botón 📰 y `/informe`), y envío programado diario y semanal.
- TUI: pantallas de calidad y salud (F8, F9) y menú Informes.

## [1.4.1] — 2026-11-15
### Añadido
- Licencia GPL-3.0-or-later, cabeceras de autor y documentación (README, arquitectura).
- Fichero `copyright` en el paquete y metadatos de autor y página del proyecto.

## [1.4.0] — 2026-11-15
### Añadido
- Reinicio remoto de la Orange Pi desde el bot, con confirmación que caduca.
- Fabricante por MAC (base IEEE) y nombre NetBIOS en la lista de dispositivos.
### Cambiado
- El test de velocidad usa servidores LibreSpeed de Clouvider, con respaldo.
- El test se detiene ante un rechazo HTTP en lugar de reintentar.

## [1.3.0] — 2026-11-15
### Añadido
- TUI al estilo Turbo Vision.
### Cambiado
- La configuración se separa en `bot.env` (credenciales) y `config.env` (ajustes), con migración
  automática.

## [1.2.1] — 2026-11-15
### Corregido
- La configuración deja de ser un *conffile*: las actualizaciones ya no la pisan ni preguntan.

## [1.2.0] — 2026-11-15
### Añadido
- Botones de estado, historial de caídas, histórico de velocidad y dispositivos de la red.
- Test de velocidad programado, aviso de cambio de IP y de dispositivos nuevos.
- Wake-on-LAN y almacenamiento en SQLite.

## [1.1.1] — 2026-11-15
### Corregido
- Una parada limpia del servicio ya no genera un falso aviso de «reinicio».

## [1.1.0] — 2026-11-15
### Añadido
- Bot bidireccional con menú (test de velocidad e IP pública) y TUI.

## [1.0.0] — 2026-11-15
### Añadido
- Monitor de conexión con aviso por Telegram al recuperarla y paquete Debian.
