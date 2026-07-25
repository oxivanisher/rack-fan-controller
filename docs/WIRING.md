# Wiring

All pin numbers below are the defaults used in `config.example.json` and
referenced in the code. Change both consistently if you rewire.

## Pinout summary (Pico W)

| Signal | GPIO | Notes |
|---|---|---|
| 1-Wire bus (both DS18B20s) | GP4 | 4.7kΩ pull-up to 3.3V, shared by both sensors |
| Intake PWM (both intake fans) | GP15 | Direct to fan PWM pin, no level shifting needed |
| Intake fan 1 tach | GP14 | 4.7kΩ pull-up to **3.3V** (not 12V!) |
| Intake fan 2 tach | GP13 | 4.7kΩ pull-up to **3.3V** |
| Exhaust PWM (both exhaust fans) | GP17 | Direct to fan PWM pin |
| Exhaust fan 1 tach | GP16 | 4.7kΩ pull-up to **3.3V** |
| Exhaust fan 2 tach | GP12 | 4.7kΩ pull-up to **3.3V** |
| Pico power (VBUS) | — | Fed from 12V→5V buck converter output |

Adjust to taste — these just need to stay in sync with `config.json`.

## Per-fan (4-pin) wiring

Standard PC fan 4-pin header:

1. **Black** — Ground
2. **Yellow** — +12V
3. **Green** — Tach (open-collector output, pulses 2x per revolution)
4. **Blue** — PWM input (3.3–5V logic, 25kHz expected)

For each pair (intake, exhaust):

- Pins 1 (GND) of both fans → common ground rail → also tied to Pico GND
  and 12V PSU GND (**all grounds must be common** or PWM/tach signals are
  meaningless).
- Pins 2 (+12V) of both fans → 12V PSU rail directly (not through the Pico).
- Pins 4 (PWM) of both fans → tied together → single Pico PWM GPIO for that
  group.
- Pins 3 (tach) of both fans → **kept separate** → one Pico GPIO each, each
  with its own pull-up resistor to 3.3V.

## 1-Wire bus (DS18B20 x2)

- All DS18B20 VDD → Pico 3.3V
- All DS18B20 GND → Pico GND
- All DS18B20 DATA → single Pico GPIO (GP4), with one 4.7kΩ pull-up resistor
  from that GPIO to 3.3V (one resistor total for the whole bus, not per
  sensor)
- Each sensor has a unique factory-programmed 64-bit ROM code — read these
  once during setup (a short MicroPython snippet using `onewire.scan()` will
  print them) and put them into `config.json` under `sensors.rack` /
  `sensors.outside`.
- If the "outside" sensor has a long cable run out of the enclosure, prefer
  shielded or twisted-pair cable if available — 1-Wire is somewhat sensitive
  to noise on long unshielded runs. Not critical at typical workshop
  distances, but cheap insurance.

## Power

- 12V PSU → fans directly (both pairs) AND → 12V→5V buck converter input
- Buck converter 5V output → Pico **VBUS** pin (or VSYS with a diode, per
  your specific buck converter's output characteristics — check its output
  is clean 5V before feeding VBUS directly)
- Common ground between 12V rail, buck converter, Pico, and all fans

## Sanity checks before first power-on

- [ ] Continuity-check that no tach line is accidentally shorted to another
      fan's tach line (this is the most common mistake when wiring pairs)
- [ ] Confirm pull-ups on tach lines go to 3.3V, not 12V
- [ ] Confirm buck converter output is actually ~5V before connecting to Pico
- [ ] Confirm common ground across every subsystem with a multimeter
      (0Ω / continuity between 12V PSU GND, Pico GND, fan GND)
