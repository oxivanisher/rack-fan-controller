"""Test-only stand-in for MicroPython's `onewire` module.

sensors.py only ever passes the OneWire instance straight into ds18x20's
DS18X20 constructor — real bus scanning/timing lives there, so this stub
just needs to exist and be constructible.
"""


class OneWire:
    def __init__(self, pin):
        self.pin = pin
