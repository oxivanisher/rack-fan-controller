"""Test-only stand-in for MicroPython's `ds18x20` module.

Real DS18B20 conversion timing/CRC behavior can't be meaningfully faked on
a desktop, so this stub is intentionally inert — tests monkeypatch
`ds18x20.DS18X20` with a fake that returns canned scan()/read_temp() data.
"""


class DS18X20:
    def __init__(self, onewire):
        self.onewire = onewire

    def scan(self):
        return []

    def convert_temp(self):
        pass

    def read_temp(self, rom):
        raise NotImplementedError("stub: monkeypatch ds18x20.DS18X20 in tests")
