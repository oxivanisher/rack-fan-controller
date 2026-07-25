"""Test-only stand-in for MicroPython's `machine` module.

Real behavior (actual GPIO levels, actual PWM output electrical
characteristics, actual watchdog reset) can't be meaningfully faked on a
desktop — this only exists so src/ modules can be imported and their pure
logic exercised under CPython/pytest. It is NOT a substitute for testing on
real hardware.
"""


class Pin:
    IN = "IN"
    OUT = "OUT"
    PULL_UP = "PULL_UP"
    PULL_DOWN = "PULL_DOWN"
    IRQ_FALLING = "IRQ_FALLING"
    IRQ_RISING = "IRQ_RISING"

    def __init__(self, id, mode=None, pull=None):
        self.id = id
        self.mode = mode
        self.pull = pull
        self._value = 0
        self._irq_handler = None

    def value(self, v=None):
        if v is None:
            return self._value
        self._value = v

    def irq(self, trigger=None, handler=None):
        self._irq_handler = handler

    def trigger_irq(self):
        """Test helper: simulate one falling edge by invoking the
        registered IRQ handler, the way a real tach pulse would.
        """
        if self._irq_handler is not None:
            self._irq_handler(self)


class PWM:
    def __init__(self, pin):
        self.pin = pin
        self._freq = 0
        self._duty_u16 = 0

    def freq(self, hz=None):
        if hz is None:
            return self._freq
        self._freq = hz

    def duty_u16(self, value=None):
        if value is None:
            return self._duty_u16
        self._duty_u16 = value

    def deinit(self):
        pass


class WDT:
    def __init__(self, id=0, timeout=8000):
        self.timeout = timeout
        self.feed_count = 0

    def feed(self):
        self.feed_count += 1
