# Pachislot external-output raw logger for Raspberry Pi Pico (MicroPython).
#
# Pachislot machines expose four dry-contact outputs that close to GND when an
# event occurs. Connect each signal to a Pico GPIO and a common GND. Internal
# pull-ups keep a pin HIGH while idle; a contact closure pulls it LOW.
#
#   GP2  <- IN   (medal-in pulse: one pulse per bet medal at lever-on)
#   GP3  <- OUT  (medal-out pulse)
#   GP4  <- RB   (regular bonus: held LOW for the whole bonus -- level signal)
#   GP5  <- BB   (big bonus: held LOW for the whole bonus -- level signal)
#   GND  <- common return
#
# This firmware emits a CSV raw log to USB serial, one event per line. Both the
# FALL (HIGH->LOW) and RISE (LOW->HIGH) edges of every signal are reported, so
# the Pi 5 host can reason about pulse width, chatter, stuck contacts and
# bonus duration -- the Pico itself does not finalise game results.
#
# Boot header line (lets the host detect the format):
#
#   READY,format=v1,fields=timestamp_ms,game_id,event,edge,seq
#
# Event line:
#
#   timestamp_ms,game_id,event,edge,seq
#
#     timestamp_ms  ms since boot (time.ticks_ms())
#     game_id       provisional game number assigned on the Pico (see below)
#     event         IN / OUT / RB / BB
#     edge          FALL (HIGH->LOW) or RISE (LOW->HIGH)
#     seq           per-(game_id, event) running counter

import time
from machine import Pin

EVENTS = (
    ("IN", 2),
    ("OUT", 3),
    ("RB", 4),
    ("BB", 5),
)

DEBOUNCE_MS = 20        # ignore further edges on the same pin within this window
POLL_MS = 2             # loop pause; short enough not to miss contact pulses

# A new game is recognised when an IN FALL arrives at least this long after the
# previous IN FALL. The 3 closely-spaced IN pulses of a 3-medal bet stay in the
# same game; the next lever-on (a longer gap away) starts the next game.
IN_GROUP_GAP_MS = 300

led = Pin("LED", Pin.OUT)

pins = [(name, Pin(gp, Pin.IN, Pin.PULL_UP)) for name, gp in EVENTS]

# Idle level is HIGH; remember it so the first real closure registers as FALL.
state = {name: pin.value() for name, pin in pins}
last_edge_ms = {name: 0 for name, _ in pins}

# Provisional game numbering. game_id starts at 0 and becomes 1 on the first IN
# FALL; events seen before any IN (e.g. a stray OUT) are emitted under game 0.
game_id = 0
last_in_fall_ms = 0
have_in_fall = False

# seq is the per-(game_id, event) FALL counter. RISE reuses the FALL's value,
# so seq is incremented on FALL only and all counters reset on a new game.
seq = {name: 0 for name, _ in pins}

print("READY,format=v1,fields=timestamp_ms,game_id,event,edge,seq")

led.on()

while True:
    now = time.ticks_ms()

    for name, pin in pins:
        level = pin.value()
        if level == state[name]:
            continue
        if time.ticks_diff(now, last_edge_ms[name]) < DEBOUNCE_MS:
            continue

        last_edge_ms[name] = now
        state[name] = level

        if level == 0:
            # HIGH -> LOW: falling edge.
            if name == "IN":
                # First IN FALL ever, or one far enough from the previous IN
                # FALL, opens a new game and resets every seq counter.
                if not have_in_fall or \
                        time.ticks_diff(now, last_in_fall_ms) >= IN_GROUP_GAP_MS:
                    game_id += 1
                    for ev in seq:
                        seq[ev] = 0
                have_in_fall = True
                last_in_fall_ms = now

            seq[name] += 1
            print("{},{},{},FALL,{}".format(now, game_id, name, seq[name]))
        else:
            # LOW -> HIGH: rising edge; reuse the matching FALL's seq value.
            print("{},{},{},RISE,{}".format(now, game_id, name, seq[name]))

        led.toggle()

    time.sleep_ms(POLL_MS)
