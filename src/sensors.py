"""DS18B20 (1-Wire) temperature sensor handling.

Both the "rack" and "outside" sensors share a single 1-Wire GPIO. Sensors are
distinguished by their unique 64-bit ROM code, configured in config.json.

Run scan_bus() once during setup (e.g. from the REPL) to discover the ROM
codes of your physical sensors, then paste them into config.json.
"""

import onewire
import ds18x20
from machine import Pin


def rom_to_str(rom_bytes):
    return "-".join(
        ["%02x" % rom_bytes[0]] + ["".join("%02x" % b for b in rom_bytes[1:])]
    )


class TempSensors:
    def __init__(self, onewire_pin, rom_map):
        """
        onewire_pin: GPIO number for the shared 1-Wire bus
        rom_map: dict like {"rack": "28-000001a2b3c4", "outside": "28-..."}
        """
        self._ow = onewire.OneWire(Pin(onewire_pin))
        self._ds = ds18x20.DS18X20(self._ow)
        self._rom_by_name = {}
        self._name_by_rom = {}

        discovered = self._ds.scan()
        discovered_str = {rom_to_str(r): r for r in discovered}

        for name, rom_str in rom_map.items():
            if rom_str not in discovered_str:
                raise RuntimeError(
                    "Configured sensor '%s' (ROM %s) not found on bus. "
                    "Found: %s" % (name, rom_str, list(discovered_str.keys()))
                )
            self._rom_by_name[name] = discovered_str[rom_str]
            self._name_by_rom[rom_str] = name

    def read_all(self):
        """Trigger a conversion on all sensors and return {name: celsius}.

        Blocks ~750ms for conversion (12-bit default resolution). Called
        once per poll cycle, so this is fine — irrelevant next to the
        poll_interval_s scale (seconds).
        """
        self._ds.convert_temp()
        import time
        time.sleep_ms(750)

        result = {}
        for name, rom in self._rom_by_name.items():
            result[name] = self._ds.read_temp(rom)
        return result

    @staticmethod
    def scan_bus(onewire_pin):
        """Utility: print ROM codes of everything on the bus. Run once
        manually from the REPL during setup, not part of normal operation.
        """
        ow = onewire.OneWire(Pin(onewire_pin))
        ds = ds18x20.DS18X20(ow)
        roms = ds.scan()
        print("Found %d device(s):" % len(roms))
        for r in roms:
            print("  ", rom_to_str(r))
        return roms
