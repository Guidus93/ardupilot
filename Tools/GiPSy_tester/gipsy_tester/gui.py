"""Tkinter GUI: pick a port, connect, watch 4 status LEDs.

Flow:
  1. Scan -> list candidate ports (VID:PID / description match).
  2. Connect -> hand the port to a MavlinkHealthMonitor, which waits
     out the bootloader boot window (retrying a heartbeat, re-scanning
     ports) instead of probing the bootloader up front. See health.py
     for why probing early is counterproductive.
  3. Poll the monitor's snapshot every 250ms and recolor the LEDs.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import port_scan
from .health import MavlinkHealthMonitor

POLL_MS = 250
LED_GREEN = "#2ecc71"
LED_RED = "#e74c3c"
LED_GREY = "#95a5a6"

MAVLINK_BAUD = 57600


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

        self._build_widgets()
        self._on_scan()

    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 6}

        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", **pad)

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
        leds.grid(row=1, column=0, sticky="ew", **pad)

        self._leds: dict[str, LedIndicator] = {}
        for i, key in enumerate(("mavlink", "imu1", "imu2", "baro")):
            col = ttk.Frame(leds)
            col.grid(row=0, column=i, padx=14, pady=8)
            led = LedIndicator(col, key)
            led.pack()
            ttk.Label(col, text=key.upper()).pack()
            self._leds[key] = led

        self._status_var = tk.StringVar(value="Not connected")
        ttk.Label(self, textvariable=self._status_var, anchor="w").grid(
            row=2, column=0, sticky="ew", **pad
        )

    def _on_scan(self) -> None:
        # Don't yank a live connection out from under the user on a rescan.
        if self._monitor is not None:
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
            if self._autoconnect_var.get():
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
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        self._connect_btn.config(text="Connect")
        self._set_all_leds(None)
        self._status_var.set("Disconnected")

    def _set_all_leds(self, state: bool | None) -> None:
        for led in self._leds.values():
            led.set_state(state)

    def _poll_health(self) -> None:
        if self._monitor is None:
            return
        snap = self._monitor.snapshot()

        self._leds["mavlink"].set_state(snap.mavlink_ok)
        self._leds["imu1"].set_state(snap.imu1_ok)
        self._leds["imu2"].set_state(snap.imu2_ok)
        self._leds["baro"].set_state(snap.baro_ok)

        if snap.phase == "waiting":
            self._set_all_leds(None)
            self._status_var.set(
                f"Waiting for board to boot ({snap.boot_wait_remaining:.0f}s left)... "
                "just plugged in / flashed? give it a few seconds."
            )
        elif snap.phase == "failed":
            self._set_all_leds(None)
            self._status_var.set(snap.last_error or "Connection failed")
        elif snap.last_error:
            self._status_var.set(snap.last_error)
        elif snap.mavlink_ok:
            self._status_var.set(
                f"Connected: sysid={snap.system_id} autopilot={snap.autopilot_type}"
            )
        else:
            self._status_var.set("Waiting for MAVLink heartbeat...")

        self.after(POLL_MS, self._poll_health)

    def destroy(self) -> None:
        if self._monitor is not None:
            self._monitor.stop()
        super().destroy()


def main() -> None:
    app = GipsyTesterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
