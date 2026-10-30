"""Minimal DNS A-record lookup with a hard time limit.

MicroPython's socket.getaddrinfo() ignores socket timeouts and waits for
lwIP's own DNS retries: about 7s per unresponsive server, up to two servers.
That's long enough to trip the hardware watchdog from the control loop, so
hostnames are resolved here instead, with a single UDP query and a timeout
this module controls.

Only plain unicast DNS against one server — no mDNS (.local) names.
"""

import socket
import struct
import os

DNS_PORT = 53
TYPE_A = 1
CLASS_IN = 1


def is_ip(host):
    """True for a dotted-quad IPv4 literal, which needs no lookup at all."""
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or int(part) > 255:
            return False
    return True


def build_query(name, txid):
    # Header: id, flags (recursion desired), 1 question, 0 other records
    query = bytearray(struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0))
    for label in name.split("."):
        query.append(len(label))
        query.extend(label.encode())
    query.append(0)
    query.extend(struct.pack("!HH", TYPE_A, CLASS_IN))
    return bytes(query)


def _skip_name(data, pos):
    """Returns the position right after the (maybe compressed) name at pos."""
    while True:
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:  # compression pointer, always ends the name
            return pos + 2
        pos += length + 1


def parse_response(data, txid):
    """Returns the first A record as a dotted-quad string, or None if the
    response doesn't contain one (wrong id, error rcode, CNAME only, ...).
    Malformed responses may raise IndexError/struct.error; resolve() handles
    those.
    """
    resp_id, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", data[:12])
    if resp_id != txid or not flags & 0x8000 or flags & 0x000F:
        return None

    pos = 12
    for _ in range(qdcount):
        pos = _skip_name(data, pos) + 4  # QTYPE + QCLASS

    for _ in range(ancount):
        pos = _skip_name(data, pos)
        rtype, rclass, _, rdlength = struct.unpack("!HHIH", data[pos:pos + 10])
        pos += 10
        if rtype == TYPE_A and rclass == CLASS_IN and rdlength == 4:
            return "%d.%d.%d.%d" % (data[pos], data[pos + 1], data[pos + 2], data[pos + 3])
        pos += rdlength

    return None


def resolve(name, server, timeout_s=1, port=DNS_PORT):
    """Best-effort lookup. Returns an IP string, or None on any failure.
    Blocks for at most about timeout_s. Never raises.
    """
    if not server or server == "0.0.0.0":
        return None

    sock = None
    try:
        txid = struct.unpack("!H", os.urandom(2))[0]
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout_s)
        sock.connect((server, port))
        sock.send(build_query(name, txid))
        return parse_response(sock.recv(512), txid)
    except Exception as e:
        print("DNS lookup of %s failed: %s" % (name, e))
        return None
    finally:
        if sock is not None:
            sock.close()
