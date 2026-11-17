# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Miguel González Oreiro <mgoreiro@gmail.com>
"""Escaneo de la red local (tabla ARP del router) y Wake-on-LAN. Sin módulo `ipaddress` (no existe en Python 2)."""
from __future__ import division, print_function, unicode_literals

import binascii
import gzip
import os
import re
import socket
import struct
import time

import common as c

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
PRIVATE_MAC = "MAC privada (aleatoria)"
LAN_CIDR = c.env("LAN_CIDR", "192.168.1.0/24")  # en el router la LAN no se deduce de la ruta por defecto (esa es la WAN)


def ip2int(ip):
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def int2ip(n):
    return socket.inet_ntoa(struct.pack("!I", n))


def network(cidr=None):
    """(base, bits) de un CIDR, o None si no es válido."""
    ip, _, bits = (cidr or LAN_CIDR).partition("/")
    try:
        bits = int(bits or 24)
        mask = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
        return ip2int(ip) & mask, bits
    except (ValueError, socket.error, OverflowError):
        return None


def in_net(ip, net):
    try:
        mask = (0xFFFFFFFF << (32 - net[1])) & 0xFFFFFFFF
        return ip2int(ip) & mask == net[0]
    except (socket.error, ValueError):
        return False


def hosts(net):
    return [int2ip(net[0] + i) for i in range(1, (1 << (32 - net[1])) - 1)]


def broadcast_ip(net):
    return int2ip(net[0] + (1 << (32 - net[1])) - 1)


def _touch(ip):
    """Un intento de conexión basta para que el kernel resuelva la MAC por ARP."""
    try:
        socket.create_connection((ip, 80), timeout=0.4).close()
    except socket.error:
        pass


def read_arp(net, path="/proc/net/arp"):
    devices = []
    try:
        with open(path) as f:
            lines = f.read().splitlines()[1:]
    except (IOError, OSError):
        return devices
    for line in lines:
        p = line.split()
        if len(p) < 4:
            continue
        ip, flags, mac = p[0], p[2], p[3].lower()
        if flags == "0x0" or mac == "00:00:00:00:00:00":
            continue
        if in_net(ip, net):
            devices.append({"ip": ip, "mac": mac, "hostname": None})
    return devices


def _name(ip):
    try:
        return c.text_of(socket.gethostbyaddr(ip)[0])
    except (socket.error, socket.herror, socket.gaierror):
        return None


# ---- fabricante por MAC (fichero opcional de solo lectura) ----

OUI_PATHS = [c.env("OUI_FILE"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "oui.txt.gz")]


def vendors(macs):
    """{mac: fabricante}. Si no está el fichero de fabricantes, solo detecta las MAC aleatorias."""
    result, wanted = {}, {}
    for mac in macs:
        hexa = re.sub(r"[^0-9A-Fa-f]", "", mac).upper()
        if len(hexa) != 12:
            continue
        if int(hexa[:2], 16) & 0x02:  # "administrada localmente": MAC aleatoria de móviles
            result[mac] = PRIVATE_MAC
            continue
        for n in (9, 7, 6):
            wanted.setdefault(hexa[:n], set()).add(mac)
    path = next((p for p in OUI_PATHS if p and os.path.exists(p)), None)
    if not wanted or not path:
        return result
    found = {}
    try:
        f = gzip.open(path, "rb")
        try:
            for line in f:
                prefix, _, name = line.decode("utf-8", "replace").rstrip("\n").partition("\t")
                if prefix in wanted:
                    found[prefix] = name
        finally:
            f.close()
    except (IOError, OSError, EOFError):
        return result
    for prefix in sorted(found, key=len, reverse=True):
        for mac in wanted[prefix]:
            result.setdefault(mac, found[prefix])
    return result


def scan(net=None):
    """Lista de dispositivos {ip, mac, hostname, vendor} o None si LAN_CIDR no es válido."""
    net = net or network()
    if net is None:
        return None
    if net[1] < 22:
        raise ValueError("red demasiado grande para escanear: %s/%d" % (int2ip(net[0]), net[1]))
    c.pmap(_touch, hosts(net), workers=24)
    time.sleep(0.5)
    devices = read_arp(net)
    names = c.pmap(_name, [d["ip"] for d in devices], workers=8, timeout=4)
    vend = vendors([d["mac"] for d in devices])
    for d, name in zip(devices, names):
        d["hostname"] = name
        d["vendor"] = vend.get(d["mac"])
    devices.sort(key=lambda d: ip2int(d["ip"]))
    return devices


def describe(d, new=False):
    vendor = d.get("vendor") or "fabricante desconocido"
    first = "• %s · %s%s" % (d["ip"], vendor, " 🆕" if new else "")
    host = d.get("hostname")
    return first + "\n   " + " · ".join([d["mac"]] + (["DNS: %s" % host] if host else []))


# ---- Wake-on-LAN ----

def wol_devices():
    """WOL_DEVICES="Nombre=AA:BB:CC:DD:EE:FF,Otro=..." -> [(nombre, mac)]."""
    out = []
    for item in c.env("WOL_DEVICES").split(","):
        name, _, mac = item.partition("=")
        name, mac = name.strip(), mac.strip()
        if name and MAC_RE.match(mac):
            out.append((name, mac))
    return out


def send_magic(mac):
    raw = binascii.unhexlify(re.sub(r"[:-]", "", mac).encode("ascii"))
    packet = b"\xff" * 6 + raw * 16
    net = network()
    bcast = c.env("WOL_BROADCAST") or (broadcast_ip(net) if net else "255.255.255.255")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (bcast, 9))
    finally:
        s.close()


# ---- presencia: PRESENCE=Ana=aa:bb:cc:dd:ee:ff,Pepe=... (solo en memoria) ----

def presence_targets():
    out = []
    for item in c.env("PRESENCE").split(","):
        name, _, mac = item.partition("=")
        name, mac = name.strip(), mac.strip().lower().replace("-", ":")
        if name and MAC_RE.match(mac):
            out.append((name, mac))
    return out
