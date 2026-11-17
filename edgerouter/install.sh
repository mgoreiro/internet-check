#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
# Instalador para EdgeRouter. Se ejecuta en el router, ya extraído el paquete en /config/internet-check:
#   sudo sh /config/internet-check/install.sh          instalar o actualizar
#   sudo sh /config/internet-check/install.sh remove   desinstalar
DIR=/config/internet-check
HOOK=/config/scripts/post-config.d/internet-check

if [ "$(id -u)" != "0" ]; then echo "Ejecútalo con sudo."; exit 1; fi

if [ "$1" = "remove" ]; then
    sh "$DIR/internet-check.sh" stop
    rm -f "$HOOK"
    echo "Servicio retirado. Para borrar también los ajustes: rm -rf $DIR"
    exit 0
fi

command -v python >/dev/null 2>&1 || { echo "No encuentro 'python' (se necesita 2.7)."; exit 1; }
python -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (2, 7) else 1)' || { echo "Se necesita Python 2.7 o superior."; exit 1; }
python -c 'import ssl, socket, json, threading' || { echo "A Python le faltan módulos (ssl, socket, json o threading)."; exit 1; }

# Python 2.7.9+ verifica los certificados: hace falta un bundle de CA y TLS 1.2 para hablar con Telegram
python - <<'PYEOF' || echo "AVISO: no se pudo abrir https://api.telegram.org desde Python (¿sin Internet, sin certificados de CA o TLS antiguo?). Revisa antes de seguir."
import sys
try:
    import urllib2 as u
except ImportError:
    import urllib.request as u
try:
    u.urlopen("https://api.telegram.org", timeout=15)
except u.HTTPError:
    pass  # el servidor contestó (404): TLS y certificados funcionan
except Exception as e:
    sys.stderr.write("%s\n" % e)
    sys.exit(1)
PYEOF

chmod 755 "$DIR/internet-check.sh" "$DIR/monitor.py"
[ -f "$DIR/config.env" ] || cp "$DIR/config.env.example" "$DIR/config.env"
if [ ! -f "$DIR/bot.env" ]; then
    cp "$DIR/bot.env.example" "$DIR/bot.env"
    chmod 600 "$DIR/bot.env"
    NEW=1
fi

# Sobrevive a los reinicios y a las actualizaciones de firmware: EdgeOS ejecuta todo lo de post-config.d
mkdir -p /config/scripts/post-config.d
cat > "$HOOK" <<EOF
#!/bin/sh
$DIR/internet-check.sh start
EOF
chmod 755 "$HOOK"

if [ -n "$NEW" ]; then
    echo "Edita el token y el chat id y vuelve a lanzar el instalador:"
    echo "    vi $DIR/bot.env"
    exit 0
fi
sh "$DIR/internet-check.sh" restart
echo "Listo. Registro:  sh $DIR/internet-check.sh log"
