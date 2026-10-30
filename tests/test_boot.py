import time

import pytest

import boot


class FakeWlan:
    def __init__(self, connected=False):
        self.connected = connected
        self.connect_calls = []
        self.connect_error = None

    def isconnected(self):
        return self.connected

    def ifconfig(self):
        return ("10.0.0.5", "255.255.255.0", "10.0.0.1", "10.0.0.53")

    def connect(self, ssid, password):
        self.connect_calls.append((ssid, password))
        if self.connect_error:
            raise self.connect_error


class Clock:
    def __init__(self):
        self.now = 1000000

    def advance(self, seconds):
        self.now += int(seconds * 1000)


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(time, "ticks_ms", lambda: clock.now)
    return clock


def test_connected_link_does_not_reconnect(clock):
    wlan = FakeWlan(connected=True)
    monitor = boot.WifiMonitor(wlan, "ssid", "pw")
    clock.advance(60)

    assert monitor.check() is True

    assert wlan.connect_calls == []


def test_down_link_waits_for_the_retry_interval(clock):
    wlan = FakeWlan()
    monitor = boot.WifiMonitor(wlan, "ssid", "pw", min_retry_interval_s=30)

    clock.advance(29)
    assert monitor.check() is False
    assert wlan.connect_calls == []

    clock.advance(1)
    assert monitor.check() is False
    assert wlan.connect_calls == [("ssid", "pw")]


def test_reconnect_attempts_stay_rate_limited(clock):
    wlan = FakeWlan()
    monitor = boot.WifiMonitor(wlan, "ssid", "pw", min_retry_interval_s=30)

    for _ in range(12):  # 60s at the default 5s poll interval
        clock.advance(5)
        monitor.check()

    assert len(wlan.connect_calls) == 2


def test_recovered_link_stops_reconnecting(clock):
    wlan = FakeWlan()
    monitor = boot.WifiMonitor(wlan, "ssid", "pw", min_retry_interval_s=30)
    clock.advance(30)
    monitor.check()
    wlan.connected = True
    clock.advance(60)

    assert monitor.check() is True

    assert len(wlan.connect_calls) == 1


def test_connect_error_does_not_escape(clock):
    wlan = FakeWlan()
    wlan.connect_error = OSError("EPERM")
    monitor = boot.WifiMonitor(wlan, "ssid", "pw", min_retry_interval_s=30)
    clock.advance(30)

    assert monitor.check() is False
