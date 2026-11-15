#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mgoreiro <mgoreiro@gmail.com>
"""Genera data/oui.txt.gz (prefijo MAC -> fabricante) a partir de los CSV del IEEE.

Uso: python3 -I tools/build_oui.py <carpeta con oui.csv, mam.csv y oui36.csv> [salida.gz]

Descarga de los CSV:
  https://standards-oui.ieee.org/oui/oui.csv        (MA-L, 24 bits)
  https://standards-oui.ieee.org/oui28/mam.csv      (MA-M, 28 bits)
  https://standards-oui.ieee.org/oui36/oui36.csv    (MA-S, 36 bits)
"""
import csv
import gzip
import os
import re
import sys

# Sufijos legales/genéricos que no ayudan a reconocer al fabricante
SUFFIX = re.compile(
    r"[,\s]+(inc|incorporated|ltd|limited|llc|l\.l\.c|gmbh|co|corp|corporation|company|s\.?a|s\.?l|b\.?v|ag|plc|"
    r"pte|oy|ab|a/s|s\.?p\.?a|kg|nv|srl|sdn|bhd|pty|k\.?k|technologies|technology|electronics|electronic|"
    r"international|intl|holdings?|group|industries|industrial|systems|communications?|enterprises?|"
    r"ind|mfg|manufacturing|corporate|computer|computers|and|&)\.?$", re.I)


def short(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip().strip(",")
    while True:
        new = SUFFIX.sub("", name).strip().strip(",")
        if new == name or not new:
            break
        name = new
    return name


def main(src, out):
    entries = {}
    for fname, length in (("oui.csv", 6), ("mam.csv", 7), ("oui36.csv", 9)):
        path = os.path.join(src, fname)
        if not os.path.exists(path):
            print(f"aviso: falta {fname}", file=sys.stderr)
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                prefix = row["Assignment"].strip().upper()
                name = short(row["Organization Name"])
                if len(prefix) == length and name and name.lower() != "private":
                    entries[prefix] = name
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as f:
        for prefix in sorted(entries):
            f.write(f"{prefix}\t{entries[prefix]}\n")
    print(f"{len(entries)} fabricantes -> {out} ({os.path.getsize(out) // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/oui.txt.gz")
