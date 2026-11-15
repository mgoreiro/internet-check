# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Escaneo de la red local (sin root ni nmap) y Wake-on-LAN."""
import concurrent.futures as cf
import gzip
import ipaddress
import os
import re
import socket
import struct
import time

MAC_RE = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # no envía nada; solo elige la interfaz
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def lan_network():
    cidr = os.environ.get("LAN_CIDR")
    if cidr:
        return ipaddress.ip_network(cidr, strict=False)
    ip = local_ip()
    return ipaddress.ip_network(ip + "/24", strict=False) if ip else None


def _touch(ip):
    """Un intento de conexión basta para que el kernel resuelva la MAC por ARP."""
    try:
        socket.create_connection((ip, 80), timeout=0.4).close()
    except OSError:
        pass


def read_arp(net, path="/proc/net/arp"):
    devices = []
    try:
        with open(path) as f:
            lines = f.read().splitlines()[1:]
    except OSError:
        return devices
    for line in lines:
        p = line.split()
        if len(p) < 4:
            continue
        ip, flags, mac = p[0], p[2], p[3].lower()
        if flags == "0x0" or mac == "00:00:00:00:00:00":
            continue
        try:
            if ipaddress.ip_address(ip) in net:
                devices.append({"ip": ip, "mac": mac, "hostname": None})
        except ValueError:
            continue
    return devices


def _name(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return None


# ---- fabricante por MAC (base IEEE, ver tools/build_oui.py) ----

OUI_PATHS = [
    os.environ.get("OUI_FILE", ""),
    "/usr/share/internet-check/oui.txt.gz",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "oui.txt.gz"),
]
PRIVATE_MAC = "MAC privada (aleatoria)"


def _oui_file():
    for path in OUI_PATHS:
        if path and os.path.exists(path):
            return path
    return None


def vendors(macs):
    """{mac: fabricante} para una lista de MAC. Lee el fichero una vez, sin cargarlo entero."""
    result, wanted = {}, {}
    for mac in macs:
        hexa = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
        if len(hexa) != 12:
            continue
        if int(hexa[:2], 16) & 0x02:  # bit "administrada localmente": MAC aleatoria de móviles, etc.
            result[mac] = PRIVATE_MAC
            continue
        for n in (9, 7, 6):  # del prefijo más específico al más general
            wanted.setdefault(hexa[:n], set()).add(mac)
    path = _oui_file()
    if not wanted or not path:
        return result
    found = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                prefix, _, name = line.rstrip("\n").partition("\t")
                if prefix in wanted:
                    found[prefix] = name
    except (OSError, EOFError):
        return result
    for prefix in sorted(found, key=len, reverse=True):  # el más largo gana
        for mac in wanted[prefix]:
            result.setdefault(mac, found[prefix])
    return result


# ---- nombre NetBIOS (consulta NBSTAT por UDP 137) ----

def _nbstat_query():
    # Pregunta por el nombre comodín "*" (codificado en nivel 1 como "CK" + 30 "A")
    return (struct.pack(">HHHHHH", 0x1A2B, 0, 1, 0, 0, 0) + b"\x20" + b"CK" + b"A" * 30 + b"\x00"
            + struct.pack(">HH", 0x0021, 0x0001))


def _skip_name(data, off):
    while True:
        length = data[off]
        if length == 0:
            return off + 1
        if length & 0xC0 == 0xC0:  # puntero de compresión
            return off + 2
        off += length + 1


def parse_nbstat(data):
    """Extrae el nombre de equipo de una respuesta NBSTAT, o None."""
    try:
        qd, an = struct.unpack(">HH", data[4:8])
        if an < 1:
            return None
        off = 12
        for _ in range(qd):
            off = _skip_name(data, off) + 4
        off = _skip_name(data, off) + 10  # tipo, clase, ttl, longitud
        names = []
        for _ in range(data[off]):
            base = off + 1 + len(names) * 18
            name = data[base:base + 15].decode("ascii", "replace").strip(" \x00")
            suffix = data[base + 15]
            flags = struct.unpack(">H", data[base + 16:base + 18])[0]
            names.append((name, suffix, flags))
        for want in (0x00, 0x20):  # estación de trabajo, servidor de archivos
            for name, suffix, flags in names:
                if suffix == want and not flags & 0x8000 and name:  # 0x8000 = nombre de grupo
                    return name
    except (IndexError, struct.error):
        pass
    return None


def netbios_name(ip, timeout=1.0, port=137):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(_nbstat_query(), (ip, port))
        data, _ = s.recvfrom(1024)
    except OSError:
        return None
    finally:
        s.close()
    return parse_nbstat(data)


def scan(net=None):
    """Devuelve la lista de dispositivos {ip, mac, hostname, netbios, vendor} o None si no hay red."""
    net = net or lan_network()
    if net is None:
        return None
    if net.num_addresses > 1024:
        raise ValueError(f"red demasiado grande para escanear: {net}")
    with cf.ThreadPoolExecutor(64) as ex:
        list(ex.map(_touch, [str(h) for h in net.hosts()]))
    time.sleep(0.5)
    devices = read_arp(net)
    ex = cf.ThreadPoolExecutor(32)
    dns = {d["ip"]: ex.submit(_name, d["ip"]) for d in devices}
    nbt = {d["ip"]: ex.submit(netbios_name, d["ip"]) for d in devices}
    cf.wait(list(dns.values()) + list(nbt.values()), timeout=4)
    vend = vendors([d["mac"] for d in devices])
    for d in devices:
        d["hostname"] = dns[d["ip"]].result() if dns[d["ip"]].done() else None
        d["netbios"] = nbt[d["ip"]].result() if nbt[d["ip"]].done() else None
        d["vendor"] = vend.get(d["mac"])
    ex.shutdown(wait=False)
    devices.sort(key=lambda d: ipaddress.ip_address(d["ip"]))
    return devices


def describe(d, new=False):
    """Texto de un dispositivo en dos líneas: IP · fabricante / MAC · nombres."""
    first = f"• {d['ip']} · {d.get('vendor') or 'fabricante desconocido'}{' 🆕' if new else ''}"
    names = []
    if d.get("netbios"):
        names.append(f"NetBIOS: {d['netbios']}")
    host = d.get("hostname")
    if host and host.split(".")[0].lower() != (d.get("netbios") or "").lower():
        names.append(f"DNS: {host}")
    return first + "\n   " + " · ".join([d["mac"]] + names)


# ---- Wake-on-LAN ----

def wol_devices():
    """Lee WOL_DEVICES="Nombre=AA:BB:CC:DD:EE:FF,Otro=..." -> [(nombre, mac)]."""
    out = []
    for item in os.environ.get("WOL_DEVICES", "").split(","):
        name, _, mac = item.partition("=")
        name, mac = name.strip(), mac.strip()
        if name and MAC_RE.fullmatch(mac):
            out.append((name, mac))
    return out


def send_magic(mac):
    raw = bytes.fromhex(re.sub(r"[:-]", "", mac))
    packet = b"\xff" * 6 + raw * 16
    bcast = os.environ.get("WOL_BROADCAST", "255.255.255.255")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (bcast, 9))
