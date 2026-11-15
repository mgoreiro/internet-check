#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro
#
# Comprueba si Telegram entrega a un bot los mensajes que envía OTRO bot en un grupo.
# De ello depende poder usar Telegram como canal de «latido» entre dos Pi.
#
# Preparación (una vez), con DOS bots de prueba creados en @BotFather:
#   1. En @BotFather: /mybots -> tu bot -> Bot Settings -> activa «Bot-to-Bot Communication Mode»
#      (en los dos bots).
#   2. Crea un grupo, añade a los dos bots y hazlos administradores. Para la prueba 2, en
#      @BotFather desactiva el «Group Privacy» del bot receptor.
#   3. Escribe algo en el grupo y averigua su id: https://api.telegram.org/bot<TOKEN>/getUpdates
#      (un grupo tiene un id negativo).
#   4. Para el bot RECEPTOR no puede haber otro programa leyendo sus mensajes a la vez (si es el
#      de la Pi, para antes el servicio).
#
# Uso (los tokens se pasan por variables de entorno, nunca como argumentos):
#   TOKEN_EMISOR=... TOKEN_RECEPTOR=... GRUPO=-100123456 USUARIO_RECEPTOR=mi_bot_receptor \
#       sh tools/prueba_bot_a_bot.sh
set -e
: "${TOKEN_EMISOR:?falta TOKEN_EMISOR}" "${TOKEN_RECEPTOR:?falta TOKEN_RECEPTOR}"
: "${GRUPO:?falta GRUPO}" "${USUARIO_RECEPTOR:?falta USUARIO_RECEPTOR (sin @)}"

enviar() { curl -s -m 20 -o /dev/null "https://api.telegram.org/bot$TOKEN_EMISOR/sendMessage" \
    --data-urlencode "chat_id=$GRUPO" --data-urlencode "text=$1"; }
recibido() {  # $1 = texto que se busca en lo que ha recibido el receptor
    curl -s -m 20 "https://api.telegram.org/bot$TOKEN_RECEPTOR/getUpdates?timeout=0" | python3 -c "
import json, sys
data = json.load(sys.stdin)
if not data.get('ok'):
    print('ERROR de la API:', data.get('description')); sys.exit(2)
hits = [u for u in data['result'] if '$1' in ((u.get('message') or {}).get('text') or '')]
print('RECIBIDO' if hits else 'NO recibido')
" 2>/dev/null || true
}

# Vacía lo pendiente del receptor
curl -s -m 20 "https://api.telegram.org/bot$TOKEN_RECEPTOR/getUpdates?offset=-1&timeout=0" >/dev/null

MARCA="prueba-$(date +%s)"
echo "Prueba 1: mensaje con una orden dirigida al receptor (/latido@$USUARIO_RECEPTOR)"
enviar "/latido@$USUARIO_RECEPTOR $MARCA-1"
sleep 4
echo "  -> $(recibido "$MARCA-1")"

echo "Prueba 2: mensaje de texto normal (necesita que el receptor sea administrador y sin Group Privacy)"
enviar "latido $MARCA-2"
sleep 4
echo "  -> $(recibido "$MARCA-2")"

echo
echo "Si la prueba 1 dice RECIBIDO, se puede construir el latido entre dos Pi solo con Telegram."
echo "Si las dos dicen NO recibido, Telegram no entrega mensajes entre bots a la API de bots: usa"
echo "HEARTBEAT_URL con un servicio externo (ver el README)."
