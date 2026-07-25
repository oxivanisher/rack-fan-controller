"""Best-effort WiFi connect at boot.

Deliberately does NOT block forever or crash the board if WiFi is
unavailable — the control loop must be able to run headless. main.py should
tolerate wifi being disconnected (MQTT/web will simply stay offline until
it reconnects).
"""

import network
import time


def connect(ssid, password, timeout_s=15):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        return wlan

    wlan.connect(ssid, password)

    start = time.ticks_ms()
    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), start) > timeout_s * 1000:
            print("WiFi connect timed out, continuing without network")
            break
        time.sleep_ms(200)

    if wlan.isconnected():
        print("WiFi connected:", wlan.ifconfig())
    return wlan
