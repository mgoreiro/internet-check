#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Instalador para OpenWrt. Se ejecuta en el router, con el paquete extraído en /etc/internet-check:
#   sh /etc/internet-check/install.sh          instalar o actualizar
#   sh /etc/internet-check/install.sh remove   desinstalar
DIR=/etc/internet-check
INIT=/etc/init.d/internet-check

if [ "$1" = "remove" ]; then
    [ -x "$INIT" ] && { "$INIT" stop; "$INIT" disable; }
    rm -f "$INIT"
    sed -i '\#^/etc/internet-check$#d' /etc/sysupgrade.conf 2>/dev/null
    echo "Servicio retirado. Para borrar también los ajustes: rm -rf $DIR"
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Falta Python 3. Instálalo con:"
    echo "    opkg update && opkg install python3-light python3-openssl ca-bundle"
    echo "(con apk en OpenWrt 25+:  apk add python3-light python3-openssl ca-bundle)"
    exit 1
fi
python3 -c 'import ssl, socket, json, threading, logging.handlers' 2>/dev/null || {
    echo "A Python le faltan módulos. Prueba: opkg install python3-openssl python3-logging  (o python3 completo)"; exit 1; }

# Comprobación de TLS y certificados contra Telegram
python3 - <<'PYEOF' || echo "AVISO: no se pudo abrir https://api.telegram.org desde Python (¿sin Internet o sin ca-bundle?). Revisa antes de seguir."
import sys, urllib.request as u
try:
    u.urlopen("https://api.telegram.org", timeout=15)
except u.HTTPError:
    pass
except Exception as e:
    sys.stderr.write("%s\n" % e)
    sys.exit(1)
PYEOF

chmod 755 "$DIR/monitor.py"
[ -f "$DIR/config.env" ] || cp "$DIR/config.env.example" "$DIR/config.env"
if [ ! -f "$DIR/bot.env" ]; then
    cp "$DIR/bot.env.example" "$DIR/bot.env"
    chmod 600 "$DIR/bot.env"
    NEW=1
fi

cp "$DIR/internet-check.init" "$INIT"
chmod 755 "$INIT"
# Conservar ajustes y servicio tras sysupgrade
touch /etc/sysupgrade.conf
grep -qx "$DIR" /etc/sysupgrade.conf || echo "$DIR" >> /etc/sysupgrade.conf

if [ -n "$NEW" ]; then
    echo "Edita el token y el chat id y vuelve a lanzar el instalador:"
    echo "    vi $DIR/bot.env"
    exit 0
fi
"$INIT" enable
"$INIT" restart
echo "Listo. Registro:  logread -e internet-check   (o  tail /tmp/internet-check.log)"
