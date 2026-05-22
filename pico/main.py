# Pachislot external-output reader for Raspberry Pi Pico (MicroPython).
#
# Pachislot machines typically expose four dry-contact outputs that close
# to GND when an event occurs. Connect each signal to a Pico GPIO and a
# common GND. Internal pull-ups keep the pin HIGH while idle; a closure
# pulls it LOW.
#
#   GP2  <- IN   (medal-in pulse)
#   GP3  <- OUT  (medal-out pulse)
#   GP4  <- RB   (regular bonus)
#   GP5  <- BB   (big bonus)
#   GND  <- common return
#
# On a HIGH->LOW edge (debounced), the pin's event name is printed to USB
# serial, one per line. The Pi 5 host parses these via app/serial_reader.py.

import time
from machine import Pin

EVENTS = (
    ("IN", 2),
    ("OUT", 3),
    ("RB", 4),
    ("BB", 5),
)

DEBOUNCE_MS = 20

led = Pin("LED", Pin.OUT)

pins = [(name, Pin(gp, Pin.IN, Pin.PULL_UP)) for name, gp in EVENTS]

state = {name: pin.value() for name, pin in pins}
last_change = {name: 0 for name, _ in pins}

# イベント回数
count = {name: 0 for name, _ in pins}

print("READY")

led.on()

while True:
    t = time.ticks_ms()

    for name, pin in pins:
        v = pin.value()

        # 状態変化 + デバウンス
        if v != state[name] and time.ticks_diff(t, last_change[name]) >= DEBOUNCE_MS:
            last_change[name] = t
            state[name] = v

            # HIGH -> LOW
            if v == 0:
                count[name] += 1

                print("{} {}".format(name, count[name]))

                led.toggle()

    time.sleep_ms(2)
