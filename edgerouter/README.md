# internet-check · edición EdgeRouter (Python 2.7)

Port reducido de `internet-check` para routers **EdgeRouter (ER-X)** con EdgeOS, que solo traen
Python 2.7. El código también funciona en Python 3, así que se puede probar en cualquier equipo.

> Autor: **Miguel González Oreiro** · Licencia: GPL-3.0-or-later

## Qué incluye y qué no

**Incluye:** aviso de caída y recuperación (con duración), estado, IP pública y aviso de cambio,
test de velocidad manual, dispositivos de la red (tabla ARP del router), aviso de dispositivos
nuevos, presencia, calidad (latencia, jitter, pérdida, DNS), salud (carga, memoria, flash),
vigilancia de servicios, latido de alarma, modo no molestar, Wake-on-LAN, reinicio remoto y
usuarios con roles (administradores y solo consulta).

**Quitado a propósito** (necesitaba disco): base de datos SQLite, histórico de velocidad,
gráficas, informes diarios y semanales, exportación a CSV, nombres de dispositivos (`/nombrar`),
detección de apagones frente a reinicios y la TUI.

Todo el estado vive **en memoria**: no se escribe nada en la flash durante el funcionamiento.
Al reiniciar el servicio o el router se pierden el historial de caídas y las medidas de calidad.
El log va a `/tmp` (RAM).

## Instalación

En el Mac:

```bash
cd edgerouter
./build.sh 1.0.0            # añade --oui para ver el fabricante de cada MAC (+475 kB)
scp internet-check-edgerouter_1.0.0.tar.gz ubnt@192.168.1.1:/tmp/
```

En el router:

```bash
sudo tar -C /config -xzf /tmp/internet-check-edgerouter_1.0.0.tar.gz
sudo sh /config/internet-check/install.sh     # crea bot.env y config.env y se detiene
sudo vi /config/internet-check/bot.env        # token y chat id
sudo sh /config/internet-check/install.sh     # arranca y deja el arranque automático
sudo sh /config/internet-check/internet-check.sh log
```

El instalador crea `/config/scripts/post-config.d/internet-check`, que EdgeOS ejecuta en cada
arranque y conserva al actualizar el firmware. Para desinstalar: `sudo sh /config/internet-check/install.sh remove`.

## Ajustes

`/config/internet-check/config.env` (ver `config.env.example`). Importante: define `LAN_CIDR` si tu LAN
no es `192.168.1.0/24`, porque en un router la ruta por defecto es la WAN y la LAN no se deduce sola.

## Limitaciones conocidas

- **Test de velocidad:** el TLS de Python 2 en la CPU MIPS del ER-X limita la medida a unos 50–100 Mbps.
  Si tu línea es más rápida, la cifra será más baja que la real.
- **Disponibilidad:** se calcula desde el arranque del servicio, no sobre un histórico.
- **Aviso de arranque:** si el router lleva menos de 15 min encendido al arrancar el servicio, avisa de que
  se ha (re)iniciado; no puede distinguir un apagón de un reinicio pedido por el bot.
- **Memoria:** el ER-X tiene 256 MB. El servicio ocupa pocas decenas de MB; el escaneo de red y el test de
  velocidad son los momentos de mayor consumo.
