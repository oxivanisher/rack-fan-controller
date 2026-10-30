"""Thin, fault-tolerant wrapper around umqtt.simple.

Design goal: the control loop must NEVER block or fail because MQTT/network
is unavailable. Every public method here catches its own exceptions and
returns a bool rather than raising, reconnect attempts are rate-limited so a
persistently-down broker doesn't waste cycles, and every network operation
has a timeout so it can't outlast the hardware watchdog (see main.py).
"""

import time
import json

import dns_lookup

try:
    from umqtt.simple import MQTTClient
except ImportError:
    MQTTClient = None  # allows the rest of the app to run/test without it

# Per socket operation. umqtt.simple keeps this on the socket after connect,
# so it covers publishes too. Worst case for a reconnect attempt is about 5s
# (DNS 1s + TCP connect 2s + CONNACK 2s): writes that follow a CONNACK land in
# an empty send buffer. main.py feeds the 8s watchdog right before this runs.
SOCKET_TIMEOUT_S = 2


class StatusPublisher:
    def __init__(self, mqtt_cfg, wlan=None):
        """wlan: the WLAN from boot.connect(), or None if WiFi isn't
        configured (publishing then simply never happens).
        """
        self._cfg = mqtt_cfg
        self._wlan = wlan
        self._client = None
        self._last_attempt_ms = 0
        self._min_retry_interval_ms = mqtt_cfg.get("reconnect_min_interval_s", 15) * 1000
        self._last_broker_ip = None  # survives DNS outages, not reboots

    def _broker_address(self):
        """Resolve the broker on every connect attempt so a moved broker gets
        picked up, falling back to the last good IP while DNS is down.
        Returns None if there's nothing to connect to yet.
        """
        broker = self._cfg["broker"]
        if dns_lookup.is_ip(broker):
            return broker

        ip = dns_lookup.resolve(broker, self._wlan.ifconfig()[3])
        if ip is not None:
            self._last_broker_ip = ip
            return ip

        if self._last_broker_ip is not None:
            print("Using last known broker IP", self._last_broker_ip)
        return self._last_broker_ip

    def _close_client(self, client):
        # Dropping the reference isn't enough: lwIP has a small, fixed number
        # of sockets, and a long outage would otherwise leave a trail of them.
        try:
            if client is not None and client.sock is not None:
                client.sock.close()
        except Exception as e:
            print("MQTT socket close failed:", e)

    def _connect(self):
        if MQTTClient is None:
            return False

        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_attempt_ms) < self._min_retry_interval_ms:
            return False  # rate-limited, don't hammer a dead broker
        self._last_attempt_ms = now

        client = None
        try:
            server = self._broker_address()
            if server is None:
                print("MQTT broker %s not resolved yet" % self._cfg["broker"])
                return False

            client = MQTTClient(
                client_id=self._cfg["client_id"],
                server=server,
                port=self._cfg.get("port", 1883),
                user=self._cfg.get("username"),
                password=self._cfg.get("password"),
                keepalive=30,
            )
            lwt_topic = self._cfg["topic"] + "/lwt"
            client.set_last_will(lwt_topic, b"offline", retain=True)
            client.connect(timeout=SOCKET_TIMEOUT_S)
            client.publish(lwt_topic, b"online", retain=True)
            self._client = client
            return True
        except Exception as e:
            print("MQTT connect failed:", e)
            self._close_client(client)
            self._client = None
            return False

    def try_publish(self, status_dict):
        """Best-effort publish. Returns True on success, False otherwise.
        Never raises.
        """
        if not self._cfg.get("enabled", False):
            return False

        if self._wlan is None or not self._wlan.isconnected():
            self._close_client(self._client)  # won't survive the link change
            self._client = None
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
            self._close_client(self._client)
            self._client = None  # force reconnect next time
            return False
