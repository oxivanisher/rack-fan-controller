"""Exercises web.py's actual route handlers via microdot's own TestClient
(microdot.test_client) — no request ever hits a real socket. microdot is a
real runtime dependency (see README.md "Dependencies"), not a stub, and
happens to run fine under plain CPython, so this tests production code
directly.
"""

import asyncio
import json

import pytest
from microdot.test_client import TestClient

import web
from fans import FanGroup


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def client():
    fan_groups = {
        "intake": FanGroup("intake", pwm_pin=15, tach_pins=[14, 13]),
        "exhaust": FanGroup("exhaust", pwm_pin=17, tach_pins=[16, 12]),
    }
    status = {"rack_temp": 32.4, "outside_temp": 21.1, "groups": {}, "detected_sensors": []}
    web.init(fan_groups, lambda: status)
    return TestClient(web.app), fan_groups


def test_status_returns_the_shared_status_object(client):
    test_client, _ = client
    res = run(test_client.get("/status"))
    assert res.status_code == 200
    assert res.json["rack_temp"] == 32.4


def test_index_serves_html_page(client):
    test_client, _ = client
    res = run(test_client.get("/"))
    assert res.status_code == 200
    assert "Rack Fan Controller" in res.text


def test_set_override_applies_to_the_named_fan_group(client):
    test_client, fan_groups = client
    res = run(
        test_client.post(
            "/override",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"group": "exhaust", "duty": 0, "duration_s": 600}),
        )
    )
    assert res.status_code == 200
    assert fan_groups["exhaust"].override_active()
    assert fan_groups["exhaust"].override["duty"] == 0


def test_set_override_rejects_unknown_group(client):
    test_client, _ = client
    res = run(
        test_client.post(
            "/override",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"group": "bogus", "duty": 0, "duration_s": 600}),
        )
    )
    assert res.status_code == 400


def test_set_override_rejects_duty_out_of_range(client):
    test_client, _ = client
    res = run(
        test_client.post(
            "/override",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"group": "intake", "duty": 150, "duration_s": 600}),
        )
    )
    assert res.status_code == 400


def test_set_override_rejects_non_positive_duration(client):
    test_client, _ = client
    res = run(
        test_client.post(
            "/override",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"group": "intake", "duty": 50, "duration_s": 0}),
        )
    )
    assert res.status_code == 400


def test_cancel_override_clears_it(client):
    test_client, fan_groups = client
    fan_groups["intake"].set_override(duty_percent=0, duration_s=600)

    res = run(
        test_client.post(
            "/override/cancel",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"group": "intake"}),
        )
    )

    assert res.status_code == 200
    assert not fan_groups["intake"].override_active()
