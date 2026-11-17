#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
# Genera internet-check-edgerouter_<version>.tar.gz (en macOS o Linux).
#   ./build.sh [version]        sin fabricantes
#   ./build.sh [version] --oui  incluye data/oui.txt.gz (475 kB) para mostrar el fabricante de cada MAC
set -e
cd "$(dirname "$0")"
VERSION="${1:-1.0.0}"
OUT="internet-check-edgerouter_${VERSION}.tar.gz"
B="$(mktemp -d)"; trap 'rm -rf "$B"' EXIT
export COPYFILE_DISABLE=1

R="$B/internet-check"
mkdir "$R"
cp common.py state.py lan.py metrics.py watch.py quiet.py heartbeat.py reports.py jobs.py info.py bot.py monitor.py \
   internet-check.sh install.sh config.env.example bot.env.example README.md "$R/"
cp ../LICENSE "$R/LICENSE"
printf '%s\n' "$VERSION" > "$R/VERSION"
[ "$2" = "--oui" ] && cp ../data/oui.txt.gz "$R/oui.txt.gz"
chmod 755 "$R/internet-check.sh" "$R/install.sh" "$R/monitor.py"

rm -f "$OUT"
tar --format ustar --uid 0 --gid 0 --numeric-owner -C "$B" -czf "$OUT" internet-check
echo "Generado $OUT"
