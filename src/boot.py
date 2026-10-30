"""Best-effort WiFi connect at boot.

Deliberately does NOT block forever or crash the board if WiFi is
unavailable — the control loop must be able to run headless. main.py should
tolerate wifi being disconnected (MQTT/web will simply stay offline until
it reconnects).
"""

import network
import time


def connect(ssid, password, timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, password)

    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
            print("WiFi connect timed out, continuing without network")
            break
        time.sleep_ms(200)

    if wlan.isconnected():
        print("WiFi connected:", wlan.ifconfig())
    return wlan


class WifiMonitor:
    """Rejoins WiFi when the link is down, from inside the control loop.

    connect() above only runs once, so without this the board would stay
    offline after an outage. Only ever calls the non-blocking wlan.connect(),
    never connect()'s wait loop, and rate-limits it so an attempt that's
    still in progress gets time to finish.
    """

    def __init__(self, wlan, ssid, password, min_retry_interval_s=30):
        self._wlan = wlan
        self._ssid = ssid
        self._password = password
        self._min_retry_interval_ms = min_retry_interval_s * 1000
        self._last_attempt_ms = time.ticks_ms()  # connect() just tried
        self._was_connected = wlan.isconnected()

    def check(self):
        """Returns whether the link is up. Never raises."""
        try:
            connected = self._wlan.isconnected()
            if connected != self._was_connected:
                print("WiFi link", "up:" if connected else "down",
                      self._wlan.ifconfig() if connected else "")
                self._was_connected = connected
            if connected:
                return True

            now = time.ticks_ms()
            if time.ticks_diff(now, self._last_attempt_ms) >= self._min_retry_interval_ms:
                self._last_attempt_ms = now
                self._wlan.connect(self._ssid, self._password)
        except Exception as e:
            print("WiFi reconnect failed:", e)
        return False
