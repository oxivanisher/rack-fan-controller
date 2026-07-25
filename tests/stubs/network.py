"""Test-only stand-in for MicroPython's `network` module.

Real WiFi association/DHCP obviously can't happen on a desktop — this only
supports exercising boot.py's connect/timeout logic.
"""

STA_IF = "STA_IF"
AP_IF = "AP_IF"


class WLAN:
    def __init__(self, interface):
        self.interface = interface
        self._active = False
        self._connected = False

    def active(self, state=None):
        if state is None:
            return self._active
        self._active = state

    def isconnected(self):
        return self._connected

    def connect(self, ssid, password):
        self._ssid = ssid
        self._password = password

    def ifconfig(self):
        return ("0.0.0.0", "255.255.255.0", "0.0.0.0", "0.0.0.0")

    def disconnect(self):
        self._connected = False
