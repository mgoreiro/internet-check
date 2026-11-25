# internet-check · edición OpenWrt (Python 3)

Port de la edición EdgeRouter para un **ER-X (u otro router) con OpenWrt**. Mismas funciones que
`../edgerouter` (aviso de caída y recuperación, IP pública, dispositivos, calidad, salud, vigilancia,
presencia, Wake-on-LAN, reinicio remoto, roles). Todo el estado vive en memoria; el log va a `/tmp`.

> Licencia: GPL-3.0-or-later
> Estado: **sin probar en hardware real**. Si algo falla, abre una incidencia con el log.

## Diferencias con la edición EdgeRouter

- Necesita Python 3: `opkg update && opkg install python3-light python3-openssl ca-bundle`
  (con `apk` en OpenWrt 25+: `apk add ...`). Ocupa unos 10-15 MB de flash.
- Servicio `procd` (`/etc/init.d/internet-check`) en vez de `post-config.d`; procd relanza el proceso si cae.
- Ajustes en `/etc/internet-check`, que el instalador añade a `/etc/sysupgrade.conf` para conservarlos al actualizar.
- El espacio de «flash» se mide sobre `/overlay`.

## Instalación

En el Mac:

```bash
cd openwrt
./build.sh 1.0.0
scp -O internet-check-openwrt_1.0.0.tar.gz root@192.168.1.1:/tmp/
```

En el router:

```bash
tar -C /etc -xzf /tmp/internet-check-openwrt_1.0.0.tar.gz
sh /etc/internet-check/install.sh     # crea bot.env y config.env y se detiene
vi /etc/internet-check/bot.env        # token y chat id
sh /etc/internet-check/install.sh     # arranca y activa el servicio
logread -e internet-check             # o: tail /tmp/internet-check.log
```

Control: `/etc/init.d/internet-check start|stop|restart|status`. Desinstalar: `sh /etc/internet-check/install.sh remove`.

## Ajustes

`/etc/internet-check/config.env` (ver `config.env.example`). Define `LAN_CIDR` (normalmente la de `br-lan`)
porque en un router la ruta por defecto es la WAN.

## Limitaciones

Las mismas que en EdgeRouter (disponibilidad desde el arranque del servicio, 256 MB de RAM, velocidad del
test limitada por la CPU MIPS). Python 3 con OpenSSL actual debería medir algo más rápido que Python 2.
