# Arquitectura

Documento técnico de `internet-check`. Para instalación y uso, ver el [README](../README.md).

> Copyright © 2026 mgoreiro <mgoreiro@gmail.com> — GPL-3.0-or-later

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
| `lan.py` | Escaneo ARP, fabricantes (OUI), NetBIOS, Wake-on-LAN | stdlib |
| `reports.py` | Textos de estado, historial de caídas, histórico de velocidad y dispositivos | `common`, `db`, `lan` |
| `jobs.py` | Bucles periódicos | `common`, `db`, `lan`, `reports` |
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
| `devices` | `mac` (clave), `ip`, `hostname`, `first_seen`, `last_seen` |
| `kv` | `installed_at`, `public_ip`, `lan_baseline`, `reboot_requested` |

Cada operación abre y cierra su conexión, lo que la hace segura entre hilos y entre procesos
(servicio y TUI).

## Empaquetado

`build-deb.sh` construye el `.deb` con `tar` y `ar`, sin `dpkg-deb`, por lo que funciona en macOS.
Los `tar` usan formato `ustar` (los PAX de macOS no los acepta `dpkg`).

Las configuraciones **no son *conffiles***: el `postinst` las crea desde las plantillas de
`/usr/share/internet-check/` solo si no existen. Así una actualización nunca pregunta ni pisa
los ajustes del usuario. El `postinst` también migra credenciales antiguas de `config.env` a
`bot.env` y arranca el servicio solo si hay un token real.
