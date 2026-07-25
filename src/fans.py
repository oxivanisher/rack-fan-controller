"""Fan group control: PWM output shared by a pair, individual tach counting.

Each FanGroup represents e.g. "intake" (2 physical fans, 1 PWM line, 2 tach
lines). PWM duty is either driven by the temperature curve or by a timed
manual override — see README.md "Control logic" for the rationale.
"""

import time
from machine import Pin, PWM

PWM_FREQ_HZ = 25000  # standard PC fan PWM frequency; keeps switching noise
                      # out of the audible range


def duty_percent_to_u16(percent):
    percent = max(0, min(100, percent))
    return int(percent / 100 * 65535)


class TachCounter:
    """Counts falling edges on a tach line between two points in time.

    2 pulses per revolution is the PC fan standard.
    """

    def __init__(self, pin_num):
        self._pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
        self._count = 0
        self._pin.irq(trigger=Pin.IRQ_FALLING, handler=self._on_pulse)

    def _on_pulse(self, pin):
        self._count += 1

    def rpm_since_last(self, elapsed_s):
        """Read and reset the pulse count, converting to RPM."""
        count = self._count
        self._count = 0
        if elapsed_s <= 0:
            return 0
        revolutions = count / 2
        return int(revolutions / (elapsed_s / 60))


class FanGroup:
    def __init__(self, name, pwm_pin, tach_pins):
        self.name = name
        self._pwm = PWM(Pin(pwm_pin))
        self._pwm.freq(PWM_FREQ_HZ)
        self._tachs = [TachCounter(p) for p in tach_pins]
        self._last_tach_read_ms = time.ticks_ms()

        self.override = None  # {"duty": int, "expires_at_ms": int} or None
        self.current_duty = 0

    def set_duty_percent(self, percent):
        self._pwm.duty_u16(duty_percent_to_u16(percent))
        self.current_duty = percent

    def set_override(self, duty_percent, duration_s):
        self.override = {
            "duty": duty_percent,
            "expires_at_ms": time.ticks_add(time.ticks_ms(), int(duration_s * 1000)),
        }

    def cancel_override(self):
        self.override = None

    def override_active(self):
        if self.override is None:
            return False
        if time.ticks_diff(self.override["expires_at_ms"], time.ticks_ms()) <= 0:
            self.override = None  # expired, clean it up
            return False
        return True

    def override_seconds_remaining(self):
        if not self.override_active():
            return None
        return max(0, time.ticks_diff(self.override["expires_at_ms"], time.ticks_ms()) // 1000)

    def read_rpms(self):
        """Returns list of RPM readings, one per tach line, and resets counters.

        Call this at most once per poll cycle — it consumes the pulse count.
        """
        now = time.ticks_ms()
        elapsed_s = time.ticks_diff(now, self._last_tach_read_ms) / 1000
        self._last_tach_read_ms = now
        return [t.rpm_since_last(elapsed_s) for t in self._tachs]


def compute_curve_duty(temp, curve_cfg, last_duty, last_temp_for_hysteresis):
    """Linear ramp with hysteresis.

    Returns (new_duty, new_temp_for_hysteresis). Caller stores the second
    value and passes it back in next time, so the hysteresis comparison is
    against the last temperature that actually caused a duty change (not
    just the last raw reading).
    """
    min_t, max_t = curve_cfg["min_temp"], curve_cfg["max_temp"]
    min_d, max_d = curve_cfg["min_duty"], curve_cfg["max_duty"]
    hysteresis = curve_cfg["hysteresis"]

    if last_temp_for_hysteresis is not None:
        if abs(temp - last_temp_for_hysteresis) < hysteresis:
            return last_duty, last_temp_for_hysteresis  # no change, inside deadband

    if temp <= min_t:
        duty = min_d
    elif temp >= max_t:
        duty = max_d
    else:
        frac = (temp - min_t) / (max_t - min_t)
        duty = min_d + frac * (max_d - min_d)

    return duty, temp
