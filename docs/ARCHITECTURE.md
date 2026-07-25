# Architecture / Data Flow

## Main loop (runs regardless of WiFi/MQTT state)

```
every poll_interval_s:
  1. Read rack_temp, outside_temp from DS18B20 bus
  2. For each fan group (intake, exhaust):
       if override active and not expired:
           duty = override.duty
       else:
           duty = curve(rack_temp)     # see README "Control logic"
       apply_pwm(group, duty)
       rpm = read_tach(group)          # both fans in group, individually
  3. Build status dict (temps, duties, rpms, override state)
  4. Best-effort: publish status dict as MQTT JSON payload
       (wrapped in try/except — failure here must never block step 1-3
        on the next iteration)
  5. Feed hardware watchdog
```

The web server (`web.py`, microdot) runs as a second concern reading/writing
the same in-memory state object main.py owns — either via a small shared
state module, or by running microdot's async loop cooperatively alongside
the control loop (implementation detail left to `main.py`; MicroPython's
`uasyncio` is the natural fit if both need to run concurrently).

## Override lifecycle

```
POST /override {"group": "exhaust", "duty": 0, "duration_s": 600}
  -> state.overrides["exhaust"] = {"duty": 0, "expires_at": now + 600}

Each control loop iteration:
  -> if state.overrides[group] exists and now < expires_at: use override duty
  -> else: delete the override entry (if present) and fall back to curve

POST /override/cancel {"group": "exhaust"}
  -> immediately deletes state.overrides["exhaust"]

On boot:
  -> state.overrides = {}   # always starts empty, never loaded from disk
```

## Why MQTT publish is "fire and forget"

The control loop's correctness must never depend on network availability.
`mqtt_client.py` should expose something like:

```python
def try_publish(payload: dict) -> bool:
    try:
        # connect if not connected, publish, return True
        ...
    except Exception:
        return False   # caller logs and moves on, does not retry inline
```

Reconnection attempts should be rate-limited (e.g. don't attempt a fresh
MQTT reconnect more than once every N seconds) so a persistently-down broker
doesn't waste control-loop cycles retrying every 5 seconds forever.

## MQTT topic

Single JSON blob published to one topic, matching `GET /status` shape
(minus the override detail, which is arguably local-only — decide based on
whether you want override state visible in Influx too; harmless either way).

Suggested topic: `rack/status` (configurable in `config.json`).

Last Will and Testament: configure the MQTT client connect call with
`will_topic="rack/status/lwt"`, `will_message="offline"`, `will_retain=True`,
and publish `"online"` to that same topic (retained) right after connecting.
Gives free online/offline monitoring in whatever subscribes.
