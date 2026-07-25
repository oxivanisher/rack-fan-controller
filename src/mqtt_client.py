"""Thin, fault-tolerant wrapper around umqtt.simple.

Design goal: the control loop must NEVER block or fail because MQTT/network
is unavailable. Every public method here catches its own exceptions and
returns a bool rather than raising, and reconnect attempts are rate-limited
so a persistently-down broker doesn't waste cycles.
"""

import time
import json

try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None  # allows the rest of the app to run/test without it


class StatusPublisher:
    def __init__(self, mqtt_cfg):
        self._cfg = mqtt_cfg
        self._client = None
        self._last_attempt_ms = 0
        self._min_retry_interval_ms = mqtt_cfg.get("reconnect_min_interval_s", 15) * 1000

    def _connect(self):
        if MQTTClient is None:
            return False

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_attempt_ms) < self._min_retry_interval_ms:
            return False  # rate-limited, don't hammer a dead broker
        self._last_attempt_ms = now

        try:
            client = MQTTClient(
                client_id=self._cfg["client_id"],
                server=self._cfg["broker"],
                port=self._cfg.get("port", 1883),
                user=self._cfg.get("username"),
                password=self._cfg.get("password"),
                keepalive=30,
            )
            lwt_topic = self._cfg["topic"] + "/lwt"
            client.set_last_will(lwt_topic, b"offline", retain=True)
            client.connect()
            client.publish(lwt_topic, b"online", retain=True)
            self._client = client
            return True
        except Exception as e:
            print("MQTT connect failed:", e)
            self._client = None
            return False

    def try_publish(self, status_dict):
        """Best-effort publish. Returns True on success, False otherwise.
        Never raises.
        """
        if not self._cfg.get("enabled", False):
            return False

        if self._client is None:
            if not self._connect():
                return False

        try:
            payload = json.dumps(status_dict)
            self._client.publish(self._cfg["topic"], payload)
            return True
        except Exception as e:
            print("MQTT publish failed:", e)
            self._client = None  # force reconnect next time
            return False
