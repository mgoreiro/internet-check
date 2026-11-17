#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
# Arranque de internet-check en EdgeOS (no hay systemd). Uso: internet-check.sh start|stop|restart|status|log
# Lo lanza al arrancar /config/scripts/post-config.d/internet-check (lo crea install.sh).
DIR=/config/internet-check
PIDFILE=/var/run/internet-check.pid
LOG=/tmp/internet-check.log   # en RAM: no gasta flash

is_running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

# Bucle de vigilancia: si Python se cae, se vuelve a lanzar a los 5 s
supervise() {
    while true; do
        python "$DIR/monitor.py"
        sleep 5
    done
}

case "$1" in
start)
    is_running && { echo "ya está en marcha"; exit 0; }
    cd "$DIR" || exit 1
    export INTERNET_CHECK_DIR="$DIR"
    export PYTHONDONTWRITEBYTECODE=1      # no escribir .pyc en la flash
    ( supervise >/dev/null 2>&1 & echo $! > "$PIDFILE" )
    echo "internet-check en marcha"
    ;;
stop)
    if is_running; then
        pid=$(cat "$PIDFILE")
        kill "$pid" 2>/dev/null                   # el bucle supervisor
        pkill -f "$DIR/monitor.py" 2>/dev/null    # y Python
        rm -f "$PIDFILE"
        echo "parado"
    else
        pkill -f "$DIR/monitor.py" 2>/dev/null
        echo "no estaba en marcha"
    fi
    ;;
restart)
    "$0" stop; sleep 1; "$0" start
    ;;
status)
    if is_running; then echo "en marcha (pid $(cat "$PIDFILE"))"; else echo "parado"; exit 1; fi
    ;;
log)
    tail -n "${2:-40}" "$LOG"
    ;;
*)
    echo "uso: $0 start|stop|restart|status|log [líneas]"; exit 2
    ;;
esac
