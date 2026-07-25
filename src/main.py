"""Entry point. Ties together config, sensors, fan groups, MQTT, and the
web status page. See README.md and docs/ARCHITECTURE.md for the full
design rationale before modifying this file.
"""

import time
import _thread
from machine import WDT

import config as config_mod
import boot
from sensors import TempSensors
from fans import FanGroup, compute_duty
import mqtt_client
import web


def build_status(cfg, temps, sensors, fan_groups):
    groups_out = {}
    for name, fg in fan_groups.items():
        override = None
        if fg.override_active():
            override = {
                "duty": fg.override["duty"],
                "expires_in_s": fg.override_seconds_remaining(),
            }
        groups_out[name] = {
            "duty": fg.current_duty,
            "rpm": fg.read_rpms(),
            "override": override,
        }

    # ROM codes actually configured (matched or not), so the status page can
    # tell you which detected ROMs are still unassigned.
    configured_roms = {cfg["sensors"]["rack"], cfg["sensors"]["outside"]}

    return {
        "rack_temp": temps.get(cfg["control_sensor"]),
        "outside_temp": temps.get("outside"),
        "groups": groups_out,
        # {rom_str: celsius} for every DS18B20 seen on the bus, matched or
        # not — lets you read ROM codes + live temps off the status page
        # when the rack isn't physically reachable for a REPL. See
        # sensors.py and README.md "Sensor discovery".
        "detected_sensors": [
            {"rom": rom, "temp": temp, "configured": rom in configured_roms}
            for rom, temp in sensors.last_by_rom.items()
        ],
    }


def main():
    cfg = config_mod.load("config.json")

    # 1. Bring up fan groups FIRST, at min_duty, before touching sensors or
    #    network. Closes the window where fans could sit at 0% during init.
    fan_groups = {}
    for name, gcfg in cfg["fan_groups"].items():
        fg = FanGroup(name, gcfg["pwm_pin"], gcfg["tach_pins"])
        fg.set_duty_percent(cfg["curve"]["min_duty"])
        fan_groups[name] = fg

    # 2. WiFi (best-effort, non-blocking beyond its own timeout)
    if cfg.get("wifi", {}).get("ssid"):
        boot.connect(cfg["wifi"]["ssid"], cfg["wifi"]["password"])

    # 3. Sensors
    sensors = TempSensors(cfg["sensors"]["onewire_pin"], {
        "rack": cfg["sensors"]["rack"],
        "outside": cfg["sensors"]["outside"],
    }, stale_after_s=cfg["sensors"].get("stale_after_s", 30))

    # 4. MQTT publisher (lazy-connects on first publish attempt)
    publisher = mqtt_client.StatusPublisher(cfg["mqtt"])

    # 5. Web server, on core 1, if enabled — keeps the control loop on core 0
    #    from ever being blocked by web request handling.
    status_holder = {"status": {}}

    def get_status_fn():
        return status_holder["status"]

    if cfg.get("web", {}).get("enabled", False):
        web.init(fan_groups, get_status_fn)
        _thread.start_new_thread(
            lambda: web.app.run(port=cfg["web"].get("port", 80)), ()
        )

    # 6. Hardware watchdog — resets the board if the loop below ever hangs.
    wdt = WDT(timeout=cfg.get("watchdog_timeout_ms", 8000))

    # Hysteresis state, one per fan group's driving sensor (they all use the
    # same control_sensor in v1, so one shared value is fine).
    last_duty = cfg["curve"]["min_duty"]
    last_temp_for_hysteresis = None

    poll_interval_s = cfg.get("poll_interval_s", 5)

    while True:
        loop_start = time.ticks_ms()

        try:
            temps = sensors.read_all()
            control_temp = temps.get(cfg["control_sensor"])

            new_duty, last_temp_for_hysteresis = compute_duty(
                control_temp, cfg["curve"], last_duty, last_temp_for_hysteresis
            )
            last_duty = new_duty

            for name, fg in fan_groups.items():
                if fg.override_active():
                    fg.set_duty_percent(fg.override["duty"])
                else:
                    fg.set_duty_percent(new_duty)

            status = build_status(cfg, temps, sensors, fan_groups)
            status_holder["status"] = status

            # Best-effort publish; never allowed to raise past this point.
            publisher.try_publish(status)

        except Exception as e:
            # Anything unexpected here should not kill the loop outright if
            # avoidable, but should also not be silently swallowed forever.
            print("Control loop error:", e)

        wdt.feed()

        elapsed = time.ticks_diff(time.ticks_ms(), loop_start)
        sleep_ms = max(0, poll_interval_s * 1000 - elapsed)
        time.sleep_ms(sleep_ms)


if __name__ == "__main__":
    main()
