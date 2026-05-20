# Generic GPIO falling-edge -> USB serial line emitter (Raspberry Pi Pico, MicroPython).
#
# Each configured pin is held HIGH by an internal pull-up while idle. A
# dry-contact closure to GND drives the pin LOW; on that HIGH->LOW (falling)
# edge -- after debounce -- the pin's label is printed to USB serial as one
# line. Any USB-serial host can read these lines.
#
# This firmware is intentionally generic: it does not know what the signals
# mean. To adapt it, edit PINS below -- map each GPIO number to whatever label
# the host expects. Defaults match the Pachislot data counter wiring.
#
#   GP2  <- IN   (medal-in pulse)
#   GP3  <- OUT  (medal-out pulse)
#   GP4  <- RB   (regular bonus)
#   GP5  <- BB   (big bonus)
#   GND  <- common return
#
# The on-board LED is lit at boot and toggles on every emitted edge, so the
# board's behaviour is visible without a serial monitor.

import time
from machine import Pin

# (label, gpio): label is the exact text emitted on a falling edge.
PINS = (
    ("IN",  2),
    ("OUT", 3),
    ("RB",  4),
    ("BB",  5),
)

DEBOUNCE_MS = 20   # further edges on the same pin within this window are ignored
POLL_MS = 2        # loop pause; short enough not to miss contact pulses

led = Pin("LED", Pin.OUT)
inputs = [(label, Pin(gp, Pin.IN, Pin.PULL_UP)) for label, gp in PINS]
last_level = {label: pin.value() for label, pin in inputs}
last_edge_ms = {label: 0 for label, _ in inputs}

print("READY")
led.on()

while True:
    now = time.ticks_ms()
    for label, pin in inputs:
        level = pin.value()
        if level == last_level[label]:
            continue
        if time.ticks_diff(now, last_edge_ms[label]) < DEBOUNCE_MS:
            continue
        last_edge_ms[label] = now
        last_level[label] = level
        if level == 0:          # HIGH -> LOW: falling edge
            print(label)
            led.toggle()
    time.sleep_ms(POLL_MS)
