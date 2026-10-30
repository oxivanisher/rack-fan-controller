import time

import pytest

import dns_lookup
import mqtt_client


class FakeSock:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeMQTTClient:
    instances = []
    connect_error = None
    publish_error = None

    def __init__(self, client_id, server, port, user, password, keepalive):
        self.server = server
        self.sock = FakeSock()
        self.connect_timeout = None
        self.published = []
        FakeMQTTClient.instances.append(self)

    def set_last_will(self, topic, msg, retain=False):
        pass

    def connect(self, timeout=None):
        self.connect_timeout = timeout
        if FakeMQTTClient.connect_error:
            raise FakeMQTTClient.connect_error

    def publish(self, topic, msg, retain=False):
        if FakeMQTTClient.publish_error:
            raise FakeMQTTClient.publish_error
        self.published.append((topic, msg))


class FakeWlan:
    def __init__(self, connected=True):
        self.connected = connected

    def isconnected(self):
        return self.connected

    def ifconfig(self):
        return ("10.0.0.5", "255.255.255.0", "10.0.0.1", "10.0.0.53")


class Clock:
    def __init__(self):
        self.now = 1000000

    def advance(self, seconds):
        self.now += int(seconds * 1000)


CFG = {
    "enabled": True,
    "broker": "mqtt.lan",
    "client_id": "test",
    "topic": "rack/status",
    "reconnect_min_interval_s": 15,
}


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(time, "ticks_ms", lambda: clock.now)
    return clock


@pytest.fixture
def lookups(monkeypatch):
    """Scripted DNS: set lookups["ip"]; records which servers were asked."""
    state = {"ip": "10.0.0.9", "servers": []}

    def fake_resolve(name, server):
        state["servers"].append(server)
        return state["ip"]

    monkeypatch.setattr(dns_lookup, "resolve", fake_resolve)
    return state


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeMQTTClient.instances = []
    FakeMQTTClient.connect_error = None
    FakeMQTTClient.publish_error = None
    monkeypatch.setattr(mqtt_client, "MQTTClient", FakeMQTTClient)


def test_connect_sets_socket_timeout(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())

    assert publisher.try_publish({}) is True

    assert FakeMQTTClient.instances[0].connect_timeout == mqtt_client.SOCKET_TIMEOUT_S


def test_hostname_is_resolved_via_the_dhcp_dns_server(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())

    publisher.try_publish({})

    assert lookups["servers"] == ["10.0.0.53"]
    assert FakeMQTTClient.instances[0].server == "10.0.0.9"


def test_ip_broker_skips_dns(clock, lookups):
    publisher = mqtt_client.StatusPublisher(dict(CFG, broker="10.0.0.7"), FakeWlan())

    publisher.try_publish({})

    assert lookups["servers"] == []
    assert FakeMQTTClient.instances[0].server == "10.0.0.7"


def test_dns_outage_falls_back_to_last_known_ip(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())
    publisher.try_publish({})
    FakeMQTTClient.publish_error = OSError("dead socket")
    publisher.try_publish({})  # connection lost
    FakeMQTTClient.publish_error = None
    lookups["ip"] = None
    clock.advance(16)

    assert publisher.try_publish({}) is True

    assert FakeMQTTClient.instances[-1].server == "10.0.0.9"


def test_moved_broker_is_picked_up_on_reconnect(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())
    publisher.try_publish({})
    FakeMQTTClient.publish_error = OSError("dead socket")
    publisher.try_publish({})
    FakeMQTTClient.publish_error = None
    lookups["ip"] = "10.0.0.77"
    clock.advance(16)

    publisher.try_publish({})

    assert FakeMQTTClient.instances[-1].server == "10.0.0.77"


def test_dns_outage_with_no_known_ip_does_not_attempt_connect(clock, lookups):
    lookups["ip"] = None
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())

    assert publisher.try_publish({}) is False

    assert FakeMQTTClient.instances == []


def test_failed_lookup_is_rate_limited_too(clock, lookups):
    lookups["ip"] = None
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())

    publisher.try_publish({})
    clock.advance(5)
    publisher.try_publish({})
    assert len(lookups["servers"]) == 1

    clock.advance(11)
    publisher.try_publish({})
    assert len(lookups["servers"]) == 2


def test_failed_connect_closes_the_socket(clock, lookups):
    FakeMQTTClient.connect_error = OSError("ETIMEDOUT")
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())

    assert publisher.try_publish({}) is False

    assert FakeMQTTClient.instances[0].sock.closed is True


def test_failed_publish_closes_the_socket_and_reconnects(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, FakeWlan())
    publisher.try_publish({})
    first = FakeMQTTClient.instances[0]
    FakeMQTTClient.publish_error = OSError("ETIMEDOUT")

    assert publisher.try_publish({}) is False
    assert first.sock.closed is True

    FakeMQTTClient.publish_error = None
    clock.advance(16)
    assert publisher.try_publish({}) is True
    assert FakeMQTTClient.instances[-1] is not first


def test_link_down_skips_network_work_and_closes_the_client(clock, lookups):
    wlan = FakeWlan()
    publisher = mqtt_client.StatusPublisher(CFG, wlan)
    publisher.try_publish({})
    wlan.connected = False
    lookups["servers"].clear()

    assert publisher.try_publish({}) is False

    assert FakeMQTTClient.instances[0].sock.closed is True
    assert lookups["servers"] == []


def test_reconnects_once_link_returns(clock, lookups):
    wlan = FakeWlan(connected=False)
    publisher = mqtt_client.StatusPublisher(CFG, wlan)
    assert publisher.try_publish({}) is False

    wlan.connected = True

    assert publisher.try_publish({}) is True


def test_no_wifi_configured_never_publishes(clock, lookups):
    publisher = mqtt_client.StatusPublisher(CFG, None)

    assert publisher.try_publish({}) is False

    assert FakeMQTTClient.instances == []


def test_disabled_never_connects(clock, lookups):
    publisher = mqtt_client.StatusPublisher(dict(CFG, enabled=False), FakeWlan())

    assert publisher.try_publish({}) is False

    assert FakeMQTTClient.instances == []
