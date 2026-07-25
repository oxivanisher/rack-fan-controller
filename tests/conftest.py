"""Makes src/ modules importable under plain CPython/pytest.

This project targets MicroPython on a Pico W and cannot actually run on a
desktop — see README.md "Testing". This harness only lets the *pure logic*
(curve math, override lifecycle, config validation, status shape) be
exercised on Windows without hardware. It does not, and cannot, validate
real PWM/tach/1-Wire/WiFi behavior — that only happens on the real board.

Two things stdlib doesn't provide, so we provide them here:
- `machine`/`onewire`/`ds18x20`/`network` don't exist in CPython at all ->
  stubs/ provides minimal stand-ins, added to sys.path.
- MicroPython's `time` module has extra tick-arithmetic helpers
  (ticks_ms/ticks_diff/ticks_add/sleep_ms) that CPython's `time` lacks ->
  patched directly onto the real, already-imported `time` module (not
  shadowed) so every other use of `time` keeps working unmodified.
"""

import sys
import time as _time
from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_STUBS_DIR = _TESTS_DIR / "stubs"
_SRC_DIR = _TESTS_DIR.parent / "src"

for _p in (str(_STUBS_DIR), str(_SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

if not hasattr(_time, "ticks_ms"):
    _time.ticks_ms = lambda: int(_time.monotonic() * 1000)
if not hasattr(_time, "ticks_diff"):
    _time.ticks_diff = lambda a, b: a - b
if not hasattr(_time, "ticks_add"):
    _time.ticks_add = lambda a, ms: a + ms
if not hasattr(_time, "sleep_ms"):
    _time.sleep_ms = lambda ms: _time.sleep(ms / 1000)
