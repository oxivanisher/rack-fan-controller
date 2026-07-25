# Rack Fan Controller (Pico W)

Temperature-controlled PWM fan controller for a homelab server rack, built on a
Raspberry Pi Pico W running MicroPython.

This README is written to be a **complete context capsule** — everything
needed to understand *why* the project looks the way it does, not just *what*
it does, so a future session (human or AI) can pick this up without
re-deriving the design decisions below.

## Goal

- Rack has intake + exhaust PC fans, previously driven by a manual variable
  voltage regulator.
- Replace that with closed-loop PWM control based on rack temperature.
- Keep a minimum "always-on" fan speed for silent-but-nonzero airflow
  (workshop is used for tinkering, not just storage — noise matters).
- Independently monitored via an existing Zigbee temperature sensor + Home
  Assistant, so **this controller does not need to be a smart-home citizen**.
  IoT integration is intentionally minimal: it just needs to publish data
  somewhere ingestible (MQTT → user's own InfluxDB pipeline) and self-govern
  the rack even if the network is down.

## Hardware

| Component | Notes |
|---|---|
| Raspberry Pi Pico W (or Pico 2 W) | Has hardware PWM (PIO/slice-based) and PIO-capable pins; WiFi used only for MQTT + status page, **not** required for core fan control loop |
| 2x DS18B20 (1-Wire temp sensors) | One inside rack (top, hot-air zone), one outside rack ("workshop ambient") |
| 4x Noctua 4-pin PC fans | 2x intake (airflow-optimized model), 2x exhaust (static-pressure-optimized model). Different models chosen only because that's what was on hand — treated as functionally equivalent per role. |
| 12V PSU (existing) | Powers fans directly |
| Buck converter (12V→5V) | Powers the Pico via VBUS/USB pin, so no separate USB supply needed in the enclosure |
| Pull-up resistors | 4.7kΩ on the 1-Wire bus; 4.7kΩ on each of the 4 tach lines (see `docs/WIRING.md`) |

### Key hardware decisions (and why)

- **DS18B20 over AM2320/AM2302/LM35**: digital, multi-drop on one GPIO,
  accurate enough (±0.5°C), immune to the analog noise a PWM-switching
  environment would otherwise induce on an LM35's analog line. AM2302/AM2320
  were ruled out — they're humidity+temp combo sensors, no benefit here, and
  slower/less reliable to poll than 1-Wire.
- **All fans in a group share ONE PWM line.** PWM inputs on PC fans are
  high-impedance logic lines, not a driven load — safe to tie together.
  Reduces GPIO usage regardless of group size (currently 2 fans/group, but
  `FanGroup`/`config.json` support 3+ per group with no code changes — see
  `docs/WIRING.md` "Scaling to 3+ fans per group").
- **Tach lines are NOT shared** — each fan gets its own tach GPIO + pull-up.
  Tach outputs are open-collector; combining two fans' tach lines produces
  garbage pulse counts. One tach GPIO per physical fan so each fan's RPM is
  individually readable (useful for spotting a fan starting to degrade, even
  though active stall-detection logic was explicitly descoped for v1 — see
  below).
- **PWM frequency: 25kHz.** Standard Intel PWM spec frequency for PC fans;
  staying at or above ~20kHz keeps switching noise out of the audible range
  (a common cause of annoying fan whine at lower PWM frequencies).
- **No level shifting on PWM output.** Pico GPIOs are 3.3V logic; PC fan PWM
  inputs (Noctua confirmed, most others too) accept 3.3V logic fine since it's
  a logic threshold, not a driven signal. Tach pull-ups go to the Pico's
  **3.3V rail, not 12V** — this is a common wiring mistake and would kill a
  GPIO.

## Control logic (v1 scope)

- Single control sensor ("rack" zone) drives a linear ramp:
  - `temp <= min_temp` → `min_duty`
  - `min_temp < temp < max_temp` → linear interpolation
  - `temp >= max_temp` → `max_duty`
- Hysteresis band prevents duty cycle chatter when temp sits near a boundary.
- "Outside" sensor is **informational only** in v1 — logged/published, not
  fed into the control loop. Rationale: don't add complexity (e.g.
  rack-vs-ambient delta modulating max duty) before there's real logged data
  showing it's needed. This is a deliberate, documented simplification, not
  an oversight — revisit if workshop ambient swings turn out to matter.
- **Manual override per fan group**, with a mandatory expiry
  (`override_until` timestamp), used for the initial "how quiet can these
  fans go" tuning process: drop one group to 0% / raise the other until it's
  audible, note the duty%, repeat for the other group, then bake the numbers
  into `config.json`. Override state is runtime-only — **never persisted
  across reboot** (a stale override silently surviving a power cycle is a
  worse failure mode than just requiring the user to re-set it).
- **Stall detection: explicitly out of scope for v1.** User's fans are
  Noctua and have not failed historically; RPM is still published per-fan so
  the data exists in Influx if this is revisited later.

## Software architecture

```
src/
  boot.py         # WiFi connect (best-effort, non-blocking for main loop)
  main.py         # Ties everything together; the control loop + watchdog
  config.py       # Loads/validates config.json
  sensors.py      # DS18B20 wrapper: scan bus, map ROM codes -> zone names
  fans.py         # FanGroup class: PWM out, tach counting, override state
  mqtt_client.py  # Thin wrapper over umqtt.simple with reconnect + non-blocking publish
  web.py          # microdot-based status page + override API
  lib/            # third-party deps go here (see "Dependencies" below) — NOT vendored in this repo
config.example.json
docs/
  WIRING.md       # Pinout, resistor values, physical wiring notes
  ARCHITECTURE.md # Data flow / sequence diagram in text form
```

### Design principle: control loop must survive network/MQTT failure

Fan control (sensor read → compute duty → set PWM) runs independently of
MQTT publish and the web server. A failed publish is caught and logged, never
allowed to block or delay the next control loop iteration. A hardware
watchdog timer (`machine.WDT`) resets the board if the main loop ever hangs.

### Boot safety

Before any sensor is read, PWM is immediately set to `min_duty` for both fan
groups (never 0%, never left floating). This closes the window where fans
could sit at 0% during sensor/WiFi initialisation.

## Dependencies (not vendored — install onto the Pico separately)

- [`umqtt.simple`](https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple) — MQTT client
- [`microdot`](https://github.com/miguelgrinberg/microdot) — lightweight web framework for the status page/API
- `onewire` + `ds18x20` — usually included in standard MicroPython firmware builds; if not, vendor from micropython-lib

Install via `mip` (MicroPython's package manager, needs WiFi) directly on
the Pico, or download and copy into `src/lib/` before uploading. Not
committed to this repo to keep it small and avoid licensing/version drift —
pin versions in your own notes once you've picked them.

## Status / API

`GET /status` returns the same JSON shape published to MQTT, plus current
override state per fan group:

```json
{
  "rack_temp": 32.4,
  "outside_temp": 21.1,
  "groups": {
    "intake": {"duty": 65, "rpm": [1340, 1355], "override": null},
    "exhaust": {"duty": 65, "rpm": [1290, 1310],
                "override": {"duty": 0, "expires_in_s": 341}}
  },
  "detected_sensors": [
    {"rom": "28-000001a2b3c4", "temp": 32.4, "configured": true},
    {"rom": "28-000005d6e7f8", "temp": 21.1, "configured": true}
  ]
}
```

`POST /override` — body `{"group": "exhaust", "duty": 0, "duration_s": 600}`
`POST /override/cancel` — body `{"group": "exhaust"}`

## Sensor discovery

`sensors.rack` / `sensors.outside` in `config.json` must be the DS18B20 ROM
codes of your physical sensors. Since the rack usually isn't reachable for a
REPL/USB session, discovery doesn't require one: the 1-Wire bus is scanned
on every boot regardless of what's configured, and **every** ROM code seen —
matched to a config entry or not — is published live in `detected_sensors`
(status page and MQTT). A configured ROM that isn't found is a boot-time
warning, not a crash.

Workflow: boot with placeholder/empty ROM codes, open the status page, note
the ROM codes under "Detected 1-Wire sensors", touch a physical sensor and
watch which live temp reading moves to tell rack from outside, paste the
codes into `config.json`, reboot.

If `sensors.rack`'s ROM isn't currently matched, the control loop has no
temperature signal to act on and fails safe to `max_duty` (loud is a safer
failure mode than silently underventilating) — see `main.py`.

## Testing

This targets MicroPython on a Pico W — it does not run on a desktop, and
the PyCharm MicroPython plugin only gives stub-based autocomplete plus a
REPL/upload connection to a *physically attached* board. There is no
Windows/PyCharm way to actually execute `main.py` without a Pico.

What `tests/` gives you instead: `machine`, `onewire`, `ds18x20`, and
`network` don't exist outside MicroPython, so `tests/stubs/` provides
minimal stand-ins (added to `sys.path` by `tests/conftest.py`) purely so
`src/` modules can be *imported* under CPython. `microdot` (a real runtime
dependency, not a stub — see "Dependencies" above) happens to also run
under plain CPython, so `web.py`'s actual route handlers are exercised
through microdot's own `test_client`, not reimplemented.

This validates: curve/hysteresis math, override lifecycle and expiry,
config validation, sensor ROM matching/discovery, status JSON shape, and
the web API's request handling and validation.

This does **not** validate, and cannot: real PWM signal quality, actual
tach pulse counts against physical fans, real 1-Wire bus timing/CRC, or
real WiFi/MQTT behavior. Flashing to the actual board remains the final
integration test.

Setup (uses the project's `.venv`, not the system Python):

```
.venv\Scripts\pip install -r requirements-test.txt
.venv\Scripts\python -m pytest
```

## Not yet built / open follow-ups

- [ ] Actual duty% numbers for `min_duty`/`max_duty` — to be determined
      empirically using the override feature, then written into
      `config.json`.
- [ ] Optional: use rack-vs-outside delta to modulate the curve (deferred,
      see "Control logic" above).
- [ ] Optional: stall detection / fault flag in MQTT payload (deferred).
- [ ] Optional: persist override to survive intentional reboots — currently
      deliberately not implemented.

## License

MIT — see `LICENSE`.
