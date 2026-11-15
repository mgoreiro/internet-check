# internet-check

Monitor de conexión a Internet para una **Orange Pi Zero 2** (y cualquier Debian con systemd),
controlado por un **bot de Telegram** y por una **TUI** al estilo Turbo Vision.

- Avisa por Telegram cuando vuelve Internet tras un corte, con la hora de la caída y su duración.
- Distingue entre caída de Internet, apagón y reinicio solicitado, y calcula la disponibilidad.
- Bot bidireccional con menú de botones: estado, test de velocidad, IP pública, historiales,
  dispositivos de la red, Wake-on-LAN y reinicio remoto.
- Avisos automáticos: test de velocidad programado, cambio de IP pública y dispositivos nuevos.
- Solo **Python 3 estándar**: sin dependencias, sin `pip`, sin root para comprobar la conexión.

> Autor: **mgoreiro** · Licencia: [GPL-3.0-or-later](LICENSE)

---

## Índice
1. [Instalación](#instalación)
2. [Configuración](#configuración)
3. [Bot de Telegram](#bot-de-telegram)
4. [Avisos automáticos](#avisos-automáticos)
5. [TUI](#tui)
6. [Cómo funciona](#cómo-funciona)
7. [Privacidad y seguridad](#privacidad-y-seguridad)
8. [Desarrollo](#desarrollo)
9. [Licencia y créditos](#licencia-y-créditos)

---

## Instalación

**Requisitos:** Debian, Armbian u otra distribución con `systemd` y Python 3.7 o superior
(probado en Orange Pi Zero 2 con Debian 12 y Python 3.11).

### 1. Crear el bot de Telegram
1. En Telegram habla con **@BotFather** → `/newbot` y copia el token.
2. Escribe cualquier mensaje a tu bot nuevo.
3. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia el valor de `chat.id`.

### 2. Generar e instalar el paquete
El paquete se genera en cualquier máquina, también macOS (no necesita `dpkg-deb`):

```bash
./build-deb.sh 1.4.1
scp internet-check_1.4.1_all.deb usuario@orangepi:
```

En la Orange Pi:

```bash
sudo apt install ./internet-check_1.4.1_all.deb
sudo nano /etc/internet-check/bot.env      # token y chat id
sudo systemctl restart internet-check
journalctl -u internet-check -f
```

El instalador crea las configuraciones la primera vez y **nunca las sobrescribe** al actualizar.
Si vienes de una versión anterior a la 1.3 (con el token en `config.env`), las credenciales se
mueven solas a `bot.env`.

- Desinstalar: `sudo apt remove internet-check` (`purge` borra además configuración y datos).
- Probar: desconecta el cable de red un minuto y vuelve a conectarlo; llegará el aviso.

---

## Configuración

Hay **dos ficheros** en `/etc/internet-check/`:

| Fichero | Contenido | Permisos |
|---|---|---|
| `bot.env` | Credenciales del bot (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) | 600, solo root |
| `config.env` | Todos los demás ajustes (sin secretos) | 644 |

Tras cambiar cualquiera: `sudo systemctl restart internet-check`. Las plantillas con todos los
ajustes comentados están en `/usr/share/internet-check/`.

### Ajustes de `config.env`

| Variable | Por defecto | Descripción |
|---|---|---|
| `DEVICE_NAME` | nombre del equipo | Nombre que aparece en los mensajes |
| `CHECK_INTERVAL` | `10` | Segundos entre comprobaciones de conexión |
| `FAIL_THRESHOLD` | `3` | Fallos seguidos para dar la conexión por caída |
| `CHECK_HOSTS` | `1.1.1.1:53,8.8.8.8:53,9.9.9.9:53` | Destinos TCP de la comprobación |
| `CHECK_TIMEOUT` | `3` | Segundos de espera por destino |
| `SPEEDTEST_SERVERS` | Clouvider (Fráncfort, Londres, Ámsterdam) | Backends LibreSpeed (`https://…/backend`), por orden |
| `SPEEDTEST_SECONDS` | `8` | Duración de la bajada y de la subida |
| `SPEEDTEST_STREAMS` | `4` | Conexiones paralelas del test |
| `SPEEDTEST_EVERY_HOURS` | `6` | Test programado; `0` lo desactiva |
| `SPEED_MIN_DOWN_MBPS` | `0` | Avisa si la bajada queda por debajo; `0` = sin aviso |
| `IP_CHECK_MINUTES` | `5` | Vigila cambios de IP pública; `0` lo desactiva |
| `LAN_SCAN_MINUTES` | `10` | Busca dispositivos nuevos; `0` lo desactiva |
| `LAN_CIDR` | /24 de la interfaz principal | Red a escanear (máximo 1024 direcciones) |
| `WOL_DEVICES` | vacío | Equipos para Wake-on-LAN: `PC=AA:BB:CC:DD:EE:FF,NAS=11:22:…` |
| `WOL_BROADCAST` | `255.255.255.255` | Dirección de difusión del paquete mágico |
| `REBOOT_ENABLED` | `1` | Permite reiniciar desde el bot; `0` lo desactiva |

Para uso avanzado: `STATE_FILE`, `DB_FILE`, `OUI_FILE`, `INTERNET_CHECK_CONFIG` e
`INTERNET_CHECK_BOT_CONFIG` cambian las rutas de los ficheros de datos y configuración.

---

## Bot de Telegram

Escribe `/menu` (o cualquier texto) y aparece el menú con botones. También hay comandos:

| Botón | Comando | Qué hace |
|---|---|---|
| 📊 Estado | `/estado` | Conexión actual, última caída, disponibilidad 24 h / 7 d, uptime, IP y último test |
| 🚀 Test velocidad | `/velocidad` | Mide latencia, bajada y subida (~20 s) y lo guarda en el histórico |
| 🌍 IP pública | `/ip` | IP pública actual |
| 📉 Caídas | `/caidas` | Últimas caídas (internet, apagón o reinicio) y disponibilidad 24 h / 7 d / 30 d |
| 📈 Velocidad (histórico) | `/historico` | Mini-gráfica de tendencia, medias y últimos tests |
| 📡 Dispositivos | `/dispositivos` | Escanea la red: IP, fabricante, MAC, nombre NetBIOS y DNS; marca los nuevos con 🆕 |
| 💡 Encender equipo | `/encender` | Envía un paquete Wake-on-LAN al equipo elegido |
| 🔄 Reiniciar | `/reiniciar` | Reinicia la Orange Pi tras una confirmación que caduca a los 60 s |

**Solo responde al chat de `TELEGRAM_CHAT_ID`**; cualquier otro chat se ignora y queda anotado
en el log.

### Dispositivos: fabricante y nombres
- **Fabricante:** búsqueda por MAC en la base del IEEE (MA-L, MA-M y MA-S, unas 54.000 entradas).
  Los móviles con MAC aleatoria salen como «MAC privada (aleatoria)», porque esa MAC no
  identifica al fabricante.
- **NetBIOS:** consulta `NBSTAT` por UDP 137; responden Windows, Samba y muchas impresoras y NAS.
- **DNS:** nombre inverso, si el router lo publica.

### Wake-on-LAN
Define los equipos en `config.env`:

```
WOL_DEVICES=PC=AA:BB:CC:DD:EE:FF,NAS=11:22:33:44:55:66
```

El botón 💡 mostrará un botón por equipo. El equipo debe tener Wake-on-LAN activado y estar en
la misma red.

### Reinicio remoto
El botón 🔄 pregunta «¿Reiniciar?» con ✅ / ❌. Al volver, el bot avisa con el tiempo que tardó y
el reinicio queda en el historial de caídas con su propio icono (no cuenta como apagón).

---

## Avisos automáticos

- **Internet recuperado**, con hora de caída y duración.
- **Reinicio tras apagón**: si la Pi arranca y el último latido es antiguo, avisa de cuánto estuvo
  sin servicio. Una parada limpia (`apt`, `systemctl stop`) no se confunde con un apagón.
- **Test de velocidad programado** cada `SPEEDTEST_EVERY_HOURS`. Con `SPEED_MIN_DOWN_MBPS` avisa
  si la bajada queda por debajo del umbral.
- **Cambio de IP pública**, comprobada cada `IP_CHECK_MINUTES`.
- **Dispositivo nuevo en la red**, con escaneo cada `LAN_SCAN_MINUTES`. La primera pasada solo
  memoriza lo que hay, sin avisar.

---

## TUI

```bash
internet-check-tui
```

Interfaz de terminal al estilo **Turbo Vision**: escritorio sombreado, barra de menú con
desplegables, ventanas con borde doble y sombra, diálogos con botón y barra de estado.

| Tecla | Acción |
|---|---|
| `F10` | Menú (`←` `→` entre menús, `↑` `↓` opciones, `Enter` elegir, `Esc` cerrar) |
| `F1` | Acerca de |
| `F2` / `F5` / `F6` / `F7` | Estado / historial de caídas / histórico de velocidad / dispositivos |
| `F3` / `F4` | Test de velocidad / IP pública (se envían además al bot) |
| `Enter` | Abre la opción de la lista · `q` o `Esc` sale |

El lanzador se relanza con `sudo` para poder leer `bot.env`.

---

## Cómo funciona

- **Detección:** cada `CHECK_INTERVAL` segundos abre una conexión TCP a los destinos de
  `CHECK_HOSTS`. Tras `FAIL_THRESHOLD` fallos seguidos da la conexión por caída y, al volver,
  avisa. Si Telegram no responde al recuperar, reintenta cada 15 s hasta enviarlo.
- **Datos:** caídas, tests de velocidad y dispositivos se guardan en SQLite
  (`/var/lib/internet-check/data.db`).
- **Disponibilidad:** se calcula sobre la ventana pedida, acotada al inicio de la monitorización.

Detalles de módulos, hilos y esquema de datos en [docs/arquitectura.md](docs/arquitectura.md).

---

## Privacidad y seguridad

- El token vive en `bot.env` (600, solo root) y nunca aparece en logs ni en `config.env`.
- El bot ignora cualquier chat distinto de `TELEGRAM_CHAT_ID`. El reinicio exige confirmación con
  caducidad, de modo que un botón antiguo no puede reiniciar el equipo.
- El servicio se ejecuta como root (necesario para reiniciar el sistema). Si no quieres esa
  función, pon `REBOOT_ENABLED=0`.
- **Servicios de terceros contactados**, sin telemetría de ningún tipo:
  - Telegram (`api.telegram.org`): mensajes del bot.
  - `api.ipify.org`, `ifconfig.me`, `icanhazip.com`: para conocer la IP pública.
  - Servidores LibreSpeed de Clouvider: solo durante el test de velocidad.
- El escaneo de la red es local (ARP, NetBIOS y DNS inverso) y sus resultados no salen de la Pi,
  salvo lo que tú pidas al bot.

---

## Desarrollo

Sin dependencias: basta Python 3.7+.

```bash
# Demonio y bot, con datos en una carpeta temporal
export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=... DB_FILE=/tmp/ic/data.db STATE_FILE=/tmp/ic/state.json
python3 monitor.py

# TUI (lee bot.env y config.env, o las variables de entorno)
python3 tui.py

# Paquete .deb
./build-deb.sh 1.4.1

# Regenerar la base de fabricantes con los CSV del IEEE
python3 -I tools/build_oui.py <carpeta con oui.csv, mam.csv y oui36.csv>
```

| Archivo | Función |
|---|---|
| `monitor.py` | Demonio: detección de caídas y arranque del bot y las tareas |
| `bot.py` | Bot de Telegram: menú, acciones y reinicio |
| `jobs.py` | Tareas periódicas: test programado, IP y dispositivos |
| `reports.py` | Textos de estado, historiales y dispositivos |
| `common.py` | Configuración, Telegram, IP pública y test de velocidad |
| `lan.py` | Escaneo de red, fabricantes, NetBIOS y Wake-on-LAN |
| `db.py` | Almacenamiento SQLite |
| `tui.py` | Interfaz Turbo Vision |
| `build-deb.sh`, `packaging/` | Generación del paquete Debian |

---

## Licencia y créditos

Copyright © 2026 mgoreiro <mgoreiro@gmail.com>

Este programa es software libre: puedes redistribuirlo y modificarlo bajo los términos de la
**GNU General Public License** publicada por la Free Software Foundation, ya sea la versión 3 o
(a tu elección) cualquier versión posterior. Se distribuye **sin ninguna garantía**; consulta el
fichero [LICENSE](LICENSE) para más detalles.

Créditos de terceros:
- `data/oui.txt.gz` se deriva de los listados públicos de asignación de direcciones MAC del
  [IEEE Registration Authority](https://standards.ieee.org/products-services/regauth/). Los nombres
  de fabricante pertenecen a sus titulares; este fichero no está cubierto por el copyright del
  proyecto.
- Test de velocidad: protocolo y servidores [LibreSpeed](https://librespeed.org), alojados por
  Clouvider.
- La interfaz de la TUI se inspira en Turbo Vision de Borland.
