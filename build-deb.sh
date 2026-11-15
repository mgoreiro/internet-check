#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
# Genera internet-check_<version>_all.deb (funciona en macOS y Linux, sin dpkg-deb)
set -e
cd "$(dirname "$0")"
VERSION="${1:-1.4.1}"
OUT="internet-check_${VERSION}_all.deb"
B="$(mktemp -d)"; trap 'rm -rf "$B"' EXIT
export COPYFILE_DISABLE=1

R="$B/root"
install -d -m 755 "$R/usr/bin" "$R/usr/lib/internet-check" "$R/lib/systemd/system" "$R/usr/share/internet-check" "$R/usr/share/doc/internet-check"
for f in common.py db.py lan.py reports.py jobs.py bot.py monitor.py tui.py; do
    install -m 755 "$f" "$R/usr/lib/internet-check/$f"
done
install -m 755 internet-check-tui "$R/usr/bin/internet-check-tui"
install -m 644 internet-check.service "$R/lib/systemd/system/internet-check.service"
install -m 644 config.env.example bot.env.example data/oui.txt.gz "$R/usr/share/internet-check/"
install -m 644 README.md CHANGELOG.md LICENSE docs/arquitectura.md "$R/usr/share/doc/internet-check/"
install -m 644 packaging/copyright "$R/usr/share/doc/internet-check/copyright"

C="$B/control"; mkdir "$C"
sed "s/@VERSION@/$VERSION/" packaging/DEBIAN/control.in > "$C/control"
cp packaging/DEBIAN/postinst packaging/DEBIAN/prerm packaging/DEBIAN/postrm "$C/"
chmod 755 "$C/postinst" "$C/prerm" "$C/postrm"

TAROPT="--format ustar --uid 0 --gid 0 --numeric-owner"
tar $TAROPT -C "$C" -czf "$B/control.tar.gz" .
tar $TAROPT -C "$R" -czf "$B/data.tar.gz" .
printf '2.0\n' > "$B/debian-binary"
rm -f "$OUT"
( cd "$B" && ar rcS "$OLDPWD/$OUT" debian-binary control.tar.gz data.tar.gz )
echo "Generado $OUT"
