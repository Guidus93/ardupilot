"""Tkinter GUI: pick a port, connect, watch 4 status LEDs.

Flow:
  1. Scan -> list candidate ports (VID:PID / description match).
  2. Connect -> probe bootloader sync handshake first. If the board
     answers it, stop there and tell the user to flash firmware.
     Otherwise hand the (still-closed) port to a MavlinkHealthMonitor.
  3. Poll the monitor's snapshot every 250ms and recolor the LEDs.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import bootloader, port_scan
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
        self._ports = port_scan.find_candidate_ports()
        labels = [p.label for p in self._ports]
        self._port_combo["values"] = labels
        if labels:
            self._port_combo.current(0)
        self._status_var.set(f"Found {len(labels)} candidate port(s)" if labels else "No ports found")

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

        self._status_var.set(f"Probing {port_name} for bootloader...")
        self.update_idletasks()

        if bootloader.probe_bootloader(port_name):
            self._status_var.set(
                f"{port_name}: board is in BOOTLOADER mode. "
                "If you just flashed it, unplug/replug USB (full power cycle) "
                "before connecting again -- a bootloader->app jump alone is not enough."
            )
            self._set_all_leds(None)
            return

        self._status_var.set(f"Connecting to {port_name} via MAVLink...")
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

        if snap.last_error:
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
