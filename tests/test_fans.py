import pytest

from fans import (
    FanGroup,
    TachCounter,
    compute_curve_fraction,
    compute_fraction,
    duty_for_fraction,
    duty_percent_to_u16,
)

CURVE = {"min_temp": 30, "max_temp": 35, "hysteresis": 0.5}


def test_duty_percent_to_u16_clamps_and_scales():
    assert duty_percent_to_u16(-10) == 0
    assert duty_percent_to_u16(0) == 0
    assert duty_percent_to_u16(100) == 65535
    assert duty_percent_to_u16(150) == 65535
    assert duty_percent_to_u16(50) == int(0.5 * 65535)


def test_curve_below_min_temp_uses_fraction_zero():
    fraction, _ = compute_curve_fraction(20, CURVE, last_fraction=0.4, last_temp_for_hysteresis=None)
    assert fraction == 0.0


def test_curve_exactly_at_min_temp_uses_fraction_zero():
    # README contract is "<=", not "<" — exercise the boundary itself, not
    # just an interior point, so a boundary-operator typo gets caught.
    fraction, _ = compute_curve_fraction(
        CURVE["min_temp"], CURVE, last_fraction=0.4, last_temp_for_hysteresis=None
    )
    assert fraction == 0.0


def test_curve_above_max_temp_uses_fraction_one():
    fraction, _ = compute_curve_fraction(40, CURVE, last_fraction=0.4, last_temp_for_hysteresis=None)
    assert fraction == 1.0


def test_curve_exactly_at_max_temp_uses_fraction_one():
    fraction, _ = compute_curve_fraction(
        CURVE["max_temp"], CURVE, last_fraction=0.4, last_temp_for_hysteresis=None
    )
    assert fraction == 1.0


def test_curve_linear_interpolation_midpoint():
    fraction, temp = compute_curve_fraction(32.5, CURVE, last_fraction=0.4, last_temp_for_hysteresis=None)
    assert fraction == pytest.approx(0.5)  # halfway between min_temp=30 and max_temp=35
    assert temp == 32.5


def test_curve_hysteresis_tracks_rises_immediately():
    # Rising is never deadbanded, even by a tiny amount, so duty ramps
    # smoothly instead of stair-stepping.
    fraction, temp = compute_curve_fraction(32.31, CURVE, last_fraction=0.4, last_temp_for_hysteresis=32.3)
    assert fraction == pytest.approx((32.31 - 30) / 5)
    assert temp == 32.31


def test_curve_hysteresis_holds_last_fraction_on_small_drop():
    # last_temp_for_hysteresis=32.8, hysteresis=0.5 -> needs to fall below 32.3 to release
    fraction, temp = compute_curve_fraction(32.5, CURVE, last_fraction=0.56, last_temp_for_hysteresis=32.8)
    assert fraction == 0.56
    assert temp == 32.8


def test_curve_hysteresis_releases_drop_outside_deadband():
    fraction, temp = compute_curve_fraction(32.2, CURVE, last_fraction=0.56, last_temp_for_hysteresis=32.8)
    assert fraction != 0.56
    assert temp == 32.2


def test_compute_fraction_fails_safe_to_one_when_control_temp_missing():
    fraction, hysteresis_temp = compute_fraction(None, CURVE, last_fraction=0.4, last_temp_for_hysteresis=31.0)
    assert fraction == 1.0
    assert hysteresis_temp is None


def test_compute_fraction_delegates_to_curve_when_control_temp_present():
    fraction, temp = compute_fraction(20, CURVE, last_fraction=0.4, last_temp_for_hysteresis=None)
    assert fraction == 0.0
    assert temp == 20


def test_duty_for_fraction_maps_onto_groups_own_range():
    assert duty_for_fraction(0.0, min_duty=20, max_duty=100) == 20
    assert duty_for_fraction(1.0, min_duty=20, max_duty=100) == 100
    assert duty_for_fraction(0.5, min_duty=20, max_duty=100) == pytest.approx(60)

    # Different group, same fraction -> its own range, not the other group's.
    assert duty_for_fraction(0.5, min_duty=10, max_duty=50) == pytest.approx(30)


def test_fan_group_defaults_to_full_duty_range():
    fg = FanGroup("intake", pwm_pin=15, tach_pins=[14, 13])
    assert fg.min_duty == 0
    assert fg.max_duty == 100


def test_fan_group_stores_its_own_duty_range():
    fg = FanGroup("intake", pwm_pin=15, tach_pins=[14, 13], min_duty=30, max_duty=80)
    assert fg.min_duty == 30
    assert fg.max_duty == 80


def test_fan_group_set_duty_percent_updates_pwm_and_state():
    fg = FanGroup("intake", pwm_pin=15, tach_pins=[14, 13])
    fg.set_duty_percent(65)
    assert fg.current_duty == 65
    assert fg._pwm.duty_u16() == duty_percent_to_u16(65)
    assert fg._pwm.freq() == 25000


def test_fan_group_override_lifecycle():
    fg = FanGroup("exhaust", pwm_pin=17, tach_pins=[16, 12])
    assert not fg.override_active()
    assert fg.override_seconds_remaining() is None

    fg.set_override(duty_percent=0, duration_s=600)
    assert fg.override_active()
    assert fg.override["duty"] == 0
    assert 0 < fg.override_seconds_remaining() <= 600

    fg.cancel_override()
    assert not fg.override_active()
    assert fg.override_seconds_remaining() is None


def test_fan_group_override_expires_on_its_own(monkeypatch):
    import time as time_mod

    fg = FanGroup("exhaust", pwm_pin=17, tach_pins=[16, 12])
    fg.set_override(duty_percent=0, duration_s=1)
    assert fg.override_active()

    real_ticks_ms = time_mod.ticks_ms
    monkeypatch.setattr(time_mod, "ticks_ms", lambda: real_ticks_ms() + 5000)

    assert not fg.override_active()
    assert fg.override is None  # cleaned up, not just reported inactive


def test_tach_counter_converts_pulses_to_rpm():
    tc = TachCounter(pin_num=14)
    for _ in range(20):  # 2 pulses/revolution -> 10 revolutions
        tc._pin.trigger_irq()

    rpm = tc.rpm_since_last(elapsed_s=1)
    assert rpm == 600  # 10 rev in 1s == 600 rpm


def test_tach_counter_resets_count_after_read():
    tc = TachCounter(pin_num=14)
    tc._pin.trigger_irq()
    tc.rpm_since_last(elapsed_s=1)

    assert tc.rpm_since_last(elapsed_s=1) == 0


def test_fan_group_read_rpms_returns_one_value_per_tach_pin():
    fg = FanGroup("intake", pwm_pin=15, tach_pins=[14, 13])
    assert fg.read_rpms() == [0, 0]


def test_fan_group_supports_more_than_two_fans_per_group():
    # tach_pins is a plain list consumed generically — 3 fans (or more) on
    # one shared PWM line works with zero code changes, only extra wiring
    # (one more tach GPIO + pull-up) and config.json entries. See WIRING.md
    # "Scaling to 3+ fans per group".
    fg = FanGroup("intake", pwm_pin=15, tach_pins=[14, 13, 18])
    assert len(fg.read_rpms()) == 3

    fg.set_duty_percent(70)
    assert fg._pwm.duty_u16() == duty_percent_to_u16(70)  # still one shared PWM line
