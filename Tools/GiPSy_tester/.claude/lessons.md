# Lessons learned

## First connect after flashing needs a full power cycle

After flashing firmware for the first time, the board comes up in
bootloader mode and this app's sync probe correctly detects it.
Jumping from bootloader to app (or just re-probing) is not enough to
get MAVLink flowing on the USB CDC port — the board needs a full
power cycle (unplug/replug USB) before the app's MAVLink stream
becomes visible. Likely cause: the USB peripheral/clock state left
behind by the bootloader isn't fully reset by a soft jump into the
app, so re-enumeration is incomplete until power is actually
removed.

Practical effect: don't read "no MAVLink after apparent bootloader
exit" as a firmware bug — try a full unplug/replug first. The
bootloader-detected status message in `gui.py` now says this
explicitly.
