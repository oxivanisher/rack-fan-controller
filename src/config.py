"""Load and provide access to config.json.

Kept deliberately dumb: no schema validation library (not worth the RAM on a
Pico), just a straight json.load plus a couple of sanity checks that would
otherwise fail confusingly deep inside the control loop.
"""

import json


def load(path="config.json"):
    with open(path) as f:
        cfg = json.load(f)

    _validate(cfg)
    return cfg


def _validate(cfg):
    curve = cfg["curve"]
    if curve["min_temp"] >= curve["max_temp"]:
        raise ValueError("curve.min_temp must be < curve.max_temp")

    for name, group in cfg["fan_groups"].items():
        if "pwm_pin" not in group or "tach_pins" not in group:
            raise ValueError("fan_groups.%s missing pwm_pin/tach_pins" % name)
        if len(group["tach_pins"]) < 1:
            raise ValueError("fan_groups.%s needs at least one tach pin" % name)
        if "min_duty" not in group or "max_duty" not in group:
            raise ValueError("fan_groups.%s missing min_duty/max_duty" % name)
        if not (0 <= group["min_duty"] <= group["max_duty"] <= 100):
            raise ValueError(
                "fan_groups.%s duty values must satisfy 0 <= min_duty <= max_duty <= 100" % name
            )
