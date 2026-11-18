#!/usr/bin/env bash
# Lanza la TUI con la base de datos ficticia creada por docs/demo-seed.py (sin red ni datos reales)
D=/tmp/internet-check-demo
export DB_FILE=$D/data.db STATE_FILE=$D/state.json DEVICE_NAME=orangepi
export INTERNET_CHECK_CONFIG=/dev/null INTERNET_CHECK_BOT_CONFIG=/dev/null TELEGRAM_TOKEN=123456:demo TELEGRAM_CHAT_ID=1
exec python3 "$(cd "$(dirname "$0")/.." && pwd)/tui.py" "$@"
