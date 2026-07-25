import main


class FakeFanGroup:
    def __init__(self, current_duty, rpms, override=None):
        self.current_duty = current_duty
        self._rpms = rpms
        self.override = override

    def override_active(self):
        return self.override is not None

    def override_seconds_remaining(self):
        return self.override["expires_in_s"] if self.override else None

    def read_rpms(self):
        return self._rpms


class FakeSensors:
    def __init__(self, last_by_rom):
        self.last_by_rom = last_by_rom


CFG = {
    "control_sensor": "rack",
    "sensors": {"rack": "28-000001a2b3c4", "outside": "28-000005d6e7f8"},
}


def test_build_status_shape_with_no_override():
    temps = {"rack": 32.4, "outside": 21.1}
    fan_groups = {"intake": FakeFanGroup(65, [1340, 1355])}
    sensors = FakeSensors({"28-000001a2b3c4": 32.4, "28-000005d6e7f8": 21.1})

    status = main.build_status(CFG, temps, sensors, fan_groups)

    assert status["rack_temp"] == 32.4
    assert status["outside_temp"] == 21.1
    assert status["groups"]["intake"] == {
        "duty": 65,
        "rpm": [1340, 1355],
        "override": None,
    }


def test_build_status_includes_active_override():
    fan_groups = {
        "exhaust": FakeFanGroup(0, [0, 0], override={"duty": 0, "expires_in_s": 341}),
    }
    sensors = FakeSensors({})

    status = main.build_status(CFG, {}, sensors, fan_groups)

    assert status["groups"]["exhaust"]["override"] == {"duty": 0, "expires_in_s": 341}


def test_build_status_flags_configured_vs_unassigned_detected_sensors():
    sensors = FakeSensors(
        {
            "28-000001a2b3c4": 32.4,  # matches cfg.sensors.rack
            "28-unassigned0000": 19.0,  # not in config at all
        }
    )

    status = main.build_status(CFG, {}, sensors, fan_groups={})

    by_rom = {d["rom"]: d for d in status["detected_sensors"]}
    assert by_rom["28-000001a2b3c4"]["configured"] is True
    assert by_rom["28-000001a2b3c4"]["temp"] == 32.4
    assert by_rom["28-unassigned0000"]["configured"] is False


def test_build_status_missing_control_temp_is_none_not_a_crash():
    sensors = FakeSensors({})

    status = main.build_status(CFG, temps={}, sensors=sensors, fan_groups={})

    assert status["rack_temp"] is None
    assert status["outside_temp"] is None
