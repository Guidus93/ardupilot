# Lessons learned

## "Needs a power cycle after flashing" was a misdiagnosis

Earlier this looked like: after flashing, MAVLink wouldn't appear until
a full USB unplug/replug, so we assumed a bootloader->app soft jump left
the USB peripheral in a bad state. That was wrong.

What's actually going on: after flashing or a power-up, the AP_Bootloader
sits in its sync loop for `HAL_BOOTLOADER_TIMEOUT` (5s default, see
`Tools/AP_Bootloader/AP_Bootloader.cpp:54`) and then jumps to the app on
its own. ArduPilot's docs say the same -- "It usually takes a few seconds
for the bootloader to exit and enter the main code after programming or a
power-up. Wait to press CONNECT until this occurs."
(https://ardupilot.org/copter/docs/common-loading-firmware-onto-pixhawk.html)

So the board wasn't stuck -- the operator (and our tool) was just probing
too early, during the normal 5s boot window.

Worse, our old up-front bootloader probe could *extend* the stall: a
mistimed `GET_SYNC`+`EOC` whose `EOC` misses the bootloader's 2ms
`wait_for_eoc(2)` tolerance hits the `cmd_bad` path, which resets
`timeout = original_timeout` and restarts the 5s countdown
(`bl_protocol.cpp:1229-1230`). Repeated probing = board kept in bootloader.

## Fix: patient connect instead of an up-front probe

Connect no longer probes the bootloader first. It waits for a MAVLink
heartbeat, retrying for `BOOT_WAIT_S` (15s, covering the 5s window +
USB re-enumeration) and re-scanning ports each attempt -- the USB CDC
port can come back on a *different* COM number across the
bootloader->app jump (see the "Windows 11 won't connect after flashing"
discuss.ardupilot.org thread). The heartbeat wait only reads, so it
can't disturb a board still counting down.

Only if the entire window elapses with no heartbeat do we probe the
bootloader once, for diagnosis: still-in-sync -> "flash firmware";
otherwise -> "no MAVLink, check firmware/power". By then resetting the
bootloader timeout no longer matters, since the board clearly isn't
booting on its own.

Practical effect: the operator just plugs in and clicks Connect. The UI
shows a "waiting for board to boot (Ns left)" countdown so they don't
panic and start yanking cables during the normal boot delay.

## setup.bat: a stale `py` launcher can shadow a working `python`

Seen on a factory PC with Python 3.14.6: `setup.bat` failed with
`did not find executable at 'C:\Python.exe'` even though `python
--version` worked fine directly. Cause: the `py` launcher was
registered on PATH from some earlier/removed Python install and
pointed at a path that no longer existed. `setup.bat` only checked
`where py` (does the command exist), not whether it actually runs --
so it always picked the broken `py -3` first and never fell back to
the working `python`.

Fix: check with `py -3 --version` (actually runs it) instead of
`where py` (only checks PATH). Also added a self-heal: if `.venv`
already exists but its `python.exe` doesn't run (e.g. created earlier
by the broken launcher, which can bake a bad interpreter path into
the venv via `__PYVENV_LAUNCHER__`), wipe and recreate it rather than
limping along on a broken venv forever.

Practical effect: if `setup.bat` ever fails again with "did not find
executable", the fix is almost always a stale/broken `py` launcher
registration on that machine, not a problem with this tool's
dependencies -- `python --version` working directly is the tell.

## When a PASS gate has several data sources, all of them must gate it

The IMU/baro chip-type text sometimes never appeared even with values
showing and LEDs green, and only a disconnect/reconnect ever fixed it.
First fix attempt: retry the `PARAM_REQUEST_READ` for any devid param
whose `PARAM_VALUE` reply never arrived (see health.py's
`_devid_pending`/`_retry_missing_devid_params`). That helped but didn't
fully fix it, because it treated the symptom (a dropped reply) without
noticing the actual race: `_poll_health`'s PASS condition (`all_ok` in
gui.py) only checked the 5 LED booleans. Those come from
continuously-streamed sensor messages and go green fast. The type
strings come from the *slower* `PARAM_VALUE` round trip. So as soon as
the LEDs went green -- often before the type round trip finished --
`_finish_test` fired and called `_stop_monitor()`, closing the
connection the retry needed to ever land a reply on. No amount of
retrying on the health-monitor side fixes a race that kills the
monitor before the retry gets a chance.

Fix: `all_ok` now also requires `imu1_type`/`imu2_type`/`baro_type` to
be non-empty, not just the 5 LED booleans. The disconnect/reconnect
"workaround" people found by hand wasn't fixing anything -- it was
just giving the type round trip a fresh connection and enough
wall-clock time to finish before something else raced to disconnect
it.

General lesson: when a readiness check (a PASS/ready/done gate) is
fed by several independent data sources with different latencies,
*all* of them need to be in the gate condition, not just the ones that
happen to be fastest/most visible (LEDs, in this case). A partial gate
will intermittently look "mostly done" and tear down state that a
slower source still needs.
