import copy
import json

import pytest

import config as config_mod

_BASE_CFG = {
    "wifi": {"ssid": "x", "password": "y"},
    "mqtt": {"enabled": False, "broker": "", "client_id": "c", "topic": "t"},
    "web": {"enabled": False},
    "poll_interval_s": 5,
    "control_sensor": "rack",
    "sensors": {"onewire_pin": 4, "rack": "28-a", "outside": "28-b"},
    "curve": {"min_temp": 30, "max_temp": 35, "min_duty": 20, "max_duty": 100, "hysteresis": 0.5},
    "fan_groups": {
        "intake": {"pwm_pin": 15, "tach_pins": [14, 13]},
        "exhaust": {"pwm_pin": 17, "tach_pins": [16, 12]},
    },
    "watchdog_timeout_ms": 8000,
}


def _write_config(tmp_path, **overrides):
    cfg = copy.deepcopy(_BASE_CFG)
    for key, value in overrides.items():
        cfg[key] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    return path


def test_load_accepts_valid_config(tmp_path):
    path = _write_config(tmp_path)
    cfg = config_mod.load(str(path))
    assert cfg["control_sensor"] == "rack"
    assert cfg["fan_groups"]["intake"]["pwm_pin"] == 15


def test_load_rejects_inverted_temp_bounds(tmp_path):
    path = _write_config(
        tmp_path,
        curve={"min_temp": 35, "max_temp": 30, "min_duty": 20, "max_duty": 100, "hysteresis": 0.5},
    )
    with pytest.raises(ValueError, match="min_temp"):
        config_mod.load(str(path))


def test_load_rejects_equal_temp_bounds(tmp_path):
    path = _write_config(
        tmp_path,
        curve={"min_temp": 30, "max_temp": 30, "min_duty": 20, "max_duty": 100, "hysteresis": 0.5},
    )
    with pytest.raises(ValueError, match="min_temp"):
        config_mod.load(str(path))


def test_load_rejects_inverted_duty_bounds(tmp_path):
    path = _write_config(
        tmp_path,
        curve={"min_temp": 30, "max_temp": 35, "min_duty": 100, "max_duty": 20, "hysteresis": 0.5},
    )
    with pytest.raises(ValueError, match="duty"):
        config_mod.load(str(path))


def test_load_rejects_duty_out_of_0_100_range(tmp_path):
    path = _write_config(
        tmp_path,
        curve={"min_temp": 30, "max_temp": 35, "min_duty": -5, "max_duty": 100, "hysteresis": 0.5},
    )
    with pytest.raises(ValueError, match="duty"):
        config_mod.load(str(path))


def test_load_rejects_fan_group_missing_pwm_pin(tmp_path):
    path = _write_config(
        tmp_path,
        fan_groups={"intake": {"tach_pins": [14, 13]}},
    )
    with pytest.raises(ValueError, match="intake"):
        config_mod.load(str(path))


def test_load_rejects_fan_group_with_no_tach_pins(tmp_path):
    path = _write_config(
        tmp_path,
        fan_groups={"intake": {"pwm_pin": 15, "tach_pins": []}},
    )
    with pytest.raises(ValueError, match="intake"):
        config_mod.load(str(path))
