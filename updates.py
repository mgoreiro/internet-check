# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro
"""Comprobación de versiones nuevas en las releases de GitHub.

Solo consulta e informa: nunca descarga ni instala nada por su cuenta.
"""
import json
import os
import re
import urllib.request

import info

# «propietario/repositorio»; por defecto, el del proyecto (ver info.REPO)
REPO = os.environ.get("UPDATE_REPO") or info.REPO.rsplit("github.com/", 1)[-1]


def parse_version(text):
    """'1.5.2 (desarrollo)' / 'v1.6.0' -> (1, 5, 2). () si no hay números."""
    return tuple(int(n) for n in re.findall(r"\d+", (text or "").split(" ")[0])[:3])


def latest():
    """Última release publicada: {version, tag, url, deb, notes}. Lanza OSError/ValueError si falla."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"User-Agent": "internet-check", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.load(r)
    deb = next((a.get("browser_download_url") for a in data.get("assets", [])
                if str(a.get("name", "")).endswith(".deb")), None)
    tag = str(data.get("tag_name", ""))
    return {"version": tag.lstrip("v"), "tag": tag, "url": data.get("html_url", ""), "deb": deb,
            "notes": str(data.get("body") or "")}


def check():
    """Compara la versión instalada con la última release.

    Devuelve (info_de_la_release | None, hay_nueva, error | None)."""
    try:
        rel = latest()
    except Exception as e:  # noqa: BLE001 (red, JSON, límite de la API...)
        return None, False, str(e)
    installed = parse_version(info.version())
    newer = bool(parse_version(rel["version"])) and parse_version(rel["version"]) > installed
    return rel, newer, None


def _notes_excerpt(notes, limit=700):
    text = re.sub(r"\n{3,}", "\n\n", notes).strip()
    return text if len(text) <= limit else text[:limit].rsplit("\n", 1)[0] + "\n…"


def message(rel, newer=True):
    """Texto del aviso. Las notas vienen de GitHub y se envían como texto plano."""
    if not newer:
        return (f"✅ internet-check está al día: v{info.version()}\n"
                f"Última versión publicada: {rel['version']}")
    lines = [f"🆕 Hay una versión nueva de internet-check: {rel['version']} (instalada: {info.version()})",
             rel["url"], "", _notes_excerpt(rel["notes"])]
    if rel["deb"]:
        name = rel["deb"].rsplit("/", 1)[-1]
        lines += ["", "Para actualizar la Pi:", f"curl -LO {rel['deb']}", f"sudo apt install ./{name}"]
    return "\n".join(lines)
