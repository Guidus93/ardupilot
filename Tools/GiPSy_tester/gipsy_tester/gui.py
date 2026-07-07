"""Tkinter GUI: scan a QR code, watch 5 status LEDs, get PASS/FAIL.

Production flow, driven entirely by the QR field at the top:
  1. Operator scans the unit's QR code (a keyboard-wedge scanner types
     the code + Enter into the always-focused QR entry). If the
     scanner's Enter keystroke doesn't register -- seen when Windows'
     input language isn't English and IME composition eats it -- the
     field auto-submits once it goes quiet for QR_IDLE_SUBMIT_MS
     anyway, so Enter is a nice-to-have, not a hard requirement.
  2. A valid scan (PRODUCT_WWYY_SERIAL, see qrcode_parse.py; NFKC-
     normalized there too, so full-width IME characters still parse)
     triggers a port scan and connect automatically -- no button
     presses needed. The scan is retried for QR_SCAN_RETRY_S because
     comports() can return a stale/empty result on the very first call
     right after a scan even with the board already plugged in.
  3. Connect hands the port to a MavlinkHealthMonitor, which waits out
     the bootloader boot window (retrying a heartbeat, re-scanning
     ports) instead of probing the bootloader up front. See health.py
     for why probing early is counterproductive.
  4. Once connected, every poll (250ms) checks whether all 5 LEDs are
     green; if so it's a PASS, if TEST_TIMEOUT_S elapses without that
     (or the boot window itself times out) it's a FAIL. Either way the
     result is appended to test_log.csv and the QR field clears for
     the next unit.

The Scan/Connect buttons and port dropdown still work standalone for
manual debugging outside the QR flow.
"""

from __future__ import annotations

import datetime
import time
import tkinter as tk
from tkinter import ttk

from . import port_scan, test_log
from .health import HealthSnapshot, MavlinkHealthMonitor
from .qrcode_parse import ParsedQr, parse_qr
from .test_log import TestResult

POLL_MS = 250
LED_GREEN = "#2ecc71"
LED_RED = "#e74c3c"
LED_GREY = "#95a5a6"

MAVLINK_BAUD = 57600

# How long after MAVLink connects to wait for all 5 LEDs to go green
# before giving up and logging a FAIL. Generous margin over the ~1Hz
# default stream rate for every message the LEDs depend on.
TEST_TIMEOUT_S = 8.0
# How long to leave the PASS/FAIL banner up before auto-resetting for
# the next scan.
RESULT_DISPLAY_MS = 3000

# A scanner's trailing Enter keystroke can be swallowed by IME
# composition when Windows' input language isn't English, so typing
# into the QR field auto-submits once it goes quiet for this long
# instead of strictly requiring <Return> to fire.
QR_IDLE_SUBMIT_MS = 400

# Auto-retry window for the QR-triggered port scan: comports() can
# occasionally return stale/empty results on the very first call right
# after a scan even though the board has been plugged in and
# enumerated for a while (a manual re-click of Scan a moment later
# always finds it) -- so retry instead of failing on one empty scan.
QR_SCAN_RETRY_S = 3.0
QR_SCAN_RETRY_INTERVAL_MS = 300


class LedIndicator(tk.Canvas):
    def __init__(self, master, label_text: str, size: int = 22):
        super().__init__(master, width=size, height=size, highlightthickness=0)
        pad = 2
        self._oval = self.create_oval(pad, pad, size - pad, size - pad, fill=LED_GREY, outline="#333333")
        self.label_text = label_text

    def set_state(self, ok: bool | None) -> None:
        color = LED_GREY if ok is None else (LED_GREEN if ok else LED_RED)
        self.itemconfig(self._oval, fill=color)


class GipsyTesterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GiPSy Autopilot Tester")
        self.resizable(False, False)

        self._monitor: MavlinkHealthMonitor | None = None
        self._ports: list[port_scan.CandidatePort] = []

        # Set once a QR is scanned and cleared to None once the result for
        # that unit has been logged and the field resets for the next scan.
        # A test is "in progress" whenever this is not None.
        self._current_qr: ParsedQr | None = None
        # Monotonic deadline for the LEDs to all go green once MAVLink
        # connects; None until connected, since the boot-wait phase already
        # has its own timeout in health.py.
        self._test_deadline: float | None = None
        # Monotonic deadline for _scan_for_qr_retry to keep retrying the
        # port scan right after a QR scan; set fresh each time in
        # _on_qr_scanned.
        self._scan_for_qr_deadline: float = 0.0

        self._build_widgets()
        self._on_scan()
        self._qr_entry.focus_set()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 6}

        qr_frame = ttk.Frame(self)
        qr_frame.grid(row=0, column=0, sticky="ew", **pad)
        ttk.Label(qr_frame, text="Scan QR code:", font=("", 11, "bold")).grid(row=0, column=0, padx=4)
        self._qr_var = tk.StringVar()
        self._qr_entry = ttk.Entry(qr_frame, textvariable=self._qr_var, width=30, font=("", 11))
        self._qr_entry.grid(row=0, column=1, padx=4)
        self._qr_entry.bind("<Return>", self._on_qr_scanned)
        self._qr_entry.bind("<KeyRelease>", self._on_qr_key_release)
        self._qr_idle_after_id: str | None = None

        self._result_var = tk.StringVar(value="")
        self._result_label = tk.Label(qr_frame, textvariable=self._result_var, font=("", 14, "bold"))
        self._result_label.grid(row=0, column=2, padx=12)

        top = ttk.LabelFrame(self, text="Manual controls (for debugging)")
        top.grid(row=1, column=0, sticky="ew", **pad)

        ttk.Label(top, text="Port:").grid(row=0, column=0)
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(top, textvariable=self._port_var, width=40, state="readonly")
        self._port_combo.grid(row=0, column=1, padx=4)

        ttk.Button(top, text="Scan", command=self._on_scan).grid(row=0, column=2, padx=4)
        self._connect_btn = ttk.Button(top, text="Connect", command=self._on_connect)
        self._connect_btn.grid(row=0, column=3, padx=4)

        self._autoconnect_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text="Auto-connect on scan", variable=self._autoconnect_var
        ).grid(row=1, column=1, columnspan=2, sticky="w", padx=4)

        leds = ttk.LabelFrame(self, text="Status")
        leds.grid(row=2, column=0, sticky="ew", **pad)

        self._leds: dict[str, LedIndicator] = {}
        self._detail_vars: dict[str, tk.StringVar] = {}
        detail_defaults = {
            "imu1": "-- --.--m/s²",
            "imu2": "-- --.--m/s²",
            "baro": "-- --.--hPa",
            "vbat": "--.-- V",
        }
        for i, key in enumerate(("mavlink", "imu1", "imu2", "baro", "vbat")):
            col = ttk.Frame(leds)
            col.grid(row=0, column=i, padx=14, pady=8)
            led = LedIndicator(col, key)
            led.pack()
            ttk.Label(col, text=key.upper()).pack()
            if key in detail_defaults:
                var = tk.StringVar(value=detail_defaults[key])
                ttk.Label(col, textvariable=var).pack()
                self._detail_vars[key] = var
            self._leds[key] = led

        self._status_var = tk.StringVar(value="Not connected")
        ttk.Label(self, textvariable=self._status_var, anchor="w").grid(
            row=3, column=0, sticky="ew", **pad
        )

    def _on_qr_key_release(self, _event=None) -> None:
        # Backstop for a scanner's trailing Enter keystroke getting eaten
        # by IME composition (seen with the PC's input language set to
        # Chinese): if the field goes quiet for QR_IDLE_SUBMIT_MS, submit
        # it ourselves instead of waiting for <Return> to ever fire.
        if self._qr_idle_after_id is not None:
            self.after_cancel(self._qr_idle_after_id)
        self._qr_idle_after_id = self.after(QR_IDLE_SUBMIT_MS, self._on_qr_idle_timeout)

    def _on_qr_idle_timeout(self) -> None:
        self._qr_idle_after_id = None
        if self._qr_var.get().strip():
            self._on_qr_scanned()

    def _on_qr_scanned(self, _event=None) -> None:
        if self._qr_idle_after_id is not None:
            self.after_cancel(self._qr_idle_after_id)
            self._qr_idle_after_id = None

        raw = self._qr_var.get().strip()
        self._qr_var.set("")
        if not raw:
            return

        if self._current_qr is not None:
            self._status_var.set("Test already in progress, please wait")
            return

        try:
            qr = parse_qr(raw)
        except ValueError as exc:
            self._status_var.set(f"Invalid QR code: {exc}")
            return

        self._current_qr = qr
        self._test_deadline = None
        self._result_var.set("")
        self._qr_entry.config(state="disabled")
        self._status_var.set(f"Scanned {qr.raw} -- looking for the board...")

        self._scan_for_qr_deadline = time.monotonic() + QR_SCAN_RETRY_S
        self._scan_for_qr_retry()

    def _scan_for_qr_retry(self) -> None:
        # comports() can return a stale/empty result on the very first
        # call right after a scan even with the board already plugged in
        # and enumerated (a manual re-click of Scan a moment later always
        # finds it) -- so retry for a few seconds instead of failing on
        # one empty scan.
        self._on_scan()
        if self._monitor is not None:
            return

        if time.monotonic() < self._scan_for_qr_deadline:
            self.after(QR_SCAN_RETRY_INTERVAL_MS, self._scan_for_qr_retry)
            return

        qr = self._current_qr
        assert qr is not None
        self._status_var.set(f"Scanned {qr.raw}, but no ArduPilot port found")
        self._finish_test(passed=False)

    def _on_scan(self) -> None:
        # Don't yank a live connection out from under the user on a rescan.
        # A QR scan against an already-connected board just rides along on
        # that connection -- _poll_health picks up self._current_qr on its
        # next tick and evaluates pass/fail against it.
        if self._monitor is not None:
            if self._current_qr is None:
                self._status_var.set("Disconnect before scanning again")
            return

        self._ports = port_scan.find_candidate_ports()
        labels = [p.label for p in self._ports]
        self._port_combo["values"] = labels
        if not labels:
            self._status_var.set("No ports found")
            return

        # Auto-select the first exact VID:PID match if there is one; the
        # COM number itself is irrelevant to the operator (each board keeps
        # a stable number derived from its CPU UID -- see cleanup script).
        strong_idx = next(
            (i for i, p in enumerate(self._ports) if p.strong_match), None
        )
        self._port_combo.current(strong_idx if strong_idx is not None else 0)

        if strong_idx is not None:
            self._status_var.set(
                f"Found ArduPilot board on {self._ports[strong_idx].device}"
            )
            # A QR scan always connects, regardless of the manual checkbox.
            if self._autoconnect_var.get() or self._current_qr is not None:
                self._on_connect()
        else:
            self._status_var.set(
                f"{len(labels)} port(s), none matched ArduPilot's USB ID -- "
                "pick one and Connect (best guess selected)"
            )

    def _selected_port(self) -> str | None:
        idx = self._port_combo.current()
        if idx < 0 or idx >= len(self._ports):
            return None
        return self._ports[idx].device

    def _on_connect(self) -> None:
        if self._monitor is not None:
            self._disconnect()
            return

        port_name = self._selected_port()
        if not port_name:
            self._status_var.set("Select a port first")
            return

        # No up-front bootloader probe: after flashing/power-up the board
        # sits in the bootloader for ~5s and boots on its own, and a
        # mistimed probe resets that countdown (see health.py). The
        # monitor just waits out the boot window instead.
        self._status_var.set(f"Waiting for {port_name} to boot...")
        self._monitor = MavlinkHealthMonitor(port_name, baud=MAVLINK_BAUD)
        self._monitor.start()
        self._connect_btn.config(text="Disconnect")
        self.after(POLL_MS, self._poll_health)

    def _disconnect(self) -> None:
        self._stop_monitor()
        self._connect_btn.config(text="Connect")
        self._set_all_leds(None)
        if self._current_qr is not None:
            # Manual disconnect during a QR-triggered test aborts it outright
            # rather than logging a result -- it wasn't a real pass/fail
            # verdict from the sensors, just the operator bailing out.
            self._status_var.set(f"{self._current_qr.raw}: test aborted (disconnected)")
            self._reset_for_next_scan()
        else:
            self._status_var.set("Disconnected")

    def _stop_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None

    def _set_all_leds(self, state: bool | None) -> None:
        for led in self._leds.values():
            led.set_state(state)
        self._detail_vars["imu1"].set("-- --.--m/s²")
        self._detail_vars["imu2"].set("-- --.--m/s²")
        self._detail_vars["baro"].set("-- --.--hPa")
        self._detail_vars["vbat"].set("--.-- V")

    def _poll_health(self) -> None:
        if self._monitor is None:
            return
        snap = self._monitor.snapshot()

        if snap.phase == "waiting":
            self._set_all_leds(None)
            self._status_var.set(
                f"Waiting for board to boot ({snap.boot_wait_remaining:.0f}s left)... "
                "just plugged in / flashed? give it a few seconds."
            )
        elif snap.phase == "failed":
            self._set_all_leds(None)
            self._status_var.set(snap.last_error or "Connection failed")
            if self._current_qr is not None:
                self._finish_test(passed=False, snapshot=snap)
                return
        else:
            self._leds["mavlink"].set_state(snap.mavlink_ok)
            self._leds["imu1"].set_state(snap.imu1_ok)
            self._leds["imu2"].set_state(snap.imu2_ok)
            self._leds["baro"].set_state(snap.baro_ok)
            self._leds["vbat"].set_state(snap.vbat_ok)

            self._detail_vars["imu1"].set(self._format_imu(snap.imu1_type, snap.imu1_accel_mag))
            self._detail_vars["imu2"].set(self._format_imu(snap.imu2_type, snap.imu2_accel_mag))
            self._detail_vars["baro"].set(
                f"{snap.baro_type or '--'} {snap.baro_pressure:.1f}hPa"
                if snap.baro_pressure is not None
                else "-- --.--hPa"
            )
            self._detail_vars["vbat"].set(
                f"{snap.vbat_voltage:.2f} V" if snap.vbat_voltage is not None else "--.-- V"
            )

            if snap.last_error:
                self._status_var.set(snap.last_error)
            elif snap.mavlink_ok:
                self._status_var.set(
                    f"Connected: sysid={snap.system_id} autopilot={snap.autopilot_type}"
                )
            else:
                self._status_var.set("Waiting for MAVLink heartbeat...")

        if self._current_qr is not None and snap.phase == "connected":
            if self._test_deadline is None:
                self._test_deadline = time.monotonic() + TEST_TIMEOUT_S

            all_ok = snap.mavlink_ok and snap.imu1_ok and snap.imu2_ok and snap.baro_ok and snap.vbat_ok
            if all_ok:
                self._finish_test(passed=True, snapshot=snap)
                return
            if time.monotonic() > self._test_deadline:
                self._status_var.set(f"Timed out after {TEST_TIMEOUT_S:.0f}s waiting for all sensors")
                self._finish_test(passed=False, snapshot=snap)
                return

        self.after(POLL_MS, self._poll_health)

    def _finish_test(self, passed: bool, snapshot: HealthSnapshot | None = None) -> None:
        qr = self._current_qr
        assert qr is not None
        snap = snapshot if snapshot is not None else HealthSnapshot()

        self._stop_monitor()
        self._connect_btn.config(text="Connect")

        test_log.append_result(
            TestResult(qr=qr, snapshot=snap, passed=passed, timestamp=datetime.datetime.now())
        )

        self._result_var.set("PASS" if passed else "FAIL")
        self._result_label.config(fg="#1e8e3e" if passed else "#d93025")
        self._status_var.set(
            f"{qr.raw}: {'PASS' if passed else 'FAIL'} -- logged to {test_log.DEFAULT_LOG_PATH.name}"
        )

        self.after(RESULT_DISPLAY_MS, self._reset_for_next_scan)

    def _reset_for_next_scan(self) -> None:
        self._current_qr = None
        self._test_deadline = None
        self._result_var.set("")
        self._set_all_leds(None)
        self._qr_entry.config(state="normal")
        self._qr_entry.focus_set()
        self._status_var.set("Ready -- scan the next QR code")

    @staticmethod
    def _format_imu(type_name: str, accel_mag: float | None) -> str:
        if accel_mag is None:
            return "-- --.--m/s²"
        return f"{type_name or '--'} {accel_mag:.2f}m/s²"

    def destroy(self) -> None:
        if self._qr_idle_after_id is not None:
            self.after_cancel(self._qr_idle_after_id)
        self._stop_monitor()
        super().destroy()


def main() -> None:
    app = GipsyTesterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
