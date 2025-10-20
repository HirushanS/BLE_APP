# ble_ctk_browser.py
import asyncio
import threading
import re
from functools import partial
from typing import Optional, Dict, List, Tuple, Union

import customtkinter as ctk
from bleak import BleakScanner, BleakClient


# ---------- Async bridge ----------
class AsyncioBridge:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        try:
            if self.loop.is_running():
                self.loop.call_soon_threadsafe(self.loop.stop)
        finally:
            if self.thread.is_alive():
                self.thread.join(timeout=1.0)


# ---------- App ----------
class BLEBrowserApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")   # "light" or "system"
        ctk.set_default_color_theme("blue")  # "dark-blue" / "green" etc.

        self.title("BLE Browser (CustomTkinter + Bleak)")
        self.geometry("1280x800")
        self.minsize(1050, 650)

        self.bridge = AsyncioBridge()

        self.devices = []  # list[BLEDevice]
        self.client: Optional[BleakClient] = None
        self.connected_address: Optional[str] = None

        # char_uuid -> (service_uuid, char_obj, handle)
        self.char_index: Dict[str, Tuple[str, object, int]] = {}
        self.notify_active_uuid: Optional[str] = None

        # UI state
        self.compact_values = ctk.BooleanVar(value=True)
        self.text_mode = ctk.BooleanVar(value=False)

        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI ----------
    def _build_ui(self):
        # grid: 3 rows (toolbar, mid controls, bottom panes)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- Toolbar ---
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 6))
        bar.grid_columnconfigure(5, weight=1)

        self.scan_btn = ctk.CTkButton(bar, text="Scan", command=self.on_scan)
        self.scan_btn.grid(row=0, column=0, padx=(0, 8))

        self.connect_btn = ctk.CTkButton(bar, text="Connect", state="disabled", command=self.on_connect)
        self.connect_btn.grid(row=0, column=1, padx=8)

        self.disconnect_btn = ctk.CTkButton(bar, text="Disconnect", state="disabled", command=self.on_disconnect)
        self.disconnect_btn.grid(row=0, column=2, padx=8)

        self.status_lbl = ctk.CTkLabel(bar, text="Idle")
        self.status_lbl.grid(row=0, column=5, sticky="e", padx=(8, 8))

        # theme toggle + scale
        self.theme_var = ctk.StringVar(value="dark")
        theme = ctk.CTkSegmentedButton(bar, values=["light", "dark"], variable=self.theme_var, command=self._change_theme)
        theme.grid(row=0, column=6, padx=(8, 0))
        scale = ctk.CTkOptionMenu(bar, values=["90%", "100%", "110%", "125%"], command=self._change_scale)
        scale.set("100%")
        scale.grid(row=0, column=7, padx=(8, 0))

        # --- Middle strip: Devices (left) + Controls (right) ---
        mid = ctk.CTkFrame(self)
        mid.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        mid.grid_columnconfigure(0, weight=2)
        mid.grid_columnconfigure(1, weight=3)
        mid.grid_rowconfigure(1, weight=1)

        # Devices panel
        dev_box = ctk.CTkFrame(mid)
        dev_box.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8), pady=8)
        dev_box.grid_columnconfigure(0, weight=1)
        dev_box.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(dev_box, text="Discovered Devices").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        self.device_var = ctk.StringVar(value="")  # store selected device index as string
        self.device_list = ctk.CTkScrollableFrame(dev_box, height=180)
        self.device_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))

        # Controls panel
        ctl_box = ctk.CTkFrame(mid)
        ctl_box.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=8)
        ctl_box.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ctl_box, text="Characteristic Controls").grid(row=0, column=0, columnspan=4, sticky="w", padx=10, pady=(10, 0))

        ctk.CTkLabel(ctl_box, text="Characteristic:").grid(row=1, column=0, sticky="w", padx=10, pady=(6, 6))
        self.char_var = ctk.StringVar(value="")
        self.char_combo = ctk.CTkComboBox(ctl_box, variable=self.char_var, values=[], width=600, command=lambda _: self._on_char_selected())
        self.char_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=8, pady=6)

        self.props_lbl = ctk.CTkLabel(ctl_box, text="Props: -")
        self.props_lbl.grid(row=1, column=3, sticky="e", padx=(8, 10))

        # RW/Notify row
        self.read_btn = ctk.CTkButton(ctl_box, text="Read", state="disabled", command=self.on_read)
        self.read_btn.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="w")

        self.write_entry = ctk.CTkEntry(ctl_box, placeholder_text="Hex: 01 A0 0D   (or enable Text mode)", width=380)
        self.write_entry.grid(row=2, column=1, sticky="ew", pady=(0, 10))

        ctk.CTkCheckBox(ctl_box, text="Text mode", variable=self.text_mode).grid(row=2, column=2, sticky="w", padx=8, pady=(0, 10))

        self.write_btn = ctk.CTkButton(ctl_box, text="Write", state="disabled", command=self.on_write)
        self.write_btn.grid(row=2, column=3, padx=(8, 10), pady=(0, 10), sticky="e")

        self.notify_btn = ctk.CTkButton(ctl_box, text="Subscribe", state="disabled", command=self.on_toggle_notify)
        self.notify_btn.grid(row=3, column=3, padx=(8, 10), pady=(0, 12), sticky="e")

        # Byte size selection row
        byte_size_frame = ctk.CTkFrame(ctl_box, fg_color="transparent")
        byte_size_frame.grid(row=4, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 10))
        byte_size_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(byte_size_frame, text="Byte Size:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.byte_size_var = ctk.StringVar(value="0")
        self.byte_size_entry = ctk.CTkEntry(byte_size_frame, textvariable=self.byte_size_var, width=80)
        self.byte_size_entry.grid(row=0, column=1, sticky="w", padx=(0, 8))
        
        self.create_empty_btn = ctk.CTkButton(byte_size_frame, text="Create Empty Bytes", 
                                             command=self.on_create_empty_bytes, width=140)
        self.create_empty_btn.grid(row=0, column=2, sticky="w", padx=(0, 8))
        
        self.bytes_info_lbl = ctk.CTkLabel(byte_size_frame, text="Bytes: 0", text_color="gray")
        self.bytes_info_lbl.grid(row=0, column=3, sticky="e")

        # --- Bottom panes: Log (left) | Right (Decoded + Values) ---
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=2)
        bottom.grid_columnconfigure(1, weight=3)
        bottom.grid_rowconfigure(1, weight=1)

        # Log
        ctk.CTkLabel(bottom, text="Log / Services").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.output = ctk.CTkTextbox(bottom, wrap="none", font=("Consolas", 11))
        self.output.grid(row=1, column=0, sticky="nsew", padx=(10, 8), pady=(6, 10))

        # Right stack
        right = ctk.CTkFrame(bottom)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 10), pady=(6, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(3, weight=2)

        # Decoded table (scrollable key/value)
        ctk.CTkLabel(right, text="Decoded Status").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self.decoded_frame = ctk.CTkScrollableFrame(right)
        self.decoded_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(6, 10))
        self._decoded_rows: Dict[str, Tuple[ctk.CTkLabel, ctk.CTkLabel]] = {}  # name -> (name_lbl, value_lbl)

        # Values viewer
        values_hdr = ctk.CTkFrame(right, fg_color="transparent")
        values_hdr.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 0))
        values_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(values_hdr, text="Values (READ / NOTIFY)").grid(row=0, column=0, sticky="w")
        ctk.CTkCheckBox(values_hdr, text="Compact", variable=self.compact_values).grid(row=0, column=1, sticky="e")

        self.values_txt = ctk.CTkTextbox(right, wrap="none", font=("Consolas", 11))
        self.values_txt.configure(state="disabled")
        self.values_txt.grid(row=3, column=0, sticky="nsew", padx=10, pady=(6, 10))

    # ---------- Helpers ----------
    def _change_theme(self, mode):
        ctk.set_appearance_mode(mode)

    def _change_scale(self, value):
        pct = int(value.strip("%"))
        ctk.set_widget_scaling(pct / 100.0)

    def set_status(self, s: str):
        self.status_lbl.configure(text=s)
        self.update_idletasks()

    def log(self, text: str):
        # main log
        self.output.insert("end", text + "\n")
        self.output.see("end")

        # mirrored compact payloads
        if text.startswith("[READ ") or text.startswith("[NOTIF "):
            line = self._compact_line(text) if self.compact_values.get() else text
            self.values_txt.configure(state="normal")
            self.values_txt.insert("end", line + "\n")
            self.values_txt.see("end")
            self.values_txt.configure(state="disabled")

    @staticmethod
    def _compact_line(text: str) -> str:
        m = re.search(r"\]\s+(.*)", text)
        if not m:
            return text
        rest = m.group(1)
        rest = re.split(r"\s…|\s\(len=", rest, maxsplit=1)[0]
        rest = re.sub(r"\(Handle:[^)]+\)\s*", "", rest)
        return rest.strip()

    # ---------- Device list ----------
    def _refresh_device_list(self):
        # clear
        for child in self.device_list.winfo_children():
            child.destroy()

        # rebuild
        for idx, d in enumerate(self.devices):
            name = d.name or "(Unknown)"
            addr = getattr(d, "address", getattr(d, "mac_address", "??"))

            rb = ctk.CTkRadioButton(
                self.device_list,
                text=f"{name}   [{addr}]",
                variable=self.device_var,
                value=str(idx),
                command=self._on_device_pick,
                width=800,          # optional width
            )
            # <-- anchor belongs to the geometry manager, not the widget:
            rb.pack(fill="x", padx=6, pady=3, anchor="w")


    def _on_device_pick(self):
        self.connect_btn.configure(state=("normal" if self.device_var.get() else "disabled"))

    def _selected_device(self):
        v = self.device_var.get()
        if not v:
            return None
        i = int(v)
        if 0 <= i < len(self.devices):
            return self.devices[i]
        return None

    # ---------- Actions ----------
    def on_scan(self):
        self.set_status("Scanning…")
        self.scan_btn.configure(state="disabled")
        self.connect_btn.configure(state="disabled")
        self.output.delete("0.0", "end")
        self.values_txt.configure(state="normal")
        self.values_txt.delete("0.0", "end")
        self.values_txt.configure(state="disabled")
        self._clear_decoded()

        fut = self.bridge.run_coro(self._scan_async())
        fut.add_done_callback(lambda _f: self.after(0, self._scan_done))

    async def _scan_async(self):
        self.devices = await BleakScanner.discover(timeout=5.0)

    def _scan_done(self):
        self._refresh_device_list()
        self.set_status(f"Found {len(self.devices)} device(s)")
        self.scan_btn.configure(state="normal")

    def on_connect(self):
        device = self._selected_device()
        if not device:
            return

        if self.client and getattr(self.client, "is_connected", False):
            self.on_disconnect()

        address = getattr(device, "address", getattr(device, "mac_address", None))
        if not address:
            return

        self.set_status(f"Connecting to {address} …")
        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="disabled")

        fut = self.bridge.run_coro(self._connect_and_list(address))
        fut.add_done_callback(lambda _f: self.after(0, self._post_connect_ui))

    async def _connect_and_list(self, address: str):
        self.client = BleakClient(address)
        self.char_index.clear()
        self._populate_char_combo([])

        try:
            await self.client.connect(timeout=10.0)
            ok = bool(getattr(self.client, "is_connected", False))
            self.connected_address = address if ok else None
        except Exception as exc:
            self.connected_address = None
            self.after(0, lambda m=str(exc): self.log(f"Connect failed: {m}"))
            return

        connected_flag = bool(getattr(self.client, "is_connected", False))
        self.after(0, lambda s=connected_flag: self.log(f"Connected: {s}"))

        # Service discovery (version-agnostic)
        try:
            services_coll = getattr(self.client, "services", None)
            if not services_coll or len(list(services_coll)) == 0:
                get_services = getattr(self.client, "get_services", None)
                if callable(get_services):
                    services_coll = await get_services()
            if not services_coll:
                self.after(0, lambda: self.log("No GATT services found."))
                return
        except Exception as exc:
            self.after(0, lambda m=f"Failed to obtain services: {exc}": self.log(m))
            return

        # Log services & build char index
        char_items: List[str] = []
        for svc in services_coll:
            self.after(0, lambda s=svc: self.log(f"[Service] {s.uuid}: {s.description}"))
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                self.after(0, lambda c=ch, p=props: self.log(f"  [Char] {c.uuid}: {c.description} (props: {p})"))
                uuid = str(ch.uuid)
                # Store UUID, char object, AND handle
                self.char_index[uuid] = (str(svc.uuid), ch, ch.handle)
                char_items.append(uuid)

        self.after(0, lambda items=char_items: self._populate_char_combo(items))

    def _populate_char_combo(self, items: List[str]):
        self.char_combo.configure(values=items)
        self.char_var.set(items[0] if items else "")
        if items:
            self._on_char_selected()

    def _on_char_selected(self):
        uuid = self.char_var.get()
        props = []
        if uuid and uuid in self.char_index:
            # Get service UUID, char object, and handle
            _svc_uuid, ch, _handle = self.char_index[uuid]
            props = list(getattr(ch, "properties", []))
        self.props_lbl.configure(text=f"Props: {','.join(props) if props else '-'}")

        self.read_btn.configure(state=("normal" if "read" in props else "disabled"))
        self.write_btn.configure(state=("normal" if ("write" in props or "write-without-response" in props) else "disabled"))
        self.notify_btn.configure(state=("normal" if "notify" in props or "indicate" in props else "disabled"))
        self.notify_btn.configure(text=("Unsubscribe" if self.notify_active_uuid == uuid else "Subscribe"))

    def _post_connect_ui(self):
        if self.client and getattr(self.client, "is_connected", False):
            self.set_status(f"Connected to {self.connected_address}")
            self.disconnect_btn.configure(state="normal")
        else:
            self.set_status("Disconnected")
        self.connect_btn.configure(state="normal")

    def on_disconnect(self):
        if not (self.client and getattr(self.client, "is_connected", False)):
            self.set_status("Disconnected")
            self.disconnect_btn.configure(state="disabled")
            return

        self.set_status("Disconnecting…")
        fut = self.bridge.run_coro(self._disconnect_async())
        fut.add_done_callback(lambda _f: self.after(0, self._post_disconnect_ui))

    async def _disconnect_async(self):
        try:
            if self.notify_active_uuid:
                try:
                    # Stop notifications using handle instead of UUID
                    if self.notify_active_uuid in self.char_index:
                        _, _, handle = self.char_index[self.notify_active_uuid]
                        await self.client.stop_notify(handle)
                except Exception:
                    pass
                self.notify_active_uuid = None
            await self.client.disconnect()
        except Exception:
            pass

    def _post_disconnect_ui(self):
        self.set_status("Disconnected")
        self.disconnect_btn.configure(state="disabled")
        self.notify_btn.configure(text="Subscribe", state="disabled")
        self.read_btn.configure(state="disabled")
        self.write_btn.configure(state="disabled")
        self._clear_decoded()

    # ---------- Read / Write / Notify ----------
    def on_read(self):
        uuid = self.char_var.get()
        if not uuid:
            return
        fut = self.bridge.run_coro(self._read_async(uuid))
        fut.add_done_callback(lambda _f: None)

    async def _read_async(self, uuid: str):
        try:
            data = await self.client.read_gatt_char(uuid)
            hex_str = " ".join(f"{b:02X}" for b in data[:64])
            msg = f"[READ {uuid}] {hex_str}" + (f" … (len={len(data)})" if len(data) > 64 else f" (len={len(data)})")
            self.after(0, lambda m=msg: self.log(m))
            if len(data) >= 34:
                decoded = self._decode_status(data)
                self.after(0, lambda d=decoded: self._update_decoded(d))
        except Exception as exc:
            self.after(0, lambda m=f"[READ {uuid}] Failed: {exc}": self.log(m))

    def on_write(self):
        uuid = self.char_var.get()
        if not uuid:
            return
        text = self.write_entry.get().strip()
        if not text:
            return

        if self.text_mode.get():
            payload = text.encode("utf-8", errors="ignore")
        else:
            ok, payload = self._parse_hex(text)
            if not ok:
                self.log("Write: hex parse error. Use '01 A0 0D' or '01,a0,0d'")
                return

        fut = self.bridge.run_coro(self._write_async(uuid, payload))
        fut.add_done_callback(lambda _f: None)

    async def _write_async(self, uuid: str, payload: bytes):
        try:
            props = []
            if uuid in self.char_index:
                _svc_uuid, ch, _handle = self.char_index[uuid]
                props = list(getattr(ch, "properties", []))
            noresp = "write-without-response" in props and "write" not in props
            await self.client.write_gatt_char(uuid, payload, response=not noresp)
            shown = " ".join(f"{b:02X}" for b in payload[:64])
            msg = f"[WRITE {uuid}] {shown}" + (" …" if len(payload) > 64 else "")
            self.after(0, lambda m=msg: self.log(m))
        except Exception as exc:
            self.after(0, lambda m=f"[WRITE {uuid}] Failed: {exc}": self.log(m))

    def on_toggle_notify(self):
        uuid = self.char_var.get()
        if not uuid:
            return

        if self.notify_active_uuid == uuid:
            fut = self.bridge.run_coro(self._stop_notify_async(uuid))
            fut.add_done_callback(lambda _f: self.after(0, self._notify_stopped_ui))
        else:
            fut = self.bridge.run_coro(self._start_notify_async(uuid))
            fut.add_done_callback(lambda _f: self.after(0, self._notify_started_ui, uuid))

    async def _start_notify_async(self, uuid: str):
        try:
            if uuid in self.char_index:
                # Get the handle from our stored characteristic info
                _svc_uuid, ch, handle = self.char_index[uuid]
                # Use handle instead of UUID for notification subscription
                await self.client.start_notify(handle, self._notification_handler)
                self.notify_active_uuid = uuid
                self.after(0, lambda: self.log(f"[NOTIFY {uuid}] Subscribed using handle {handle}"))
            else:
                self.after(0, lambda: self.log(f"[NOTIFY {uuid}] Characteristic not found in index"))
        except Exception as exc:
            self.after(0, lambda m=f"[NOTIFY {uuid}] Failed to subscribe: {exc}": self.log(m))

    async def _stop_notify_async(self, uuid: str):
        try:
            if uuid in self.char_index:
                # Get the handle from our stored characteristic info
                _svc_uuid, ch, handle = self.char_index[uuid]
                # Use handle instead of UUID for stopping notification
                await self.client.stop_notify(handle)
                self.after(0, lambda: self.log(f"[NOTIFY {uuid}] Unsubscribed"))
            else:
                self.after(0, lambda: self.log(f"[NOTIFY {uuid}] Characteristic not found in index"))
        except Exception as exc:
            self.after(0, lambda m=f"[NOTIFY {uuid}] Failed to unsubscribe: {exc}": self.log(m))
        finally:
            if self.notify_active_uuid == uuid:
                self.notify_active_uuid = None

    def _notify_started_ui(self, uuid: str):
        if self.char_var.get() == uuid:
            self.notify_btn.configure(text="Unsubscribe")

    def _notify_stopped_ui(self):
        self.notify_btn.configure(text="Subscribe")

    def _notification_handler(self, sender: int, data: bytearray):
        # Convert handle back to UUID for display
        uuid = "Unknown"
        for char_uuid, (_svc_uuid, _ch, handle) in self.char_index.items():
            if handle == sender:
                uuid = char_uuid
                break
                
        hex_str = " ".join(f"{b:02X}" for b in data[:64])
        msg = f"[NOTIF {uuid}] {hex_str}" + (f" … (len={len(data)})" if len(data) > 64 else f" (len={len(data)})")
        self.after(0, lambda m=msg: self.log(m))
        if len(data) >= 34:
            decoded = self._decode_status(data)
            self.after(0, lambda d=decoded: self._update_decoded(d))

    # ---------- Byte Size Functions ----------
    def on_create_empty_bytes(self):
        try:
            size = int(self.byte_size_var.get())
            if size < 0:
                self.log("Error: Byte size must be a positive integer")
                return
                
            # Create empty byte array
            empty_bytes = bytes([0] * size)
            hex_str = " ".join(f"{b:02X}" for b in empty_bytes)
            
            # Update the write entry
            self.write_entry.delete(0, "end")
            self.write_entry.insert(0, hex_str)
            
            # Update the info label
            self.bytes_info_lbl.configure(text=f"Bytes: {size}")
            
            self.log(f"Created empty byte array of size {size}: {hex_str}")
        except ValueError:
            self.log("Error: Please enter a valid integer for byte size")

    # ---------- Decoding ----------
    @staticmethod
    def _u16_be(hi: int, lo: int) -> int:
        return ((hi & 0xFF) << 8) | (lo & 0xFF)

    def _decode_status(self, payload: bytes) -> Dict[str, Union[List[int], int]]:
        # Expect at least 34 bytes, but allow more
        b = payload
        if len(b) < 34:
            return {}
        current_status = b[0]
        error_code = b[1]

        def pairs(start, count):
            out = []
            for i in range(count):
                hi = b[start + 2 * i]
                lo = b[start + 2 * i + 1]
                out.append(self._u16_be(hi, lo))
            return out

        temps = pairs(2, 4)
        press = pairs(10, 6)
        levels = pairs(22, 2)
        flows = pairs(26, 4)

        return {
            "current_status": current_status,
            "error_code": error_code,
            "temperature": temps,
            "pressure": press,
            "level": levels,
            "flowrate": flows,
        }

    def _clear_decoded(self):
        for child in self.decoded_frame.winfo_children():
            child.destroy()
        self._decoded_rows.clear()

    def _update_decoded(self, d: Dict[str, Union[List[int], int]]):
        if not d:
            return

        # build rows if not present
        def ensure_row(name: str):
            if name in self._decoded_rows:
                return self._decoded_rows[name]
            row = ctk.CTkFrame(self.decoded_frame, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)
            k = ctk.CTkLabel(row, text=name, width=140, anchor="w")
            k.pack(side="left")
            v = ctk.CTkLabel(row, text="", anchor="w", wraplength=800)
            v.pack(side="left", fill="x", expand=True)
            self._decoded_rows[name] = (k, v)
            return self._decoded_rows[name]

        def set_val(name: str, val: Union[int, List[int]]):
            _, v = ensure_row(name)
            if isinstance(val, list):
                v.configure(text=", ".join(str(x) for x in val))
            else:
                v.configure(text=str(val))

        set_val("current_status", d["current_status"])
        set_val("error_code", d["error_code"])
        set_val("temperature[4]", d["temperature"])
        set_val("pressure[6]", d["pressure"])
        set_val("level[2]", d["level"])
        set_val("flowrate[4]", d["flowrate"])

    # ---------- Utils ----------
    @staticmethod
    def _parse_hex(s: str) -> Tuple[bool, bytes]:
        tokens = [t for t in s.replace(",", " ").replace(";", " ").split() if t]
        try:
            return True, bytes(int(t, 16) & 0xFF for t in tokens)
        except Exception:
            return False, b""

    # ---------- Close ----------
    def on_close(self):
        try:
            if self.client and getattr(self.client, "is_connected", False):
                self.bridge.run_coro(self._disconnect_async()).result(timeout=2.0)
        except Exception:
            pass
        self.bridge.stop()
        self.destroy()


if __name__ == "__main__":
    app = BLEBrowserApp()
    app.mainloop()