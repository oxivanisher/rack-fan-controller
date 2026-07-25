import ds18x20 as ds18x20_mod
import onewire as onewire_mod

import sensors as sensors_mod


def _rom_bytes(rom_str):
    family_hex, rest_hex = rom_str.split("-")
    return bytes(
        [int(family_hex, 16)] + [int(rest_hex[i : i + 2], 16) for i in range(0, len(rest_hex), 2)]
    )


class FakeDS18X20:
    def __init__(self, discovered_rom_strs, temps_by_rom):
        self._roms = [_rom_bytes(s) for s in discovered_rom_strs]
        self._temps = dict(temps_by_rom)

    def scan(self):
        return self._roms

    def convert_temp(self):
        pass

    def read_temp(self, rom):
        return self._temps[sensors_mod.rom_to_str(rom)]


class FlakyDS18X20(FakeDS18X20):
    """Like FakeDS18X20, but read_temp raises for any rom currently listed
    in self.fail_roms (mutable between read_all() calls)."""

    def __init__(self, discovered_rom_strs, temps_by_rom):
        super().__init__(discovered_rom_strs, temps_by_rom)
        self.fail_roms = set()

    def read_temp(self, rom):
        rom_str = sensors_mod.rom_to_str(rom)
        if rom_str in self.fail_roms:
            raise onewire_mod.OneWireError("CRC error")
        return self._temps[rom_str]


def _make_sensors(monkeypatch, rom_map, discovered_rom_strs, temps_by_rom, stale_after_s=30):
    fake = FakeDS18X20(discovered_rom_strs, temps_by_rom)
    monkeypatch.setattr(onewire_mod, "OneWire", lambda pin: pin)
    monkeypatch.setattr(ds18x20_mod, "DS18X20", lambda onewire: fake)
    return sensors_mod.TempSensors(onewire_pin=4, rom_map=rom_map, stale_after_s=stale_after_s)


def _make_flaky_sensors(monkeypatch, rom_map, discovered_rom_strs, temps_by_rom, stale_after_s=30):
    fake = FlakyDS18X20(discovered_rom_strs, temps_by_rom)
    monkeypatch.setattr(onewire_mod, "OneWire", lambda pin: pin)
    monkeypatch.setattr(ds18x20_mod, "DS18X20", lambda onewire: fake)
    ts = sensors_mod.TempSensors(onewire_pin=4, rom_map=rom_map, stale_after_s=stale_after_s)
    return ts, fake


def test_round_trips_rom_bytes_helper_against_rom_to_str():
    assert sensors_mod.rom_to_str(_rom_bytes("28-000001a2b3c4")) == "28-000001a2b3c4"


def test_read_all_returns_named_temps_for_matched_roms(monkeypatch):
    rom_map = {"rack": "28-000001a2b3c4", "outside": "28-000005d6e7f8"}
    ts = _make_sensors(
        monkeypatch,
        rom_map,
        discovered_rom_strs=["28-000001a2b3c4", "28-000005d6e7f8"],
        temps_by_rom={"28-000001a2b3c4": 32.4, "28-000005d6e7f8": 21.1},
    )

    assert ts.read_all() == {"rack": 32.4, "outside": 21.1}


def test_unmatched_configured_rom_warns_instead_of_raising(monkeypatch, capsys):
    rom_map = {"rack": "28-doesnotexist", "outside": "28-000005d6e7f8"}
    ts = _make_sensors(
        monkeypatch,
        rom_map,
        discovered_rom_strs=["28-000005d6e7f8"],
        temps_by_rom={"28-000005d6e7f8": 21.1},
    )

    captured = capsys.readouterr()
    assert "WARNING" in captured.out
    assert "rack" in captured.out

    named = ts.read_all()
    assert named == {"outside": 21.1}  # "rack" simply absent, no crash


def test_last_by_rom_exposes_every_discovered_rom_matched_or_not(monkeypatch):
    rom_map = {"rack": "28-000001a2b3c4"}  # "outside" deliberately not configured
    ts = _make_sensors(
        monkeypatch,
        rom_map,
        discovered_rom_strs=["28-000001a2b3c4", "28-aabbccddeeff"],
        temps_by_rom={"28-000001a2b3c4": 32.4, "28-aabbccddeeff": 19.0},
    )

    ts.read_all()

    assert ts.last_by_rom == {"28-000001a2b3c4": 32.4, "28-aabbccddeeff": 19.0}


def test_last_by_rom_empty_before_first_read(monkeypatch):
    ts = _make_sensors(
        monkeypatch,
        rom_map={},
        discovered_rom_strs=["28-000001a2b3c4"],
        temps_by_rom={"28-000001a2b3c4": 32.4},
    )

    assert ts.last_by_rom == {}


def test_transient_read_failure_falls_back_to_last_good_value(monkeypatch, capsys):
    rom_map = {"rack": "28-000001a2b3c4"}
    ts, fake = _make_flaky_sensors(
        monkeypatch,
        rom_map,
        discovered_rom_strs=["28-000001a2b3c4"],
        temps_by_rom={"28-000001a2b3c4": 32.4},
        stale_after_s=30,
    )

    assert ts.read_all() == {"rack": 32.4}  # good reading, cached

    fake.fail_roms.add("28-000001a2b3c4")
    named = ts.read_all()  # this read fails a CRC check on the bus

    assert named == {"rack": 32.4}  # served from cache, not dropped
    assert "using cached value" in capsys.readouterr().out.lower()


def test_read_failure_drops_once_cache_exceeds_stale_after_s(monkeypatch):
    import time as time_mod

    rom_map = {"rack": "28-000001a2b3c4"}
    ts, fake = _make_flaky_sensors(
        monkeypatch,
        rom_map,
        discovered_rom_strs=["28-000001a2b3c4"],
        temps_by_rom={"28-000001a2b3c4": 32.4},
        stale_after_s=30,
    )

    assert ts.read_all() == {"rack": 32.4}

    fake.fail_roms.add("28-000001a2b3c4")
    real_ticks_ms = time_mod.ticks_ms
    monkeypatch.setattr(time_mod, "ticks_ms", lambda: real_ticks_ms() + 31_000)

    named = ts.read_all()  # still failing, but cache is now older than stale_after_s

    assert named == {"rack": None}
