# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).

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
