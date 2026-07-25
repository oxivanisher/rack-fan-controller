"""DS18B20 (1-Wire) temperature sensor handling.

Both the "rack" and "outside" sensors share a single 1-Wire GPIO. Sensors are
distinguished by their unique 64-bit ROM code, configured in config.json.

The bus is (re-)scanned on every boot. A configured ROM that isn't found is
a *warning*, not a fatal error — the board still boots (fans stay at
min_duty via main.py's boot-safety ordering) and every ROM code seen on the
bus, with a live temperature, is published in status/MQTT under
"detected_sensors" (see main.py). That's the discovery mechanism: since the
rack sensors aren't reachable from a REPL, read the ROM codes off the status
page instead, identify which is which by touching a sensor and watching
which value moves, then paste the codes into config.json.
"""

import time
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

        self._discovered_roms = self._ds.scan()
        discovered_str = {rom_to_str(r): r for r in self._discovered_roms}

        for name, rom_str in rom_map.items():
            if rom_str not in discovered_str:
                print(
                    "WARNING: configured sensor '%s' (ROM %s) not found on "
                    "bus. Found: %s. Check /status -> detected_sensors for "
                    "live ROM codes." % (name, rom_str, list(discovered_str.keys()))
                )
                continue
            self._rom_by_name[name] = discovered_str[rom_str]

        self.last_by_rom = {}  # {rom_str: celsius}, refreshed each read_all()

    def read_all(self):
        """Trigger one conversion and return {name: celsius} for configured,
        matched sensors (missing/unmatched names are simply absent).

        As a side effect, self.last_by_rom is refreshed with every ROM seen
        on the bus (matched or not) so callers can surface raw discovery
        data (e.g. for the status page) without a second, separate
        conversion pass.

        Blocks ~750ms for conversion (12-bit default resolution). Called
        once per poll cycle, so this is fine — irrelevant next to the
        poll_interval_s scale (seconds).
        """
        self._ds.convert_temp()
        time.sleep_ms(750)

        by_rom = {}
        for rom in self._discovered_roms:
            try:
                by_rom[rom_to_str(rom)] = self._ds.read_temp(rom)
            except Exception as e:
                print("Failed reading sensor %s: %s" % (rom_to_str(rom), e))
        self.last_by_rom = by_rom

        return {
            name: by_rom.get(rom_to_str(rom))
            for name, rom in self._rom_by_name.items()
        }

    @staticmethod
    def scan_bus(onewire_pin):
        """Utility: print ROM codes of everything on the bus. Handy from a
        REPL if you do have physical/USB access; otherwise unnecessary now
        that detected ROM codes are published on every boot (see above).
        """
        ow = onewire.OneWire(Pin(onewire_pin))
        ds = ds18x20.DS18X20(ow)
        roms = ds.scan()
        print("Found %d device(s):" % len(roms))
        for r in roms:
            print("  ", rom_to_str(r))
        return roms
