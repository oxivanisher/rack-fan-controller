import socket
import struct
import threading
import time

import pytest

import dns_lookup


def make_response(txid, name, answers=(), flags=0x8180):
    """answers: list of (rtype, rdata). Names use a compression pointer back
    to the question, the way real servers answer.
    """
    query = dns_lookup.build_query(name, txid)
    resp = bytearray(struct.pack("!HHHHHH", txid, flags, 1, len(answers), 0, 0))
    resp.extend(query[12:])
    for rtype, rdata in answers:
        resp.extend(struct.pack("!HHHIH", 0xC00C, rtype, 1, 60, len(rdata)))
        resp.extend(rdata)
    return bytes(resp)


@pytest.mark.parametrize(
    "host,expected",
    [
        ("192.168.1.10", True),
        ("mqtt.example.lan", False),
        ("broker", False),
        ("1.2.3", False),
        ("1.2.3.256", False),
        ("1.2.3.mqtt", False),
    ],
)
def test_is_ip(host, expected):
    assert dns_lookup.is_ip(host) is expected


def test_build_query_encodes_name_as_labels():
    query = dns_lookup.build_query("mqtt.lan", 0x1234)

    assert query[:2] == b"\x12\x34"
    assert query[12:] == b"\x04mqtt\x03lan\x00\x00\x01\x00\x01"


def test_parse_response_returns_a_record():
    data = make_response(7, "mqtt.lan", [(1, bytes([192, 168, 1, 10]))])

    assert dns_lookup.parse_response(data, 7) == "192.168.1.10"


def test_parse_response_skips_cname_before_a_record():
    data = make_response(
        7, "mqtt.lan", [(5, b"\x04host\xc0\x11"), (1, bytes([10, 0, 0, 2]))]
    )

    assert dns_lookup.parse_response(data, 7) == "10.0.0.2"


def test_parse_response_rejects_wrong_transaction_id():
    data = make_response(7, "mqtt.lan", [(1, bytes([10, 0, 0, 2]))])

    assert dns_lookup.parse_response(data, 8) is None


def test_parse_response_rejects_nxdomain():
    data = make_response(7, "mqtt.lan", flags=0x8183)

    assert dns_lookup.parse_response(data, 7) is None


@pytest.fixture
def udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    yield sock
    sock.close()


def test_resolve_over_real_udp_socket(udp_server):
    def answer():
        data, addr = udp_server.recvfrom(512)
        txid = struct.unpack("!H", data[:2])[0]
        udp_server.sendto(
            make_response(txid, "mqtt.lan", [(1, bytes([10, 0, 0, 9]))]), addr
        )

    thread = threading.Thread(target=answer)
    thread.start()
    ip = dns_lookup.resolve("mqtt.lan", "127.0.0.1", port=udp_server.getsockname()[1])
    thread.join()

    assert ip == "10.0.0.9"


def test_resolve_silent_server_gives_up_at_the_timeout(udp_server):
    start = time.monotonic()

    ip = dns_lookup.resolve(
        "mqtt.lan", "127.0.0.1", timeout_s=0.1, port=udp_server.getsockname()[1]
    )

    assert ip is None
    assert time.monotonic() - start < 1


def test_resolve_truncated_response_is_none_not_a_crash(udp_server):
    def answer():
        _, addr = udp_server.recvfrom(512)
        udp_server.sendto(b"\x00\x01", addr)

    thread = threading.Thread(target=answer)
    thread.start()
    ip = dns_lookup.resolve("mqtt.lan", "127.0.0.1", port=udp_server.getsockname()[1])
    thread.join()

    assert ip is None


@pytest.mark.parametrize("server", ["0.0.0.0", "", None])
def test_resolve_without_a_dns_server_is_none(server):
    assert dns_lookup.resolve("mqtt.lan", server) is None
