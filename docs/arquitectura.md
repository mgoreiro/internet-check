# Arquitectura

Documento técnico de `internet-check`. Para instalación y uso, ver el [README](../README.md).

> Copyright © 2026 Miguel González Oreiro <mgoreiro@gmail.com> — GPL-3.0-or-later

## Visión general

Un único proceso (`monitor.py`, servicio systemd) ejecuta varios hilos que comparten la base de
datos SQLite. La TUI es un proceso aparte que lee la misma configuración y la misma base.

```
                 ┌───────────────────────── monitor.py (servicio) ─────────────────────────┐
  Internet  ◄──► │ hilo principal: detección de caídas, latido, avisos de recuperación     │
  Telegram  ◄──► │ hilo bot.run_bot: long polling de getUpdates, un hilo por acción        │
                 │ hilos jobs: test programado · cambio de IP · dispositivos nuevos        │
                 └──────────────┬──────────────────────────────────────────────────────────┘
                                │ db.py (SQLite, una conexión por operación)
  tui.py (proceso aparte) ──────┘
```

## Módulos

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `common.py` | Carga de configuración, comprobación de conexión, API de Telegram, IP pública, test de velocidad | stdlib |
| `db.py` | Esquema y consultas SQLite | stdlib |
| `metrics.py` | Ráfagas de latencia/pérdida, comprobación de DNS y lectura de salud del sistema | `common`, `db` |
| `lan.py` | Escaneo ARP, fabricantes (OUI), NetBIOS, Wake-on-LAN | stdlib |
| `info.py` | Ayuda y «acerca de»; la versión sale de `_version.py` (generado por `build-deb.sh`) o, en desarrollo, del `CHANGELOG.md` | `common` |
| `charts.py` | Gráficas PNG: lienzo RGB, fuente de bitmap 5×7 y codificador PNG con `zlib` | `common`, `db` |
| `export.py` | Exportación del histórico a CSV dentro de un zip | `common`, `db` |
| `updates.py` | Búsqueda de versiones nuevas en las releases de GitHub | `info` |
| `watch.py` | Vigilancia de equipos y servicios propios (TCP, ping, HTTP) | `common`, `db` |
| `quiet.py` | Modo no molestar: retiene los avisos poco urgentes y los entrega en un resumen | `common`, `db` |
| `heartbeat.py` | Latido periódico a un servicio externo (alarma de caída) | `common` |
| `reports.py` | Textos de estado, caídas, velocidad, dispositivos, calidad, salud e informes | `common`, `db`, `lan`, `metrics` |
| `jobs.py` | Bucles periódicos y sus avisos | `common`, `db`, `lan`, `metrics`, `reports` |
| `bot.py` | Menú, acciones, confirmación de reinicio | `common`, `db`, `lan`, `reports` |
| `monitor.py` | Punto de entrada del servicio | todos los anteriores |
| `tui.py` | Interfaz curses | `common`, `reports` |

## Detección de caídas

1. Cada `CHECK_INTERVAL` s se abre una conexión TCP a los destinos de `CHECK_HOSTS`; basta que uno
   responda para considerar que hay Internet.
2. Tras `FAIL_THRESHOLD` fallos seguidos se marca la caída (`down_since = ahora − fallos·intervalo`)
   y se abre una fila en `outages`.
3. Al volver, se cierra la fila y se envía el aviso. Si Telegram no responde, se reintenta cada
   15 s hasta enviarlo.
4. Mientras corre un test de velocidad (`common.SPEED_BUSY`) los fallos no se cuentan, porque la
   línea saturada podría provocar una falsa caída.

### Latido y arranque
Cada ciclo se escribe `state.json` con `last_alive` y `down_since`. Al arrancar:

- Si hay un `reboot_requested` reciente en la base: reinicio solicitado desde Telegram
  (`outages.kind = 'reboot'`) y aviso «ha vuelto tras el reinicio».
- Si no, y el último latido es más antiguo que `CHECK_INTERVAL·(FAIL_THRESHOLD+2)` y la parada no
  fue limpia: apagón (`kind = 'power'`).
- Una parada limpia (SIGTERM, por `apt` o `systemctl stop`) deja `clean = true` y no genera aviso.

## Bot

- **Long polling** de `getUpdates` (30 s). Al arrancar se descartan las actualizaciones pendientes
  (`offset = -1`), de modo que un botón pulsado mientras el servicio estaba parado no se ejecuta
  después, y una confirmación de reinicio no puede provocar un bucle de reinicios.
- **Autorización:** se compara el chat de cada mensaje o callback con `TELEGRAM_CHAT_ID`.
- **Acciones:** cada una corre en su propio hilo para no bloquear el polling. El test de velocidad
  usa un `Lock` compartido con la tarea programada: solo hay uno a la vez.
- **Reinicio:** `reboot` guarda la hora de la petición; `reboot_yes` solo se acepta durante
  60 s. Antes de ejecutar `systemctl reboot` se anota `reboot_requested` en la base.

## Test de velocidad

Protocolo de un backend [LibreSpeed](https://librespeed.org):

| Fase | Petición |
|---|---|
| Latencia | Mediana de 5 conexiones TCP al puerto del servidor |
| Bajada | `GET {base}/garbage.php?ckSize=100`, en `SPEEDTEST_STREAMS` hilos durante `SPEEDTEST_SECONDS` |
| Subida | `POST {base}/empty.php` con bloques de 2 MiB, en paralelo |

Se prueban los servidores de `SPEEDTEST_SERVERS` por orden. Ante un rechazo HTTP (429, 403…) el
hilo **se detiene** en lugar de reintentar, para no agravar un bloqueo por exceso de peticiones.

## Calidad de la conexión

Cada `QUALITY_INTERVAL` s (60 por defecto) se mide una **ráfaga**: `QUALITY_PROBES` conexiones TCP
a un destino de `CHECK_HOSTS`, separadas 0,25 s. Una conexión sin respuesta en 1 s cuenta como
perdida. Se guardan latencia media y máxima, jitter (desviación típica) y % de pérdida, junto con
el tiempo que tarda el resolutor del sistema en resolver un nombre.

- **Aviso de degradación:** tras `QUALITY_ALERT_BURSTS` ráfagas seguidas con pérdida o latencia por
  encima del umbral; otro aviso al volver a la normalidad. Las ráfagas con 100 % de pérdida se
  ignoran, porque son un corte y lo gestiona el monitor.
- **Aviso de DNS:** mismo criterio de ráfagas seguidas cuando hay conexión pero el DNS no resuelve.
  Un resolutor con caché puede ocultar un fallo hasta que caduquen las entradas.
- Durante un test de velocidad no se mide (`SPEED_BUSY`), para no falsear la latencia.

## Salud del sistema

Cada `HEALTH_MINUTES` min se lee la temperatura (`/sys/class/thermal`, prefiriendo la zona
`cpu*`), la carga, la memoria usada (`MemAvailable` de `/proc/meminfo`), el disco y el tamaño de la
base de datos. Cada umbral avisa una vez al superarse y otra al normalizarse (con un margen para
evitar rebotes). En cada lectura se borran las medidas de calidad y salud más antiguas que
`RETENTION_DAYS`; las caídas y los tests de velocidad se conservan siempre.

## Informes

`reports.period_report_text(horas)` resume un periodo (acotado al inicio de la monitorización)
a partir de la base de datos. `jobs.report_tick` lo envía a `REPORT_DAILY_TIME` (semanal el día
`REPORT_WEEKLY_DAY`) y recuerda en `kv.report_last` el día enviado, de modo que no se repite y se
recupera si la Pi estaba apagada a esa hora. No se envía antes de una hora de monitorización.

## Usuarios y permisos

`common.py` clasifica cada chat de Telegram con `role_of(chat)`: **administrador**
(`TELEGRAM_CHAT_ID` y `TELEGRAM_ADMINS`), **espectador** (`TELEGRAM_VIEWERS`) o desconocido, que se
ignora. Las acciones de administración (`ADMIN_ONLY` en `bot.py`: reinicio, Wake-on-LAN y su
confirmación) se rechazan para los espectadores y, además, cada una vuelve a comprobar el rol
(`_require_admin`).

Cada petición se atiende en su hilo con un **contexto** (`set_context(chat, rol)`, por hilo) del que
`send_telegram`, `send_photo` y `send_document` toman el destinatario: **siempre se responde al chat
que preguntó**. Las tareas del servicio no tienen contexto y escriben al administrador principal;
con `broadcast=True` y `TELEGRAM_NOTIFY_VIEWERS=1` copian el aviso a todos. El teclado del menú se
construye según el rol, de modo que los espectadores no ven los botones de administración.

## Gráficas

`charts.py` dibuja sin dependencias: un `Canvas` RGB (`bytearray`), una fuente de bitmap 5×7
(mayúsculas sin acentos, dígitos y signos), rectas con el algoritmo de Bresenham y un codificador
PNG (firma, `IHDR`, `IDAT` comprimido con `zlib` y `IEND`, con su CRC). `draw_chart` calcula marcas
«redondas» (1, 2, 5 × 10ⁿ), rejilla, leyenda y escala temporal, y **corta la línea** donde faltan
datos. Las series largas se reducen por tramos (`downsample`). El PNG sale en unos 20 ms.

## Exportación

`export.build_zip` genera `caidas.csv`, `velocidad.csv`, `calidad.csv`, `salud.csv` y un `LEEME.txt`
dentro de un zip. Los CSV llevan BOM UTF-8 y, junto a la fecha local, la hora en segundos Unix
(`epoch`) para análisis sin ambigüedad de zona horaria. La subida a Telegram usa
`multipart/form-data` construido a mano (`common.tg_upload`).

## Versiones nuevas

`updates.check` consulta `releases/latest` de la API de GitHub (petición anónima de lectura) y
compara versiones como tuplas numéricas (1.10.0 > 1.9.9). `jobs.update_tick` avisa **una sola vez**
por versión (`kv.update_notified`). Las notas de la release son texto externo: se recortan y se
envían como texto plano. Nunca se descarga ni se instala nada automáticamente.

## Vigilancia de servicios

`watch.parse_targets` convierte `WATCH_TARGETS` en destinos TCP, `ping://` o HTTP. `watch.run_once`
los comprueba en paralelo (hasta 8 hilos) y `watch.evaluate` cuenta los fallos seguidos de cada uno:
al llegar a `WATCH_FAILS` abre una fila en `service_outages` y avisa; al volver a responder la cierra
y avisa con la duración. Sobrevive a un reinicio porque el estado «caído» sale de la base de datos,
y no duplica avisos. Los destinos que no son de la red local (`is_local`) se omiten mientras el
monitor no ve Internet, para no atribuir al servicio un corte propio. Estos avisos se envían con
`c.send_telegram` directamente, sin pasar por el modo no molestar.

## Nombres y presencia

La tabla `devices` guarda `alias` (nombre del usuario), `watch` (1 = avisar de llegadas y salidas),
`present` y `misses`; las columnas se **migran al abrir la base**, así que una base anterior sigue
funcionando. Tras cada escaneo, `db.presence_update` pone `misses` a cero en los dispositivos vistos y
suma uno en los demás; solo al llegar a `PRESENCE_MISSES` un dispositivo pasa a ausente, y solo los
vigilados generan aviso, una vez por cambio de estado.

## Modo no molestar

`quiet.is_quiet` combina el horario fijo (`QUIET_HOURS`, con ventanas que cruzan la medianoche) y el
modo manual (`kv.dnd_until`). `quiet.notify` es el punto de salida de los avisos **poco urgentes**: en
modo no molestar los guarda en la tabla `held` y `quiet.flush`, que corre cada minuto, los entrega
juntos cuando termina. Quedan fuera, y se envían siempre, las caídas de Internet, los reinicios y las
caídas de servicios vigilados. El informe programado y el aviso de versión nueva no se retienen:
esperan a que termine.

## Latido

`heartbeat.tick` hace una petición GET a `HEARTBEAT_URL` cada `HEARTBEAT_SECONDS`. Es el único modo de
tener una alarma **durante** la caída, porque con Internet cortado la Pi no puede escribir a Telegram:
el servicio externo es quien cuenta el tiempo sin latidos y avisa. La URL lleva un código secreto, así
que los logs solo mencionan el nombre del servidor y el tipo de error, y solo en el primer fallo de
cada racha.

## Escaneo de la red

1. Un intento de conexión TCP al puerto 80 de cada dirección de la red (64 hilos). No importa que
   falle: basta para que el núcleo resuelva la MAC por ARP.
2. Se lee `/proc/net/arp` y se descartan entradas incompletas (`flags = 0x0`).
3. En paralelo se resuelve el nombre DNS inverso y se consulta NetBIOS (`NBSTAT`, UDP 137).
4. Fabricante: se lee `oui.txt.gz` en una pasada, buscando solo los prefijos necesarios
   (9, 7 y 6 dígitos hexadecimales, el más largo gana). No se carga el fichero entero en memoria.

## Datos

Base SQLite en `/var/lib/internet-check/data.db`:

| Tabla | Columnas principales |
|---|---|
| `outages` | `start`, `end` (NULL = en curso), `kind` (`internet` · `power` · `reboot`) |
| `speedtests` | `ts`, `down`, `up`, `ping`, `source` (`auto` · `bot` · `tui`) |
| `devices` | `mac` (clave), `ip`, `hostname`, `first_seen`, `last_seen`, `alias`, `watch`, `present`, `misses` |
| `service_outages` | `name`, `start`, `end` (NULL = caído ahora) |
| `held` | `ts`, `text`, `broadcast`: avisos retenidos por el modo no molestar |
| `quality` | `ts`, `rtt_avg`, `rtt_max`, `jitter`, `loss`, `dns_ms`, `dns_ok` |
| `health` | `ts`, `temp`, `load`, `mem_pct`, `disk_pct`, `db_kb` |
| `kv` | `installed_at`, `public_ip`, `lan_baseline`, `reboot_requested`, `report_last`, `update_notified` |

Cada operación abre y cierra su conexión, lo que la hace segura entre hilos y entre procesos
(servicio y TUI).

## Empaquetado

`build-deb.sh` construye el `.deb` con `tar` y `ar`, sin `dpkg-deb`, por lo que funciona en macOS.
Los `tar` usan formato `ustar` (los PAX de macOS no los acepta `dpkg`).

Las configuraciones **no son *conffiles***: el `postinst` las crea desde las plantillas de
`/usr/share/internet-check/` solo si no existen. Así una actualización nunca pregunta ni pisa
los ajustes del usuario. El `postinst` también migra credenciales antiguas de `config.env` a
`bot.env` y arranca el servicio solo si hay un token real.
