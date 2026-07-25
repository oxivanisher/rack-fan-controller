# Wiring

All pin numbers below are the defaults used in `config.example.json` and
referenced in the code. Change both consistently if you rewire.

The base build is 2 fans per group (4 fans total). The software already
supports 3 (or more) fans per group with **zero code changes** — see
"Scaling to 3+ fans per group" below. This doc covers wiring for both the
base 2-fan build and the 3-fan expansion.

## Pinout summary (Pico W)

| Signal | GPIO | Notes |
|---|---|---|
| 1-Wire bus (both DS18B20s) | GP4 | 4.7kΩ pull-up to 3.3V, shared by both sensors |
| Intake PWM (all intake fans) | GP15 | Direct to fan PWM pin, no level shifting needed |
| Intake fan 1 tach | GP14 | 4.7kΩ pull-up to **3.3V** (not 12V!) |
| Intake fan 2 tach | GP13 | 4.7kΩ pull-up to **3.3V** |
| Intake fan 3 tach *(optional)* | GP18 | Only needed if you add a 3rd intake fan |
| Exhaust PWM (all exhaust fans) | GP17 | Direct to fan PWM pin |
| Exhaust fan 1 tach | GP16 | 4.7kΩ pull-up to **3.3V** |
| Exhaust fan 2 tach | GP12 | 4.7kΩ pull-up to **3.3V** |
| Exhaust fan 3 tach *(optional)* | GP19 | Only needed if you add a 3rd exhaust fan |
| Pico power (VBUS) | — | Fed from 12V→5V buck converter output |

Adjust to taste — these just need to stay in sync with `config.json`. When
picking your own GPIOs (e.g. wiring a 4th fan per group later), avoid
**GP23, GP24, GP25, GP29** — on the Pico *W* specifically these are tied up
by the wireless chip / VSYS monitoring / onboard LED, not general-purpose.
Any other GPIO is fair game.

## Per-fan (4-pin) wiring

Standard PC fan 4-pin header:

1. **Black** — Ground
2. **Yellow** — +12V
3. **Green** — Tach (open-collector output, pulses 2x per revolution)
4. **Blue** — PWM input (3.3–5V logic, 25kHz expected)

The rule for any group, regardless of how many fans are in it (2, 3, or
more): **every fan's PWM line ties to the same one Pico GPIO; every fan's
tach line gets its own separate Pico GPIO + pull-up.** PWM inputs are
high-impedance logic lines (safe to gang together); tach outputs are
open-collector (garbage pulse counts if combined).

```
                              +12V PSU rail
                                   |
        +-----------+-----------+-+-----------+
        |           |           |             |  (repeat per fan)
     Fan 1 (Y)   Fan 2 (Y)   Fan 3 (Y)   Fan N (Y)
        |           |           |             |
        |     [ all 4-pin fans in this group ]
        |           |           |             |
     Fan 1 (K)   Fan 2 (K)   Fan 3 (K)   Fan N (K)
        |           |           |             |
        +-----------+-----+-----+-------------+
                          |
                   Common GND rail  -------------------- Pico GND
                   (also 12V PSU GND)

     Fan 1 (Bl) ---+
     Fan 2 (Bl) ---+---- tied together ---- Pico GPxx  (one PWM GPIO
     Fan 3 (Bl) ---+                                    for the whole group)
     Fan N (Bl) ---+

     Fan 1 (G) ---- 4.7k to 3V3 ---- Pico GPxx  (tach 1, own GPIO)
     Fan 2 (G) ---- 4.7k to 3V3 ---- Pico GPxx  (tach 2, own GPIO)
     Fan 3 (G) ---- 4.7k to 3V3 ---- Pico GPxx  (tach 3, own GPIO)
     Fan N (G) ---- 4.7k to 3V3 ---- Pico GPxx  (tach N, own GPIO)

     (Y)=Yellow +12V   (K)=blacK GND   (Bl)=Blue PWM   (G)=Green tach
```

Concretely, per group:

- Pins 1 (GND) of every fan in the group → common ground rail → also tied
  to Pico GND and 12V PSU GND (**all grounds must be common** or PWM/tach
  signals are meaningless).
- Pins 2 (+12V) of every fan in the group → 12V PSU rail directly (not
  through the Pico).
- Pins 4 (PWM) of every fan in the group → tied together → the group's
  single Pico PWM GPIO.
- Pins 3 (tach) of every fan in the group → **kept separate** → one Pico
  GPIO each, each with its own 4.7kΩ pull-up to 3.3V.

## Scaling to 3+ fans per group

Nothing in the code assumes exactly 2 fans per group — `fans.py`'s
`FanGroup` and `config.py`'s validation both treat `tach_pins` as a plain
list of any length, and every fan in the group already shares one PWM line
by design (see "Per-fan wiring" above). Going from 2 to 3 fans (or more,
later) is wiring + config only:

1. Wire the 3rd fan's PWM (blue) into the same tied-together bundle as the
   other fans in that group — no new GPIO needed.
2. Give the 3rd fan's tach (green) its own new Pico GPIO + 4.7kΩ pull-up to
   3.3V (e.g. GP18 for intake, GP19 for exhaust — see pinout table above).
3. Add that GPIO number to the group's `tach_pins` array in `config.json`:

   ```json
   "fan_groups": {
     "intake": {"pwm_pin": 15, "tach_pins": [14, 13, 18]},
     "exhaust": {"pwm_pin": 17, "tach_pins": [16, 12, 19]}
   }
   ```

4. Reboot. `GET /status` will now show 3 RPM readings for that group.

That's it — no changes to `main.py`, `fans.py`, `web.py`, etc. The same
pattern extends to a 4th, 5th, ... fan per group later: one more tach GPIO
+ pull-up, one more entry in `tach_pins`, avoiding the reserved GP23/24/25/
29. The only real ceiling is available GPIOs and how many fans you can
usefully drive off one PWM/12V rail — the Pico W has 26 usable GPIOs, so
that's a long way off for a homelab rack.

## 1-Wire bus (DS18B20 x2)

```
Pico 3V3 --+-------------------+-------------------+
           |                   |                   |
        [4.7kΩ]                |                   |
       pull-up                 |                   |
           |                   |                   |
Pico GP4 --+---- DATA ---------+---- DATA ---------+---- DATA (room for more)
                   |                     |
              DS18B20 "rack"       DS18B20 "outside"
                   |                     |
Pico GND --+-------+---------------------+
           |
   (also 12V PSU GND, common ground)
```

- All DS18B20 VDD → Pico 3.3V
- All DS18B20 GND → Pico GND
- All DS18B20 DATA → single Pico GPIO (GP4), with **one** 4.7kΩ pull-up
  resistor from that GPIO to 3.3V (one resistor total for the whole bus,
  not per sensor)
- Each sensor has a unique factory-programmed 64-bit ROM code. The bus is
  scanned on every boot regardless of what's in `config.json`; ROM codes
  that don't match a configured sensor still show up, live, in
  `GET /status` -> `detected_sensors` (and on the web status page) rather
  than crashing startup. If the rack isn't physically reachable for a REPL,
  read the ROM codes off the status page instead: touch a sensor and watch
  which reading moves to tell rack from outside, then paste the codes into
  `config.json` under `sensors.rack` / `sensors.outside` and reboot.
- If the "outside" sensor has a long cable run out of the enclosure, prefer
  shielded or twisted-pair cable if available — 1-Wire is somewhat sensitive
  to noise on long unshielded runs. Not critical at typical workshop
  distances, but cheap insurance.
- The bus supports more than 2 sensors electrically (that's the point of
  1-Wire) — adding a 3rd zone later is just another DATA tap on the same
  GP4 bus (no new GPIO, no new pull-up) plus a new name/ROM entry in
  `config.json`'s `sensors` map and wiring it into `control_sensor`/status
  handling in code if it needs to do more than sit in `detected_sensors`.

## Power

- 12V PSU → fans directly (every group) AND → 12V→5V buck converter input
- Buck converter 5V output → Pico **VBUS** pin (or VSYS with a diode, per
  your specific buck converter's output characteristics — check its output
  is clean 5V before feeding VBUS directly)
- Common ground between 12V rail, buck converter, Pico, and all fans
- More fans per group means more current draw on the 12V rail — confirm
  your PSU and wiring gauge have headroom for the total fan count (check
  each fan's rated current on its datasheet/label and sum per group), not
  just the Pico/buck converter side, before adding a 3rd fan.

## Sanity checks before first power-on

- [ ] Continuity-check that no tach line is accidentally shorted to another
      fan's tach line (this is the most common mistake when wiring groups
      of 2+ fans)
- [ ] Confirm pull-ups on tach lines go to 3.3V, not 12V
- [ ] Confirm buck converter output is actually ~5V before connecting to Pico
- [ ] Confirm common ground across every subsystem with a multimeter
      (0Ω / continuity between 12V PSU GND, Pico GND, fan GND)
- [ ] If you added a 3rd fan per group: confirm `config.json`'s
      `tach_pins` array has exactly as many entries as physical fans in
      that group, in the order you wired them (order only matters for
      matching `GET /status`'s `rpm` array position to a physical fan for
      your own sanity, not for correctness)
