import asyncio
import threading
import re
import ast
import tkinter as tk
from typing import Optional, Dict, List, Tuple, Union
import json, os, time  # <— time for timestamps

# matplotlib for the live graph popup
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import customtkinter as ctk
from bleak import BleakScanner, BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

THEME = {
    "bg": "#0f1b2a",
    "panel": "#122238",
    "panel_alt": "#0e1e33",
    "card": "#152c47",
    "card_border": "#214a72",
    "muted": "#8aa4bf",
    "tab_active": "#1b4266",
    "tab_inactive": "#0f2036",
    "tab_close_bg": "#2a3f5a",
    "text": "#e6eef7",
    "green": "#2ecc71",
    "green_dim": "#1e9b55",
    "red": "#e74c3c",
    # tooltip colors
    "tooltip_bg": "#0e1e33",
    "tooltip_border": "#214a72",
    "tooltip_text": "#e6eef7",
}

TARGET_STATUS_UUID = "f0002002-0451-4000-b000-000000000000"

def set_fg(w, c):
    try: w.configure(fg_color=c)
    except Exception: pass

def set_border(w, c, width=1):
    try: w.configure(border_color=c, border_width=width)
    except Exception: pass

def hide_ctk_textbox_scrollbars(tb):
    try:
        if hasattr(tb, "_scrollbar") and tb._scrollbar: tb._scrollbar.grid_remove()
    except Exception: pass
    try:
        if hasattr(tb, "_scrollbar_x") and tb._scrollbar_x: tb._scrollbar_x.grid_remove()
    except Exception: pass

# ---------------------- Tooltip helper ---------------------- #
class _HoverTooltip:
    """Small tooltip that shows near the mouse pointer for a widget.

    textfunc: a zero-arg callable returning the string to show (evaluated on show).
    """
    def __init__(self, widget, textfunc, delay_ms: int = 250):
        try:
            self.font_body = ctk.CTkFont(size=12)
        except Exception:
            self.font_body = None
        self.widget = widget
        self.textfunc = textfunc
        self.delay_ms = delay_ms
        self._after_id = None
        self.tip = None

        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Motion>", self._on_motion, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    def _on_enter(self, _evt=None):
        self._schedule()

    def _on_leave(self, _evt=None):
        self._cancel()
        self._hide()

    def _on_motion(self, evt=None):
        if self.tip and evt:
            self._position(evt.x_root, evt.y_root)

    def _on_destroy(self, _evt=None):
        self._cancel()
        self._hide()

    def _schedule(self):
        self._cancel()
        try:
            self._after_id = self.widget.after(self.delay_ms, self._show)
        except Exception:
            pass

    def _cancel(self):
        if self._after_id:
            try: self.widget.after_cancel(self._after_id)
            except Exception: pass
            self._after_id = None

    def _show(self):
        txt = ""
        try:
            txt = str(self.textfunc() or "").strip()
        except Exception:
            txt = ""
        if not txt:
            return
        if self.tip:
            try:
                for child in self.tip.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(text=txt)
                self.tip.deiconify()
            except Exception:
                pass
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_attributes("-topmost", True)
        frame = tk.Frame(self.tip, bg=THEME.get("tooltip_border","#214a72"), bd=0)
        frame.pack(padx=1, pady=1)
        lbl = tk.Label(frame, text=txt, justify="left",
                       bg=THEME.get("tooltip_bg","#0e1e33"),
                       fg=THEME.get("tooltip_text","#e6eef7"),
                       relief="flat", borderwidth=0, padx=8, pady=4,
                       font=self.font_body)
        lbl.pack()
        try:
            x, y = self.widget.winfo_pointerxy()
            self._position(x, y)
        except Exception:
            pass

    def _position(self, x_root: int, y_root: int):
        try:
            self.tip.wm_geometry(f"+{x_root+14}+{y_root+14}")
        except Exception:
            pass

    def _hide(self):
        if self.tip:
            try: self.tip.withdraw()
            except Exception: pass
# ------------------- END tooltip helper ------------------- #

class AsyncioBridge:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
    def run_coro(self, c):
        return asyncio.run_coroutine_threadsafe(c, self.loop)
    def stop(self):
        try:
            if self.loop.is_running(): self.loop.call_soon_threadsafe(self.loop.stop)
        finally:
            if self.thread.is_alive(): self.thread.join(timeout=1.0)

class BLEBrowserApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("BLE Browser")
        # self.geometry("1600x900")

        self.minsize(800, 600)
        set_fg(self, THEME["bg"])

        # Outer left devices column resizer
        self._dev_col_width = 360
        self._dev_min = 220
        self._dev_max = 700
        self._sash_size = 10
        self._dragging = False
        self._drag_start_x = 0
        self._dev_start_width = self._dev_col_width

        # Inner splitters
        self._inner_sash_size = 10

        self.bridge = AsyncioBridge()
        self.devices = []
        self.devices_unsorted = []  # <--- NEW: keep original "Found" order
        self.client: Optional[BleakClient] = None
        self.connected_address: Optional[str] = None
        self.char_index: Dict[str, Tuple[str, object, int]] = {}
        self.notify_active_uuid: Optional[str] = None

        self.compact_values = ctk.BooleanVar(value=True)
        self.active_tab_uuid: Optional[str] = None
        self.browser_tabs: Dict[str, Dict[str, object]] = {}
        self.char_pages: Dict[str, Dict[str, object]] = {}
        self.tab_titles: Dict[str, str] = {}
        self.max_tab_title_len = 26
        self._pending_logs: Dict[str, List[str]] = {}

        self._tab_menu_uuid: Optional[str] = None
        self._tab_menu = tk.Menu(self, tearoff=0)
        self._tab_menu.add_command(label="Rename tab", command=lambda: self._prompt_rename_tab(self._tab_menu_uuid))
        self._tab_menu.add_command(label="Close tab", command=lambda: self._close_browser_tab(self._tab_menu_uuid))

        self._blink_job = None
        self._blink_state = False

        # persistence
        self._names_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "char_names.json")
        self.saved_names: Dict[str, str] = self._load_saved_names()
        self._prefs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "char_prefs.json")
        self.saved_prefs: Dict[str, dict] = self._load_saved_prefs()

        # mapping for characteristic dropdown display <-> uuid
        self.uuid_to_display: Dict[str, str] = {}
        self.char_display_map: Dict[str, str] = {}
        self._char_items_order: List[str] = []

        # track installed tooltips for dropdown items
        # (kept for compatibility; not heavily used by CTk internals now)
        self._dropdown_item_tooltips: Dict[int, _HoverTooltip] = {}

        self._build_ui()
        self.after(60, self._auto_scale)
        self.after(140, self._maximize_on_start)
        self._resize_job = None
        self.bind("<Configure>", self._on_root_resize)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # scaling
    def _auto_scale(self):
        # base_w, base_h = 1600, 900
        base_w, base_h = 1920, 1080

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        scale = max(0.70, min(1.30, min(sw/base_w, sh/base_h)))
        ctk.set_widget_scaling(scale)
        try: ctk.set_window_scaling(scale)
        except Exception: pass
        self.max_tab_title_len = 26 if scale >= 1.0 else max(16, int(26 * scale))
        for u in self.browser_tabs.keys(): self._update_tab_title(u)
        try:
            if self.scale_menu.get() != "Auto": self.scale_menu.set("Auto")
        except Exception: pass

    def _maximize_on_start(self):
        try: self.state("zoomed")
        except Exception: pass
        try: self.attributes("-zoomed", True)
        except Exception: pass

    # persistence helpers
    def _load_saved_names(self) -> Dict[str, str]:
        try:
            if os.path.exists(self._names_path):
                with open(self._names_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if isinstance(k, str)}
        except Exception: pass
        return {}
    def _save_saved_names(self) -> None:
        try:
            with open(self._names_path, "w", encoding="utf-8") as f:
                json.dump(self.saved_names, f, ensure_ascii=False, indent=2)
        except Exception: pass
    def _load_saved_prefs(self) -> Dict[str, dict]:
        try:
            if os.path.exists(self._prefs_path):
                with open(self._prefs_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict): return data
        except Exception: pass
        return {}
    def _save_saved_prefs(self) -> None:
        try:
            with open(self._prefs_path, "w", encoding="utf-8") as f:
                json.dump(self.saved_prefs, f, ensure_ascii=False, indent=2)
        except Exception: pass
    def _uuid_prefs(self, uuid: str) -> dict:
        p = self.saved_prefs.setdefault(uuid, {})
        p.setdefault("title", None)
        p.setdefault("byte_names", {"read": [], "notify": [], "write": []})
        p.setdefault("notify_calcs", [])
        p.setdefault("write_presets", [])  # <---- saved WRITE presets [{name, bytes:[...]}]
        return p

    # UI
    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(self, corner_radius=0); set_fg(bar, THEME["panel_alt"])
        bar.grid(row=0, column=0, sticky="ew"); bar.grid_columnconfigure(5, weight=1)
        self.scan_btn = ctk.CTkButton(bar, text="Scan", command=self.on_scan); self.scan_btn.grid(row=0, column=0, padx=(12,8), pady=10, sticky="nsew")        self.connect_btn = ctk.CTkButton(bar, text="Connect", state="disabled", command=self.on_connect); self.connect_btn.grid(row=0, column=1, padx=8, pady=10, sticky="nsew")        self.disconnect_btn = ctk.CTkButton(bar, text="Disconnect", state="disabled", command=self.on_disconnect); self.disconnect_btn.grid(row=0, column=2, padx=8, pady=10, sticky="nsew")        self.status_lbl = ctk.CTkLabel(bar, text="Idle", text_color=THEME["text"]); self.status_lbl.grid(row=0, column=3, padx=8, pady=10, sticky="w")

        self.conn_group = ctk.CTkFrame(bar, fg_color="transparent"); self.conn_group.grid(row=0, column=6, padx=(8,8), pady=10, sticky="e")
        self.conn_dot = ctk.CTkFrame(self.conn_group, width=16, height=16, corner_radius=8, fg_color=THEME["red"]); self.conn_dot.pack(side="left", padx=(0,6))
        self.conn_label = ctk.CTkLabel(self.conn_group, text="Disconnected", text_color=THEME["text"]); self.conn_label.pack(side="left")

        theme = ctk.CTkSegmentedButton(bar, values=["light","dark"], command=lambda m: ctk.set_appearance_mode(m)); theme.set("dark"); theme.grid(row=0, column=7, padx=(8,0), sticky="nsew")        self.scale_menu = ctk.CTkOptionMenu(bar, values=["Auto","90%","100%","110%","125%"], command=self._change_scale); self.scale_menu.set("Auto"); self.scale_menu.grid(row=0, column=8, padx=(8,12), sticky="nsew")
        tabs_holder = ctk.CTkFrame(self, fg_color="transparent"); tabs_holder.grid(row=1, column=0, sticky="ew", padx=12, pady=(8,4)); tabs_holder.grid_columnconfigure(0, weight=1)
        self.tabs_strip = ctk.CTkFrame(tabs_holder, corner_radius=12); set_fg(self.tabs_strip, THEME["tab_inactive"]); set_border(self.tabs_strip, THEME["card_border"], 1)
        self.tabs_strip.grid(row=0, column=0, sticky="w")

        # Main area (left devices | resizer | right)
        main = ctk.CTkFrame(self, corner_radius=0); self.main = main; set_fg(main, THEME["bg"])
        main.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0,12))
        main.grid_columnconfigure(0, weight=0, minsize=int(self._dev_col_width))
        main.grid_columnconfigure(1, weight=0, minsize=self._sash_size)
        main.grid_columnconfigure(2, weight=1)
        main.grid_rowconfigure(1, weight=1)

        # Left devices card
        self.dev_card = dev_card = ctk.CTkFrame(main, corner_radius=14); set_fg(dev_card, THEME["card"]); set_border(dev_card, THEME["card_border"], 1)
        dev_card.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0,0), pady=8); dev_card.grid_columnconfigure(0, weight=1); dev_card.grid_rowconfigure(2, weight=1)
        hdr = ctk.CTkFrame(dev_card, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(10,4))
        # allow 3 columns: title (grow), toggle, sort
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_columnconfigure(1, weight=0)
        hdr.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(hdr, text="Devices", text_color=THEME["text"]).grid(row=0, column=0, sticky="w")
        self.dev_toggle_btn = ctk.CTkButton(hdr, text="▾", width=28, command=self._toggle_devices_panel); self.dev_toggle_btn.grid(row=0, column=1, sticky="e", padx=(6,6))

        # --- UPDATED: Filter menu (Devices | Unnamed Devices) ---
        self.dev_sort_var = tk.StringVar(value="Devices")
        self.dev_sort_menu = ctk.CTkOptionMenu(
            hdr,
            variable=self.dev_sort_var,
            values=["Devices", "Unnamed Devices"],
            command=lambda _=None: self._on_sort_changed()
        )
        self.dev_sort_menu.grid(row=0, column=2, sticky="e")

        self.dev_quick_frame = quick = ctk.CTkFrame(dev_card, fg_color="transparent"); quick.grid(row=1, column=0, sticky="ew", padx=10, pady=(0,6))
        self.connect_btn2 = ctk.CTkButton(quick, text="Connect", state="disabled", command=self.on_connect)
        self.disconnect_btn2 = ctk.CTkButton(quick, text="Disconnect", state="disabled", command=self.on_disconnect)
        self.connect_btn2.pack(side="left"); self.disconnect_btn2.pack(side="left", padx=(8,0))
        self.device_var = ctk.StringVar(value=""); self.device_list = ctk.CTkScrollableFrame(dev_card); set_fg(self.device_list, THEME["panel_alt"])
        self.device_list.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0,10))

        # Outer resizer
        self._sash = ctk.CTkFrame(main, width=self._sash_size, corner_radius=8); set_fg(self._sash, THEME["card_border"]); set_border(self._sash, THEME["card_border"], 0)
        self._sash.grid(row=0, column=1, rowspan=2, sticky="ns", padx=(8,8), pady=8)
        try: self._sash.configure(cursor="sb_h_double_arrow")
        except Exception: pass
        self._sash.bind("<Button-1>", self._on_sash_press)
        self._sash.bind("<B1-Motion>", self._on_sash_drag)
        self._sash.bind("<ButtonRelease-1>", self._on_sash_release)
        self._sash.bind("<Double-Button-1>", self._on_sash_reset)
        self._sash.bind("<Enter>", lambda e: set_fg(self._sash, THEME["tab_close_bg"]))
        self._sash.bind("<Leave>", lambda e: set_fg(self._sash, THEME["card_border"]))

        # Characteristic controls
        ctl_card = ctk.CTkFrame(main, corner_radius=14); self.ctl_card = ctl_card; set_fg(ctl_card, THEME["card"]); set_border(ctl_card, THEME["card_border"], 1)
        ctl_card.grid(row=0, column=2, sticky="nsew", padx=(0,0), pady=(8,6)); ctl_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(ctl_card, text="Characteristic Controls", text_color=THEME["text"]).grid(row=0, column=0, columnspan=6, sticky="w", padx=12, pady=(10,4))
        ctk.CTkLabel(ctl_card, text="Characteristic:", text_color=THEME["text"]).grid(row=1, column=0, sticky="w", padx=12, pady=6)
        self.char_var = ctk.StringVar(value="")
        self.char_combo = ctk.CTkComboBox(ctl_card, variable=self.char_var, values=[],  command=lambda _ : self._on_char_selected())
        self.char_combo.grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=6)

        # Install tooltip on the field itself, and hook dropdown open to attach item tooltips
        self._install_char_tooltip()

        self.props_lbl = ctk.CTkLabel(ctl_card, text="Props: -", text_color=THEME["muted"]); self.props_lbl.grid(row=1, column=4, sticky="e", padx=(8,12))
        self.read_btn = ctk.CTkButton(ctl_card, text="Read", state="disabled", command=self.on_read); self.read_btn.grid(row=2, column=0, padx=12, pady=(0,10), sticky="w")
        self.notify_btn = ctk.CTkButton(ctl_card, text="Subscribe", state="disabled", command=self.on_toggle_notify); self.notify_btn.grid(row=2, column=4, padx=(8,12), pady=(0,10), sticky="e")

        # Pages
        self.page_host = ctk.CTkFrame(main, corner_radius=14); set_fg(self.page_host, THEME["card"]); set_border(self.page_host, THEME["card_border"], 1)
        self.page_host.grid(row=1, column=2, sticky="nsew", padx=(0,0), pady=(0,8)); self.page_host.grid_columnconfigure(0, weight=1); self.page_host.grid_rowconfigure(0, weight=1)

        self._apply_dev_width()

    # ---------------------- Tooltip plumbing ---------------------- #
    def _tooltip_text_for_char(self) -> str:
        uuid = self._selected_uuid_from_combo()
        return f"UUID: {uuid}" if uuid else "UUID: -"

    def _install_char_tooltip(self):
        # Tooltip on the closed combobox
        self._char_tooltip = _HoverTooltip(self.char_combo, self._tooltip_text_for_char, delay_ms=250)
        # Also try to bind to its internal entry for better hover coverage
        try:
            entry = self.char_combo._entry  # private in CustomTkinter
            self._char_tooltip_entry = _HoverTooltip(entry, self._tooltip_text_for_char, delay_ms=250)
        except Exception:
            self._char_tooltip_entry = None

        # When user opens the dropdown, attach tooltips to *each* item inside the popup
        def _queue_hook(_evt=None):
            self._hook_char_dropdown_items(retries=0)
        self.char_combo.bind("<Button-1>", lambda e: self.after(30, _queue_hook), add="+")
        try:
            self.char_combo._dropdown_button.bind("<Button-1>", lambda e: self.after(30, _queue_hook), add="+")
        except Exception:
            pass

    def _walk_widgets(self, w):
        try:
            for ch in w.winfo_children():
                yield ch
                yield from self._walk_widgets(ch)
        except Exception:
            return

    def _hook_char_dropdown_items(self, retries=0):
        menu = getattr(self.char_combo, "_dropdown_menu", None)
        if not menu or not (hasattr(menu, "winfo_exists") and menu.winfo_exists()):
            if retries < 10:
                self.after(50, lambda: self._hook_char_dropdown_items(retries+1))
            return

        # Attach tooltips to any widget inside dropdown that has a 'text' (buttons/labels)
        count_added = 0
        for child in self._walk_widgets(menu):
            txt = None
            try:
                txt = child.cget("text")
            except Exception:
                pass
            if not txt:
                continue
            if getattr(child, "_uuid_tooltip_installed", False):
                continue

            def textfunc(t=txt):
                u = self.char_display_map.get(t, t)
                return f"UUID: {u}"

            try:
                _HoverTooltip(child, textfunc, delay_ms=0)
                child._uuid_tooltip_installed = True
                count_added += 1
            except Exception:
                pass

        if count_added == 0 and retries < 10:
            self.after(50, lambda: self._hook_char_dropdown_items(retries+1))

    # -------------------- END tooltip plumbing -------------------- #

    def _change_scale(self, value):
        if value == "Auto": self._auto_scale(); return
        pct = int(value.strip("%")); s = pct/100.0; ctk.set_widget_scaling(s)
        try: ctk.set_window_scaling(s)
        except Exception: pass
        self.max_tab_title_len = 26 if s >= 1.0 else max(16, int(26*s))
        for u in self.browser_tabs.keys(): self._update_tab_title(u)

    def set_status(self, s: str):
        self.status_lbl.configure(text=s); self.update_idletasks()

    # outer resizer
    def _clamp_dev_width(self, w: int) -> int:
        total = max(1, self.winfo_width()); right_min = 720
        max_by_window = max(self._dev_min, min(self._dev_max, total - right_min))
        return int(max(self._dev_min, min(max_by_window, w)))
    def _apply_dev_width(self):
        self._dev_col_width = self._clamp_dev_width(self._dev_col_width)
        try: self.main.grid_columnconfigure(0, minsize=int(self._dev_col_width))
        except Exception: pass
    def _on_sash_press(self, event):
        self._dragging = True; self._drag_start_x = event.x_root; self._dev_start_width = self._dev_col_width
    def _on_sash_drag(self, event):
        if not self._dragging: return
        dx = event.x_root - self._drag_start_x
        new_w = self._clamp_dev_width(self._dev_start_width + dx)
        if new_w != self._dev_col_width:
            self._dev_col_width = new_w; self._apply_dev_width()
    def _on_sash_release(self, event): self._dragging = False
    def _on_sash_reset(self, event): self._dev_col_width = 360; self._apply_dev_width()

    # ---------- Device helpers / sorting ----------
    def _dev_addr(self, d) -> str:
        return getattr(d, "address", getattr(d, "mac_address", "")) or ""
    def _dev_name(self, d) -> str:
        return (d.name or "").strip() or "(Unknown)"
    def _dev_rssi(self, d) -> Optional[int]:
        try:
            return int(getattr(d, "rssi", None)) if getattr(d, "rssi", None) is not None else None
        except Exception:
            return None

    def _on_sort_changed(self):
        self._apply_device_sort_in_place()
        self._refresh_device_list()

    def _apply_device_sort_in_place(self):
        """UPDATED: filter list by named vs unnamed devices."""
        mode = (self.dev_sort_var.get() or "Devices").strip()
        base = list(self.devices_unsorted)
        if mode == "Devices":
            # keep only those with a non-empty, non-'(Unknown)' name
            self.devices = [d for d in base if self._dev_name(d) != "(Unknown)"]
            return
        if mode == "Unnamed Devices":
            # keep only '(Unknown)' or empty names
            self.devices = [d for d in base if self._dev_name(d) == "(Unknown)"]
            return
        # fallback
        self.devices = base

    # devices
    def _toggle_devices_panel(self):
        if getattr(self, "_devices_collapsed", False): self._expand_devices_panel()
        else: self._collapse_devices_panel()
    def _collapse_devices_panel(self):
        if getattr(self, "_devices_collapsed", False): return
        if hasattr(self, "dev_quick_frame"): self.dev_quick_frame.grid_remove()
        if hasattr(self, "device_list"): self.device_list.grid_remove()
        if hasattr(self, "dev_card"): self.dev_card.grid_rowconfigure(2, weight=0)
        self.dev_toggle_btn.configure(text="▸"); self._devices_collapsed = True
    def _expand_devices_panel(self):
        if not getattr(self, "_devices_collapsed", False): return
        if hasattr(self, "dev_quick_frame"): self.dev_quick_frame.grid(, sticky="nsew")        if hasattr(self, "device_list"): self.device_list.grid(, sticky="nsew")        if hasattr(self, "dev_card"): self.dev_card.grid_rowconfigure(2, weight=1)
        self.dev_toggle_btn.configure(text="▾"); self._devices_collapsed = False
    def _set_connection_indicator(self, connected: bool, address: Optional[str] = None):
        if connected:
            self.conn_label.configure(text=f"Connected to {address}" if address else "Connected"); self._start_blink()
        else:
            self.conn_label.configure(text="Disconnected"); self._stop_blink(); self.conn_dot.configure(fg_color=THEME["red"])
    def _start_blink(self):
        self._blink_state = False
        if self._blink_job: self.after_cancel(self._blink_job)
        self._blink_tick()
    # def _blink_tick(self):
    #     self._blink_state = not self._blink_state
    #     self.conn_dot.configure(fg_color=THEME["green"] if self._blink_state else THEME["green_dim"])
    #     self._blink_job = self.after(600, self._blink_tick)
    def _blink_tick(self):
        # If we lost the BLE link, stop blinking and go red immediately
        if not (self.client and getattr(self.client, "is_connected", False)):
            self._stop_blink()
            return

        self._blink_state = not self._blink_state
        self.conn_dot.configure(fg_color=THEME["green"] if self._blink_state else THEME["green_dim"])
        self._blink_job = self.after(600, self._blink_tick)

    def _stop_blink(self):
        if self._blink_job:
            self.after_cancel(self._blink_job); self._blink_job = None
        self.conn_dot.configure(fg_color=THEME["red"])
    def _refresh_device_list(self):
        for c in self.device_list.winfo_children(): c.destroy()
        for idx, d in enumerate(self.devices):
            name = self._dev_name(d)
            addr = self._dev_addr(d)
            rssi = self._dev_rssi(d)
            rssi_txt = f"  RSSI: {rssi} dBm" if rssi is not None else ""
            rb = ctk.CTkRadioButton(self.device_list, text=f"{name}   [{addr}]{rssi_txt}", variable=self.device_var, value=str(idx), command=self._on_device_pick, )
            rb.pack(fill="x", padx=6, pady=3, anchor="w")
    def _on_device_pick(self):
        en = "normal" if self.device_var.get() else "disabled"
        self.connect_btn.configure(state=en); self.connect_btn2.configure(state=en)
    def _selected_device(self):
        v = self.device_var.get()
        if not v: return None
        i = int(v); return self.devices[i] if 0 <= i < len(self.devices) else None

    # actions
    def on_scan(self):
        self.set_status("Scanning…")
        self.scan_btn.configure(state="disabled"); self.connect_btn.configure(state="disabled"); self.connect_btn2.configure(state="disabled")
        self._pending_logs.clear()
        fut = self.bridge.run_coro(self._scan_async()); fut.add_done_callback(lambda _f: self.after(0, self._scan_done))
    async def _scan_async(self):
        self.devices = await BleakScanner.discover(timeout=5.0)
        # preserve "Found" order snapshot
        self.devices_unsorted = list(self.devices)
    def _scan_done(self):
        # apply current sort choice then refresh UI
        self._apply_device_sort_in_place()
        self._refresh_device_list(); self.set_status(f"Found {len(self.devices)} device(s)"); self.scan_btn.configure(state="normal")

    def on_connect(self):
        dev = self._selected_device()
        if not dev: return
        if self.client and getattr(self.client, "is_connected", False): self.on_disconnect()
        address = self._dev_addr(dev)
        if not address: return
        self.set_status(f"Connecting to {address} …")
        for b in (self.connect_btn, self.connect_btn2, self.disconnect_btn, self.disconnect_btn2): b.configure(state="disabled")
        fut = self.bridge.run_coro(self._connect_and_list(address)); fut.add_done_callback(lambda _f: self.after(0, self._post_connect_ui))

    async def _connect_and_list(self, address: str):
        self.client = BleakClient(address)
        self.char_index.clear(); self._populate_char_combo([])

        for ref in list(self.browser_tabs.values()): ref["frame"].destroy()
        self.browser_tabs.clear()
        for ref in list(self.char_pages.values()): ref["frame"].destroy()
        self.char_pages.clear(); self.tab_titles.clear(); self._pending_logs.clear()

        try:
            await self.client.connect(timeout=10.0)
            ok = bool(getattr(self.client, "is_connected", False))
            self.connected_address = address if ok else None

            # register disconnect callback
            if ok:
                try:
                    self.client.set_disconnected_callback(self._on_bleak_disconnected)
                except Exception:
                    pass

        except Exception as exc:
            self.connected_address = None
            self.after(0, lambda m=str(exc): self._status_only(f"Connect failed: {m}"))
            return

        self.after(0, lambda s=bool(getattr(self.client, "is_connected", False)): self._status_only(f"Connected: {s}"))

        try:
            services = getattr(self.client, "services", None)
            if not services or len(list(services)) == 0:
                get_services = getattr(self.client, "get_services", None)
                if callable(get_services): services = await get_services()
            if not services:
                self.after(0, lambda: self._status_only("No GATT services found."))
                return
        except Exception as exc:
            self.after(0, lambda m=f"Failed to obtain services: {exc}": self._status_only(m))
            return

        items: List[str] = []
        for svc in services:
            s_line = f"[Service] {svc.uuid}: {getattr(svc, 'description', '')}"
            for ch in svc.characteristics:
                uuid = str(ch.uuid); props = ",".join(ch.properties)
                c_line = f"[Char] {uuid}: {ch.description} (props: {props})"
                self._pending_logs.setdefault(uuid, []).append(s_line)
                self._pending_logs[uuid].append(c_line)
                self.char_index[uuid] = (str(svc.uuid), ch, ch.handle); items.append(uuid)
        self.after(0, lambda i=items: self._populate_char_combo(i))

    # --- mapping and dropdown updates ---
    def _populate_char_combo(self, items: List[str]):
        self._char_items_order = list(items)
        # Build display strings from saved names, fallback to uuid
        self.uuid_to_display = {u: self.saved_names.get(u, u) for u in items}
        self.char_display_map = {disp: u for u, disp in self.uuid_to_display.items()}
        self.char_combo.configure(values=list(self.uuid_to_display.values()))
        self.char_var.set("")
        self.props_lbl.configure(text="Props: -")
        self.read_btn.configure(state="disabled")
        self.notify_btn.configure(state="disabled")

    def _refresh_char_combo_names(self):
        # Rebuild names when a tab rename occurs
        items = self._char_items_order if self._char_items_order else list(self.char_index.keys())
        current_uuid = self._selected_uuid_from_combo()
        self.uuid_to_display = {u: self.saved_names.get(u, u) for u in items}
        self.char_display_map = {disp: u for u, disp in self.uuid_to_display.items()}
        self.char_combo.configure(values=list(self.uuid_to_display.values()))
        if current_uuid:
            self.char_var.set(self.uuid_to_display.get(current_uuid, current_uuid))

    def _selected_uuid_from_combo(self) -> str:
        sel = self.char_var.get()
        return self.char_display_map.get(sel, sel)
    # ----------------------------------------------------

    def _on_char_selected(self):
        uuid = self._selected_uuid_from_combo()
        props = []
        if uuid and uuid in self.char_index:
            _svc_uuid, ch, _handle = self.char_index[uuid]; props = list(getattr(ch, "properties", []))
        else:
            self.props_lbl.configure(text="Props: -"); self.read_btn.configure(state="disabled"); self.notify_btn.configure(state="disabled"); return
        self.props_lbl.configure(text=f"Props: {','.join(props) if props else '-'}")
        self.read_btn.configure(state=("normal" if "read" in props else "disabled"))
        self.notify_btn.configure(state=("normal" if ("notify" in props or "indicate" in props) else "disabled"))
        self.notify_btn.configure(text=("Unsubscribe" if self.notify_active_uuid == uuid else "Subscribe"))
        self._ensure_browser_tab(uuid); self._ensure_char_page(uuid); self._select_browser_tab(uuid); self._apply_props_to_panels(uuid)

    def _post_connect_ui(self):
        if self.client and getattr(self.client, "is_connected", False):
            self.set_status(f"Connected to {self.connected_address}"); self.disconnect_btn.configure(state="normal"); self.disconnect_btn2.configure(state="normal"); self._set_connection_indicator(True, self.connected_address)
        else:
            self.set_status("Disconnected"); self._set_connection_indicator(False)
        self.connect_btn.configure(state="normal"); self.connect_btn2.configure(state="normal")

    def on_disconnect(self):
        if not (self.client and getattr(self.client, "is_connected", False)):
            self.set_status("Disconnected"); self.disconnect_btn.configure(state="disabled"); self.disconnect_btn2.configure(state="disabled"); self._set_connection_indicator(False); return
        self.set_status("Disconnecting…")
        fut = self.bridge.run_coro(self._disconnect_async()); fut.add_done_callback(lambda _f: self.after(0, self._post_disconnect_ui))

    async def _disconnect_async(self):
        try:
            if self.notify_active_uuid:
                try:
                    if self.notify_active_uuid in self.char_index:
                        _, _, handle = self.char_index[self.notify_active_uuid]
                        await self.client.stop_notify(handle)
                except Exception: pass
                self.notify_active_uuid = None
            await self.client.disconnect()
        except Exception: pass

    def _post_disconnect_ui(self):
        self.set_status("Disconnected")
        self.disconnect_btn.configure(state="disabled")
        self.disconnect_btn2.configure(state="disabled")
        self.notify_btn.configure(text="Subscribe", state="disabled")
        self.read_btn.configure(state="disabled")
        self._set_connection_indicator(False)
        for u in list(self.char_pages.keys()):
            self._clear_decoded_for(u, which=None)
            self._close_graph_for(u)  # <— close graph windows on disconnect

    # def _on_bleak_disconnected(self, _client):
    #     self.connected_address = None
    #     self.notify_active_uuid = None
    #     self.after(0, self._post_disconnect_ui)

    def _on_bleak_disconnected(self, _client):
        self.connected_address = None
        self.notify_active_uuid = None

        # Flip the indicator NOW on the Tk thread (no delay).
        def _now():
            # This stops the blink and sets the dot to red + updates label
            self._set_connection_indicator(False)
            # Do the normal cleanup you already had (disables buttons, clears pages, etc.)
            self._post_disconnect_ui()

        self.after(0, _now)
    
    def _status_only(self, text: str): self.status_lbl.configure(text=text)

    # logging
    def log(self, text: str) -> None:
        m = re.match(r"^\[(READ|NOTIF|WRITE)\s+([0-9a-fA-F\-]+)\]", text)
        if not m: self._status_only(text); return
        kind = m.group(1).upper(); uuid = m.group(2)
        page = self.char_pages.get(uuid)
        if not page:
            self._pending_logs.setdefault(uuid, []).append(text); return
        self._append_to_char_log(uuid, line=text)
        if kind in ("READ","NOTIF"):
            line = self._compact_line(text) if self.compact_values.get() else text
            self._append_value_line(uuid, line)
    def _append_to_char_log(self, uuid: str, line: str):
        tx: ctk.CTkTextbox = self.char_pages[uuid]["log"]; tx.insert("end", line + "\n"); tx.see("end")
    def _append_value_line(self, uuid: str, line: str):
        vt: ctk.CTkTextbox = self.char_pages[uuid]["values_txt"]; vt.configure(state="normal"); vt.insert("end", line + "\n"); vt.see("end"); vt.configure(state="disabled")
    @staticmethod
    def _compact_line(text: str) -> str:
        m = re.search(r"\]\s+(.*)", text)
        if not m: return text
        rest = m.group(1); rest = re.split(r"\s…|\s\(len=", rest, maxsplit=1)[0]; rest = re.sub(r"\(Handle:[^)]+\)\s*", "", rest); return rest.strip()
    def _uuid_is_target(self, uuid: str) -> bool: return (uuid or "").lower() == TARGET_STATUS_UUID

    # read / write / notify
    def on_read(self):
        uuid = self._selected_uuid_from_combo()
        if not uuid: return
        fut = self.bridge.run_coro(self._read_async(uuid)); fut.add_done_callback(lambda _f: None)
    async def _read_async(self, uuid: str):
        try:
            data = await self.client.read_gatt_char(uuid)
            hex_str = " ".join(f"{b:02X}" for b in data[:64])
            msg = f"[READ {uuid}] {hex_str}" + (f" … (len={len(data)})" if len(data) > 64 else f" (len={len(data)})")
            self.after(0, lambda m=msg: self.log(m))
            self.after(0, lambda u=uuid, d=bytes(data): self._update_viewer(u, "read", d))
            if self._uuid_is_target(uuid) and len(data) >= 34:
                decoded = self._decode_status(bytes(data))
                self.after(0, lambda u=uuid, d=decoded: self._update_decoded_for(u, "read", d))
        except Exception as exc:
            self.after(0, lambda m=f"[READ {uuid}] Failed: {exc}": self.log(m))
    async def _write_async(self, uuid: str, payload: bytes):
        try:
            props = []
            if uuid in self.char_index:
                _svc_uuid, ch, _handle = self.char_index[uuid]; props = list(getattr(ch, "properties", []))
            noresp = "write-without-response" in props and "write" not in props
            await self.client.write_gatt_char(uuid, payload, response=not noresp)
            shown = " ".join(f"{b:02X}" for b in payload[:64])
            msg = f"[WRITE {uuid}] {shown}" + (" …" if len(payload) > 64 else "")
            self.after(0, lambda m=msg: self.log(m))
        except Exception as exc:
            self.after(0, lambda m=f"[WRITE {uuid}] Failed: {exc}": self.log(m))
    def on_toggle_notify(self):
        uuid = self._selected_uuid_from_combo()
        if not uuid: return
        if self.notify_active_uuid == uuid:
            fut = self.bridge.run_coro(self._stop_notify_async(uuid)); fut.add_done_callback(lambda _f: self.after(0, self._notify_stopped_ui_for, uuid))
        else:
            fut = self.bridge.run_coro(self._start_notify_async(uuid)); fut.add_done_callback(lambda _f: self.after(0, self._notify_started_ui_for, uuid))
    async def _start_notify_async(self, uuid: str):
        try:
            if uuid in self.char_index:
                _svc_uuid, _ch, handle = self.char_index[uuid]
                await self.client.start_notify(handle, self._notification_handler)
                self.notify_active_uuid = uuid
                self.after(0, lambda: self._append_to_char_log(uuid, f"[NOTIFY {uuid}] Subscribed using handle {handle}"))
            else:
                self.after(0, lambda: self._append_to_char_log(uuid, f"[NOTIFY {uuid}] Characteristic not found in index"))
        except Exception as exc:
            self.after(0, lambda m=f"[NOTIFY {uuid}] Failed to subscribe: {exc}": self.log(m))
    async def _stop_notify_async(self, uuid: str):
        try:
            if uuid in self.char_index:
                _svc_uuid, _ch, handle = self.char_index[uuid]
                await self.client.stop_notify(handle)
                self.after(0, lambda: self._append_to_char_log(uuid, f"[NOTIFY {uuid}] Unsubscribed"))
            else:
                self.after(0, lambda: self._append_to_char_log(uuid, f"[NOTIFY {uuid}] Characteristic not found in index"))
        except Exception as exc:
            self.after(0, lambda m=f"[NOTIFY {uuid}] Failed to unsubscribe: {exc}": self.log(m))
        finally:
            if self.notify_active_uuid == uuid: self.notify_active_uuid = None
    def _notification_handler(self, sender, data: bytearray):
        if isinstance(sender, BleakGATTCharacteristic): uuid = str(sender.uuid).lower()
        else:
            uuid = "Unknown"
            for char_uuid, (_svc_uuid, _ch, handle) in self.char_index.items():
                if handle == sender: uuid = char_uuid.lower(); break
        b = bytes(data)
        hex_str = " ".join(f"{x:02X}" for x in b[:64])
        msg = f"[NOTIF {uuid if uuid else 'Unknown'}] {hex_str}" + (f" … (len={len(b)})" if len(b) > 64 else f" (len={len(b)})")
        self.after(0, lambda m=msg: self.log(m))
        self.after(0, lambda u=uuid, d=b: self._update_viewer(u, "notify", d))
        if self._uuid_is_target(uuid) and len(b) >= 34:
            decoded = self._decode_status(b)
            self.after(0, lambda u=uuid, d=decoded: self._update_decoded_for(u, "notify", d))

    # tabs
    def _update_tab_title(self, uuid: str):
        if uuid not in self.browser_tabs: return
        raw = self.tab_titles.get(uuid, uuid)
        shown = (raw[: self.max_tab_title_len - 1] + "…") if len(raw) > self.max_tab_title_len else raw
        self.browser_tabs[uuid]["btn"].configure(text=shown)
    def _ensure_browser_tab(self, uuid: str):
        if uuid in self.browser_tabs: return
        self.tab_titles[uuid] = self.saved_names[uuid] if uuid in self.saved_names else uuid
        tab = ctk.CTkFrame(self.tabs_strip, corner_radius=12); set_fg(tab, THEME["tab_inactive"]); set_border(tab, THEME["card_border"], 1)
        tab.pack(side="left", padx=(8,8), pady=6)
        btn = ctk.CTkButton(tab, text="", width=200, height=26, command=lambda u=uuid: self._select_browser_tab(u))
        btn.grid(row=0, column=0, padx=(10,6), pady=4, sticky="w")
        btn.bind("<Double-Button-1>", lambda e, u=uuid: self._prompt_rename_tab(u))
        btn.bind("<Button-3>", lambda e, u=uuid: self._open_tab_menu(e, u))
        tab.bind("<Button-3>", lambda e, u=uuid: self._open_tab_menu(e, u))
        close = ctk.CTkButton(tab, text="×", width=26, height=26, fg_color=THEME["tab_close_bg"], command=lambda u=uuid: self._close_browser_tab(u))
        close.grid(row=0, column=1, padx=(0,8), pady=4, sticky="nsew")        self.browser_tabs[uuid] = {"frame": tab, "btn": btn, "close": close}
        self._update_tab_title(uuid); self._ensure_char_page(uuid)
    def _open_tab_menu(self, event, uuid: str):
        self._tab_menu_uuid = uuid
        try: self._tab_menu.tk_popup(event.x_root, event.y_root)
        finally: self._tab_menu.grab_release()
    def _prompt_rename_tab(self, uuid: Optional[str]):
        if not uuid: return
        try:
            dialog = ctk.CTkInputDialog(text="Enter a name for this tab:", title="Rename tab")
            new_name = dialog.get_input()
        except Exception:
            import tkinter.simpledialog as sd; new_name = sd.askstring("Rename tab", "Enter a name for this tab:")
        if new_name:
            new_name = new_name.strip()
            if new_name:
                self.tab_titles[uuid] = new_name; self.saved_names[uuid] = new_name; self._save_saved_names()
                self._update_tab_title(uuid); self._refresh_page_header(uuid)
                self._refresh_char_combo_names()
    def _select_browser_tab(self, uuid: str):
        self.active_tab_uuid = uuid
        for u, ref in self.browser_tabs.items(): set_fg(ref["frame"], THEME["tab_active"] if u == uuid else THEME["tab_inactive"])
        self._show_char_page(uuid)
        disp = self.uuid_to_display.get(uuid, uuid)
        if self.char_var.get() != disp:
            self.char_var.set(disp); self._on_char_selected()
    def _close_browser_tab(self, uuid: Optional[str]):
        if not uuid: return
        if self.notify_active_uuid == uuid:
            try: self.bridge.run_coro(self._stop_notify_async(uuid)).result(timeout=1.0)
            except Exception: pass
        # close graph if open
        self._close_graph_for(uuid)
        ref = self.browser_tabs.pop(uuid, None)
        if ref: ref["frame"].destroy()
        page = self.char_pages.pop(uuid, None)
        if page: page["frame"].destroy()
        self.tab_titles.pop(uuid, None)
        if self.browser_tabs:
            other_uuid = next(iter(self.browser_tabs.keys())); self._select_browser_tab(other_uuid)
        else:
            self.active_tab_uuid = None

    # per-characteristic page
    def _create_box(self, parent, title_text: str):
        box = ctk.CTkFrame(parent, corner_radius=12); set_fg(box, THEME["panel"]); set_border(box, THEME["card_border"], 1)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=title_text, anchor="w", text_color=THEME["text"]).grid(row=0, column=0, sticky="ew", padx=10, pady=(8,2))
        return box

    def _ensure_char_page(self, uuid: str):
        if uuid in self.char_pages: return
        page_scroll = ctk.CTkScrollableFrame(self.page_host, corner_radius=14); set_fg(page_scroll, THEME["panel_alt"]); set_border(page_scroll, THEME["card_border"], 1)
        page_scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10); page_scroll.grid_columnconfigure(0, weight=1)
        page = ctk.CTkFrame(page_scroll, fg_color="transparent"); page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1); page.grid_rowconfigure(3, weight=1)
        page_container_ref = page_scroll

        title = self.tab_titles.get(uuid, uuid); props_text = "-"
        if uuid in self.char_index:
            _svc, ch, _h = self.char_index[uuid]; props_text = ",".join(getattr(ch, "properties", [])) or "-"
        props_lbl = ctk.CTkLabel(page, text=f"{title}  [{uuid}]\nProps: {props_text}", anchor="w", justify="left", text_color=THEME["text"])
        props_lbl.grid(row=0, column=0, sticky="ew", padx=10, pady=(8,6))

        log_hdr = ctk.CTkFrame(page, fg_color="transparent"); log_hdr.grid(row=1, column=0, sticky="ew", padx=10, pady=(4,0)); log_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_hdr, text="Log / Services", text_color=THEME["text"]).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(log_hdr, text="Clear", width=70, command=lambda u=uuid: self._clear_page_log(u)).grid(row=0, column=1, sticky="e")

        log_tx = ctk.CTkTextbox(page, wrap="none", font=self.font_body, height=140); log_tx.grid(row=2, column=0, sticky="ew", padx=10, pady=(6,10))
        hide_ctk_textbox_scrollbars(log_tx)

        decoded_container = ctk.CTkFrame(page, fg_color="transparent"); decoded_container.grid(row=6, column=0, sticky="ew", padx=10, pady=(0,10))
        decoded_container.grid_columnconfigure(0, weight=1); decoded_container.grid_columnconfigure(1, weight=0)
        d_read_box = self._create_box(decoded_container, "Decoded (READ)"); d_read_box.grid(row=0, column=0, sticky="nsew", padx=(0,6))
        d_read_frame = ctk.CTkFrame(d_read_box, fg_color="transparent"); d_read_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(2,10))
        d_notify_box = self._create_box(decoded_container, "Decoded (NOTIFY)"); d_notify_box.grid(row=0, column=1, sticky="nsew", padx=(6,0))
        d_notify_frame = ctk.CTkFrame(d_notify_box, fg_color="transparent"); d_notify_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(2,10))
        d_notify_box.grid_remove()

        values_hdr = ctk.CTkFrame(page, fg_color="transparent"); values_hdr.grid(row=4, column=0, sticky="ew", padx=10, pady=(0,0)); values_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(values_hdr, text="Values (READ / NOTIFY)").grid(row=0, column=0, sticky="w")
        ctk.CTkCheckBox(values_hdr, text="Compact", variable=self.compact_values).grid(row=0, column=1, sticky="e")
        values_tx = ctk.CTkTextbox(page, wrap="none", font=self.font_body, height=100); values_tx.configure(state="disabled")
        values_tx.grid(row=5, column=0, sticky="ew", padx=10, pady=(6,10)); hide_ctk_textbox_scrollbars(values_tx)

        boxes = ctk.CTkFrame(page, fg_color="transparent"); boxes.grid(row=3, column=0, sticky="nsew", padx=10, pady=(0,10)); boxes.grid_rowconfigure(0, weight=1)

        read_box = self._create_box(boxes, "READ")
        notify_box = self._create_box(boxes, "NOTIFY")
        write_box  = self._create_box(boxes, "WRITE")
        for bx in (read_box, notify_box, write_box): bx.grid_rowconfigure(2, weight=1)

        # READ controls
        r_ctrl = ctk.CTkFrame(read_box, fg_color="transparent"); r_ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=(4,4)); r_ctrl.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(r_ctrl, text="Byte Size:").grid(row=0, column=0, padx=(0,8), sticky="nsew")        r_size_var = ctk.StringVar(value="1")
        r_size_entry = ctk.CTkEntry(r_ctrl, textvariable=r_size_var, width=80); r_size_entry.grid(row=0, column=1, sticky="w")
        r_create_btn = ctk.CTkButton(r_ctrl, text="Create Byte Editor", command=lambda u=uuid: self._on_create_read_editor_for(u)); r_create_btn.grid(row=0, column=2, padx=(8,8), sticky="nsew")        r_bytes_lbl = ctk.CTkLabel(r_ctrl, text="Bytes: 0", text_color=THEME["muted"]); r_bytes_lbl.grid(row=0, column=4, sticky="e")
        r_btn = ctk.CTkButton(r_ctrl, text="Read", command=lambda u=uuid: self._read_from(u)); r_btn.grid(row=0, column=5, padx=(10,0), sticky="e")
        r_editor = ctk.CTkScrollableFrame(read_box, fg_color="transparent", ); r_editor.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0,8)); r_editor.grid_columnconfigure(0, weight=1)

        # NOTIFY controls
        n_ctrl = ctk.CTkFrame(notify_box, fg_color="transparent"); n_ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=(4,4))
        for col in range(10): n_ctrl.grid_columnconfigure(col, weight=(1 if col == 3 else 0))
        ctk.CTkLabel(n_ctrl, text="Byte Size:").grid(row=0, column=0, padx=(0,8), sticky="nsew")        n_size_var = ctk.StringVar(value="34"); n_size_entry = ctk.CTkEntry(n_ctrl, textvariable=n_size_var, width=80); n_size_entry.grid(row=0, column=1, sticky="w")
        n_create_btn = ctk.CTkButton(n_ctrl, text="Create Byte Editor", command=lambda u=uuid: self._on_create_notify_editor_for(u)); n_create_btn.grid(row=0, column=2, padx=(8,8), sticky="nsew")        n_bytes_lbl = ctk.CTkLabel(n_ctrl, text="Bytes: 0", text_color=THEME["muted"]); n_bytes_lbl.grid(row=0, column=4, sticky="e")
        n_btn = ctk.CTkButton(n_ctrl, text="Subscribe", command=lambda u=uuid: self._toggle_notify_for(u)); n_btn.grid(row=0, column=5, padx=(10,0), sticky="e")
        n_make_calc_btn = ctk.CTkButton(n_ctrl, text="Create Value", command=lambda u=uuid: self._prompt_add_notify_calc(u)); n_make_calc_btn.grid(row=0, column=8, padx=(8,0), sticky="e")

        # NEW: Graph button (to the right of "Create Value")
        n_graph_btn = ctk.CTkButton(n_ctrl, text="Graph", command=lambda u=uuid: self._open_graph_window(u))
        n_graph_btn.grid(row=0, column=9, padx=(8,0), sticky="e")

        n_body = ctk.CTkFrame(notify_box, fg_color="transparent"); n_body.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0,8))
        n_body.grid_columnconfigure(0, weight=2); n_body.grid_columnconfigure(1, weight=1); n_body.grid_rowconfigure(0, weight=1)
        n_editor = ctk.CTkScrollableFrame(n_body, fg_color="transparent", ); n_editor.grid(row=0, column=0, sticky="nsew", padx=(0,8)); n_editor.grid_columnconfigure(0, weight=1)
        n_calc_box = self._create_box(n_body, "Computed Values (NOTIFY)"); n_calc_box.grid(row=0, column=1, sticky="nsew", padx=(8,0))
        n_calc_box.grid_columnconfigure(0, weight=1); n_calc_box.grid_rowconfigure(1, weight=1)
        calc_canvas = tk.Canvas(n_calc_box, highlightthickness=0, bg=THEME["panel"]); calc_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2,10))
        calc_sb = ctk.CTkScrollbar(n_calc_box); calc_sb.grid(row=1, column=1, sticky="ns", padx=(0,10), pady=(2,10))
        calc_canvas.configure(yscrollcommand=calc_sb.set); calc_sb.configure(command=calc_canvas.yview)
        calc_inner = ctk.CTkFrame(calc_canvas, fg_color="transparent"); inner_window = calc_canvas.create_window((0, 0), window=calc_inner, anchor="nw")
        def _on_inner_config(event=None):
            calc_inner.update_idletasks(); calc_canvas.configure(scrollregion=(0, 0, calc_canvas.winfo_width(), calc_inner.winfo_reqheight()))
        def _on_canvas_config(event):
            calc_canvas.itemconfigure(inner_window, width=event.width); _on_inner_config()
        calc_inner.bind("<Configure>", _on_inner_config); calc_canvas.bind("<Configure>", _on_canvas_config)
        def _on_wheel(event): calc_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        calc_canvas.bind("<MouseWheel>", _on_wheel); calc_inner.bind("<MouseWheel>", _on_wheel)

        # WRITE controls
        w_ctrl = ctk.CTkFrame(write_box, fg_color="transparent"); w_ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=(4,4)); w_ctrl.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(w_ctrl, text="Byte Size:").grid(row=0, column=0, padx=(0,8), sticky="nsew")        w_size_var = ctk.StringVar(value="1"); w_size_entry = ctk.CTkEntry(w_ctrl, textvariable=w_size_var, width=80); w_size_entry.grid(row=0, column=1, sticky="w")
        w_create_btn = ctk.CTkButton(w_ctrl, text="Create Byte Editor", command=lambda u=uuid: self._on_create_write_editor_for(u)); w_create_btn.grid(row=0, column=2, padx=(8,8), sticky="nsew")        w_bytes_lbl = ctk.CTkLabel(w_ctrl, text="Bytes: 0", text_color=THEME["muted"]); w_bytes_lbl.grid(row=0, column=4, sticky="e")
        w_btn = ctk.CTkButton(w_ctrl, text="Write", command=lambda u=uuid: self._write_from(u)); w_btn.grid(row=0, column=5, padx=(10,0), sticky="e")

        # NEW: Save/Load buttons stacked at the far-right of the WRITE controls
        preset_col = ctk.CTkFrame(w_ctrl, fg_color="transparent")
        preset_col.grid(row=0, column=6, padx=(10,0), sticky="e")
        w_save_btn = ctk.CTkButton(preset_col, text="Save As..", width=120, command=lambda u=uuid: self._on_write_save_preset(u))
        w_load_btn = ctk.CTkButton(preset_col, text="Load Saved", width=120, command=lambda u=uuid: self._on_write_load_preset(u))
        w_save_btn.pack(fill="x")
        w_load_btn.pack(fill="x", pady=(6,0))

        # ---------- NEW: Paste bar (row 1 of w_ctrl) ----------
        paste_row = ctk.CTkFrame(w_ctrl, fg_color="transparent")
        paste_row.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(6,0))
        paste_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(paste_row, text="Paste hex:").grid(row=0, column=0, padx=(0,8), sticky="w")
        w_paste_var = tk.StringVar(value="")
        w_paste_entry = ctk.CTkEntry(paste_row, textvariable=w_paste_var)

        # Auto-fill the byte boxes shortly after paste
        def _deferred_fill(_evt=None, u=uuid):
            # wait a tick so the pasted text is in the entry, then fill
            self.after(30, lambda: self._on_write_paste_fill(u))

        # Trigger fill on paste (does NOT write)
        w_paste_entry.bind("<<Paste>>", _deferred_fill)
        w_paste_entry.bind("<Control-v>", _deferred_fill)   # keyboard paste
        # (Optional) if you also want Enter to fill, uncomment:
        # w_paste_entry.bind("<Return>", _deferred_fill)


        w_paste_entry.grid(row=0, column=1, sticky="ew")
        w_paste_btn = ctk.CTkButton(paste_row, text="Fill&Write", width=80, command=lambda u=uuid: self._on_write_paste_fill(u))
        w_paste_btn.grid(row=0, column=2, padx=(8,0), sticky="nsew")
        # auto-fill when user pastes (Ctrl+V) or presses Enter
        # def _deferred_fill(_evt=None, u=uuid):
        #     # run shortly after the actual paste so the text is in the entry
        #     self.after(30, lambda: self._on_write_paste_fill(u))
        # try:
        #     # w_paste_entry.bind("<<Paste>>", _deferred_fill)
        #     # w_paste_entry.bind("<Control-v>", _deferred_fill)
        #     # w_paste_entry.bind("<Return>", _deferred_fill)
        # except Exception:
        #     pass
        # # ------------------------------------------------------

        w_editor = ctk.CTkScrollableFrame(write_box, fg_color="transparent", ); w_editor.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0,8)); w_editor.grid_columnconfigure(0, weight=1)

        # Inner splitters (rounded)
        sash1 = ctk.CTkFrame(boxes, width=self._inner_sash_size, corner_radius=8)
        sash2 = ctk.CTkFrame(boxes, width=self._inner_sash_size, corner_radius=8)
        for s in (sash1, sash2):
            set_fg(s, THEME["card_border"])
            try: s.configure(cursor="sb_h_double_arrow")
            except Exception: pass
            s.bind("<Enter>",  lambda e, ss=s: set_fg(ss, THEME["tab_close_bg"]))
            s.bind("<Leave>",  lambda e, ss=s: set_fg(ss, THEME["card_border"]))
        sash1.bind("<Button-1>",        lambda e, u=uuid: self._inner_sash_press(u, which=1, event=e))
        sash1.bind("<B1-Motion>",       lambda e, u=uuid: self._inner_sash_drag(u, which=1, event=e))
        sash1.bind("<ButtonRelease-1>", lambda e, u=uuid: self._inner_sash_release(u, which=1, event=e))
        sash1.bind("<Double-Button-1>", lambda e, u=uuid: self._inner_reset(u))
        sash2.bind("<Button-1>",        lambda e, u=uuid: self._inner_sash_press(u, which=2, event=e))
        sash2.bind("<B1-Motion>",       lambda e, u=uuid: self._inner_sash_drag(u, which=2, event=e))
        sash2.bind("<ButtonRelease-1>", lambda e, u=uuid: self._inner_sash_release(u, which=2, event=e))
        sash2.bind("<Double-Button-1>", lambda e, u=uuid: self._inner_reset(u))

        # Per-page splitter state + GRAPH state
        self.char_pages[uuid] = {
            "frame": page_container_ref,
            "content_frame": page,
            "props": props_lbl,
            "log": log_tx,
            "values_txt": values_tx,
            "decoded_container": decoded_container,
            "decoded_read_frame": d_read_frame,
            "decoded_notify_frame": d_notify_frame,
            "decoded_read_rows": {},
            "decoded_notify_rows": {},
            "last_notify_bytes": b"",
            "boxes_container": boxes,
            "split": {
                "w_r": 1.0, "w_n": 1.0, "w_w": 1.0,
                "min_r": 220, "min_n": 320, "min_w": 380,
                "drag": 0, "start_x": 0, "total_px": 0,
                "r_px": 0.0, "n_px": 0.0, "w_px": 0.0,
                "sash1": sash1, "sash2": sash2,
            },
            "read": {
                "box": read_box, "ctrl": r_ctrl, "size_var": r_size_var, "size_entry": r_size_entry,
                "create_btn": r_create_btn, "bytes_lbl": r_bytes_lbl, "btn": r_btn,
                "editor_frame": r_editor, "name_vars": [], "value_labels": [], "created": False,
            },
            "notify": {
                "box": notify_box, "ctrl": n_ctrl, "size_var": n_size_var, "size_entry": n_size_entry,
                "create_btn": n_create_btn, "bytes_lbl": n_bytes_lbl, "btn": n_btn,
                "editor_frame": n_editor, "calc_canvas": calc_canvas, "calc_frame": calc_inner,
                "calc_defs": [], "name_vars": [], "value_labels": [], "created": False,
            },
            "write": {
                "box": write_box, "ctrl": w_ctrl, "size_var": w_size_var, "size_entry": w_size_entry,
                "create_btn": w_create_btn, "bytes_lbl": w_bytes_lbl, "btn": w_btn,
                "save_btn": w_save_btn, "load_btn": w_load_btn,
                "paste_entry": w_paste_entry, "paste_var": w_paste_var, "paste_btn": w_paste_btn,
                "editor_frame": w_editor, "name_vars": [], "entry_vars": [], "created": False,
            },
            # --- Graph state per characteristic ---
            "graph": {
                "win": None, "fig": None, "ax": None, "canvas": None,
                "picker_var": None, "picker_menu": None,
                "series": {},            # name -> {times:[], values:[], line:Line2D}
                "start_time": time.time(),
                "pending": False,
            },
        }

        hide_ctk_textbox_scrollbars(self.char_pages[uuid]["log"])
        hide_ctk_textbox_scrollbars(self.char_pages[uuid]["values_txt"])
        if uuid in self._pending_logs:
            for line in self._pending_logs.pop(uuid): self._append_to_char_log(uuid, line)
        self._apply_props_to_panels(uuid); self._restore_notify_calcs(uuid)
        try: self._apply_responsive_layout(uuid, max(1, self.winfo_width()))
        except Exception: pass

    def _refresh_page_header(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        title = self.tab_titles.get(uuid, uuid); props_text = "-"
        if uuid in self.char_index:
            _svc, ch, _h = self.char_index[uuid]; props_text = ",".join(getattr(ch, "properties", [])) or "-"
        page["props"].configure(text=f"{title}  [{uuid}]\nProps: {props_text}")
        self._apply_props_to_panels(uuid)

    def _show_char_page(self, uuid: str):
        for u, p in self.char_pages.items(): p["frame"].grid_remove()
        if uuid in self.char_pages:
            self.char_pages[uuid]["frame"].grid(, sticky="nsew")            self.char_pages[uuid]["notify"]["btn"].configure(text=("Unsubscribe" if self.notify_active_uuid == uuid else "Subscribe"))
            self._refresh_page_header(uuid)
        # Keep dropdown in sync with the current tab (display name)
        disp = self.uuid_to_display.get(uuid, uuid)
        if self.char_var.get() != disp:
            self.char_var.set(disp); self._on_char_selected()

    def _clear_page_log(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        page["log"].delete("0.0", "end")

    def _get_props_for(self, uuid: str) -> set:
        props = set()
        if uuid in self.char_index:
            _svc, ch, _h = self.char_index[uuid]
            props = set(getattr(ch, "properties", []))
        return props

    def _enable_panel(self, panel: Dict, enabled: bool):
        # Also handle save/load/paste when present
        for key in ("size_entry", "create_btn", "btn", "save_btn", "load_btn", "paste_entry", "paste_btn"):
            if key in panel:
                try: panel[key].configure(state=("normal" if enabled else "disabled"))
                except Exception: pass

    def _apply_props_to_panels(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        props = self._get_props_for(uuid)
        can_read = "read" in props
        can_notify = ("notify" in props) or ("indicate" in props)
        can_write = ("write" in props) or ("write-without-response" in props)
        self._enable_panel(page["read"], can_read)
        self._enable_panel(page["notify"], can_notify)
        self._enable_panel(page["write"], can_write)
        if can_write and not page["write"]["created"]: page["write"]["btn"].configure(state="disabled")
        if can_read: page["decoded_read_frame"].master.grid(, sticky="nsew")        else: page["decoded_read_frame"].master.grid_remove()
        page["decoded_notify_frame"].master.grid_remove()
        page["notify"]["btn"].configure(text=("Unsubscribe" if (self.notify_active_uuid == uuid and can_notify) else "Subscribe"))

    # editors
    def _build_viewer_rows(
        self,
        frame,
        size: int,
        name_vars: List[ctk.StringVar],
        value_labels: List[ctk.CTkLabel],
    ):
        # clear
        for w in frame.winfo_children():
            w.destroy()
        name_vars.clear()
        value_labels.clear()

        # header
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=3, sticky="nsew", pady=(0, 5))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

        bold_font = self.font_body if getattr(self, "font_body", None) else ("Arial", 11, "bold")
        ctk.CTkLabel(header, text="Byte Name",   font=bold_font).grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        ctk.CTkLabel(header, text="Value (Hex)", font=bold_font).grid(row=0, column=1, padx=(0, 10), sticky="nsew")
        ctk.CTkLabel(header, text="Index",       font=bold_font).grid(row=0, column=2,                sticky="nsew")

        # rows
        for i in range(size):
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.grid(row=i + 1, column=0, columnspan=3, sticky="nsew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=1)
            row.grid_columnconfigure(2, weight=0)

            nvar = ctk.StringVar(value=f"Byte {i + 1}")
            ctk.CTkEntry(row, textvariable=nvar).grid(row=0, column=0, padx=(0, 10), sticky="nsew")
            name_vars.append(nvar)

            val_lbl = ctk.CTkLabel(row, text="--")
            val_lbl.grid(row=0, column=1, padx=(0, 10), sticky="nsew")
            value_labels.append(val_lbl)

            ctk.CTkLabel(row, text=f"#{i}", text_color=THEME["muted"]).grid(row=0, column=2, sticky="nsew")

    def _on_create_notify_editor_for(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        try: size = max(1, int(page["notify"]["size_var"].get()))
        except ValueError: self._append_to_char_log(uuid, f"[{uuid}] Error: invalid NOTIFY byte size"); return
        self._build_viewer_rows(page["notify"]["editor_frame"], size, page["notify"]["name_vars"], page["notify"]["value_labels"])
        page["notify"]["bytes_lbl"].configure(text=f"Bytes: {size}"); page["notify"]["created"] = True
        self._apply_saved_byte_names(uuid, "notify"); self._attach_name_var_traces(uuid, "notify")
    def _on_create_write_editor_for(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        try: size = max(1, int(page["write"]["size_var"].get()))
        except ValueError: self._append_to_char_log(uuid, f"[{uuid}] Error: invalid WRITE byte size"); return
        self._build_write_rows(page["write"]["editor_frame"], size, page["write"]["name_vars"], page["write"]["entry_vars"])
        page["write"]["bytes_lbl"].configure(text=f"Bytes: {size}"); page["write"]["created"] = True
        self._apply_saved_byte_names(uuid, "write"); self._attach_name_var_traces(uuid, "write")
        props = self._get_props_for(uuid); can_write = ("write" in props) or ("write-without-response" in props)
        page["write"]["btn"].configure(state=("normal" if can_write else "disabled"))

    def _apply_saved_byte_names(self, uuid: str, which: str) -> None:
        page = self.char_pages.get(uuid)
        if not page or which not in ("read","notify","write"): return
        prefs = self._uuid_prefs(uuid); saved = prefs.get("byte_names", {}).get(which, [])
        vars_list = page[which]["name_vars"]
        for i, v in enumerate(vars_list):
            if i < len(saved) and saved[i]: v.set(saved[i])
    def _persist_byte_names(self, uuid: str, which: str) -> None:
        page = self.char_pages.get(uuid)
        if not page or which not in ("read","notify","write"): return
        vars_list = page[which]["name_vars"]; names = [v.get() for v in vars_list] if vars_list else []
        prefs = self._uuid_prefs(uuid); prefs["byte_names"][which] = names; self._save_saved_prefs()
    def _attach_name_var_traces(self, uuid: str, which: str) -> None:
        page = self.char_pages.get(uuid)
        if not page or which not in ("read","notify","write"): return
        for v in page[which]["name_vars"]:
            try: v.trace_add("write", lambda *_args, u=uuid, w=which: self._persist_byte_names(u, w))
            except Exception: pass

    def _update_viewer(self, uuid: str, which: str, data: bytes):
        page = self.char_pages.get(uuid)
        if not page or which not in ("read","notify"): return
        pnl = page[which]
        if not pnl["created"]:
            if which == "notify":
                page["last_notify_bytes"] = bytes(data); self._recompute_notify_calcs(uuid)
            return
        labels: List[ctk.CTkLabel] = pnl["value_labels"]
        for i, lbl in enumerate(labels):
            val = data[i] if i < len(data) else None; lbl.configure(text=f"{val:02X}" if val is not None else "--")
        if which == "notify":
            page["last_notify_bytes"] = bytes(data[: len(labels)]); self._recompute_notify_calcs(uuid)

    # notify → write helpers
    def _get_current_notify_bytes(self, uuid: str) -> Optional[bytes]:
        page = self.char_pages.get(uuid)
        if not page: return None
        data: bytes = page.get("last_notify_bytes", b"") or b""
        if data: return data
        pnl = page["notify"]
        if not pnl["created"]: return None
        out: List[int] = []
        for lbl in pnl["value_labels"]:
            t = lbl.cget("text")
            if not t or t == "--": out.append(0)
            else:
                try: out.append(int(t, 16) & 0xFF)
                except Exception: out.append(0)
        return bytes(out) if out else None
    def _ensure_write_editor_size(self, uuid: str, size: int):
        page = self.char_pages.get(uuid)
        if not page: return
        write = page["write"]
        if not write["created"] or len(write["entry_vars"]) != size:
            write["size_var"].set(str(size)); self._on_create_write_editor_for(uuid)
    def _fill_write_from_bytes(self, uuid: str, data: bytes):
        page = self.char_pages.get(uuid)
        if not page: return
        self._ensure_write_editor_size(uuid, len(data))
        write = page["write"]
        for i, vvar in enumerate(write["entry_vars"]): vvar.set(f"{data[i]:02X}" if i < len(data) else "00")
    def _read_from(self, uuid: str):
        fut = self.bridge.run_coro(self._read_async(uuid)); fut.add_done_callback(lambda _f: None)
    def _get_write_bytes_for(self, uuid: str) -> Optional[bytes]:
        page = self.char_pages.get(uuid)
        if not page: return None
        if not page["write"]["created"]:
            self._append_to_char_log(uuid, f"[{uuid}] Create the WRITE editor first."); return None
        entries: List[ctk.StringVar] = page["write"]["entry_vars"]; out: List[int] = []
        for i, v in enumerate(entries):
            value = v.get().strip()
            if not value:
                self._append_to_char_log(uuid, f"[{uuid}] Error: Byte #{i} value is empty"); return None
            try:
                if len(value) == 1: value = "0" + value
                out.append(int(value, 16) & 0xFF)
            except ValueError:
                self._append_to_char_log(uuid, f"[{uuid}] Error: Invalid hex value '{value}' for byte #{i}"); return None
        return bytes(out)
    def _write_from(self, uuid: str):
        payload = self._get_write_bytes_for(uuid)
        if payload is None: return
        fut = self.bridge.run_coro(self._write_async(uuid, payload)); fut.add_done_callback(lambda _f: None)

    # --- WRITE presets (Save / Load) ---
    def _on_write_save_preset(self, uuid: str):
        """Save current WRITE editor bytes into prefs[{uuid}]['write_presets'] with a chosen name."""
        data = self._get_write_bytes_for(uuid)
        if data is None:
            return
        # Ask a name
        try:
            dialog = ctk.CTkInputDialog(text="Preset name:", title="Save As..")
            name = dialog.get_input()
        except Exception:
            import tkinter.simpledialog as sd
            name = sd.askstring("Save As..", "Preset name:")
        if not name:
            return
        name = name.strip()
        if not name:
            return

        prefs = self._uuid_prefs(uuid)
        presets = prefs.setdefault("write_presets", [])
        # replace if same name exists
        replaced = False
        for p in presets:
            if p.get("name") == name:
                p["bytes"] = list(data)
                replaced = True
                break
        if not replaced:
            presets.append({"name": name, "bytes": list(data)})
        self._save_saved_prefs()
        shown = " ".join(f"{b:02X}" for b in data)
        self._append_to_char_log(uuid, f"[WRITE {uuid}] Preset '{name}' saved: {shown}")

    def _on_write_load_preset(self, uuid: str):
        """Open a dialog to choose a saved preset and apply it into the WRITE editor.
           NEW: includes a Search box to filter presets by name."""
        prefs = self._uuid_prefs(uuid)
        presets = prefs.get("write_presets", [])
        if not presets:
            self._append_to_char_log(uuid, f"[WRITE {uuid}] No saved presets found.")
            return

        win = ctk.CTkToplevel(self); win.title("Load Saved")
        try: win.grab_set()
        except Exception: pass
        set_fg(win, THEME["panel"]); set_border(win, THEME["card_border"], 1)
        win.grid_columnconfigure(1, weight=1)

        # --- NEW: Search row ---
        ctk.CTkLabel(win, text="Search:").grid(row=0, column=0, padx=10, pady=(12,6), sticky="w")
        search_var = tk.StringVar(value="")
        search_entry = ctk.CTkEntry(win, textvariable=search_var, width=260)
        search_entry.grid(row=0, column=1, padx=10, pady=(12,6), sticky="ew")

        # Select row
        ctk.CTkLabel(win, text="Select preset:").grid(row=1, column=0, padx=10, pady=(8,8), sticky="w")
        names_all = [p.get("name","(unnamed)") for p in presets]
        sel_var = tk.StringVar(value=names_all[0])
        picker = ctk.CTkOptionMenu(win, variable=sel_var, values=names_all, width=260)
        picker.grid(row=1, column=1, padx=10, pady=(8,8), sticky="ew")

        btns = ctk.CTkFrame(win, fg_color="transparent"); btns.grid(row=2, column=0, columnspan=2, pady=(2,12), sticky="nsew")        apply_btn = ctk.CTkButton(btns, text="Apply", width=110)
        cancel_btn = ctk.CTkButton(btns, text="Cancel", width=110, command=win.destroy)
        apply_btn.pack(side="left", padx=8); cancel_btn.pack(side="left", padx=8)

        # filtering logic
        def current_filtered_names():
            q = (search_var.get() or "").strip().lower()
            if not q:
                return list(names_all)
            return [n for n in names_all if q in (n or "").lower()]

        def refresh_picker(*_):
            filtered = current_filtered_names()
            # Update the option list
            try:
                picker.configure(values=filtered if filtered else ["(no matches)"])
            except Exception:
                pass
            # Choose first available or clear selection
            if filtered:
                if sel_var.get() not in filtered:
                    sel_var.set(filtered[0])
                apply_btn.configure(state="normal")
            else:
                sel_var.set("(no matches)")
                apply_btn.configure(state="disabled")

        search_entry.bind("<KeyRelease>", refresh_picker)

        def on_apply():
            nm = sel_var.get()
            if not nm or nm == "(no matches)":
                return
            chosen = None
            for p in presets:
                if p.get("name") == nm:
                    chosen = p; break
            if not chosen:
                win.destroy(); return
            data_list = chosen.get("bytes", [])
            try:
                data = bytes(int(x) & 0xFF for x in data_list)
            except Exception:
                win.destroy(); return
            self._fill_write_from_bytes(uuid, data)
            shown = " ".join(f"{b:02X}" for b in data)
            self._append_to_char_log(uuid, f"[WRITE {uuid}] Loaded preset '{nm}': {shown}")
            win.destroy()

        apply_btn.configure(command=on_apply)

        # Focus on search for quick filtering
        try: search_entry.focus_set()
        except Exception: pass

    # ---------- NEW: Paste helper ----------
    @staticmethod
    def _parse_pasted_bytes(text: str) -> List[int]:
        """
        Accepts strings like:
          '04 00 00 64', '0x04,0x00,0x64', '04000064', '04-00-00-64'
        Returns a list of ints (0..255).
        """
        if not text:
            return []
        t = text.strip()
        if not t:
            return []

        # Remove 0x prefixes, normalize separators to spaces
        t = re.sub(r'0x', '', t, flags=re.IGNORECASE)
        t = re.sub(r'[^0-9a-fA-F]', ' ', t)  # keep only hex digits, make others spaces
        parts = [p for p in t.split() if p]

        out: List[int] = []
        for p in parts:
            if len(p) <= 2:
                # single byte
                try:
                    out.append(int(p, 16) & 0xFF)
                except Exception:
                    pass
            else:
                # chunk with no spaces (e.g., "04000064")
                # slice into pairs
                if len(p) % 2 == 1:
                    p = "0" + p  # pad if odd length
                for i in range(0, len(p), 2):
                    try:
                        out.append(int(p[i:i+2], 16) & 0xFF)
                    except Exception:
                        pass
        return out

    def _on_write_paste_fill(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page:
            return
        paste_var: tk.StringVar = page["write"].get("paste_var")
        if not paste_var:
            return
        text = paste_var.get()
        bytes_list = self._parse_pasted_bytes(text)
        if not bytes_list:
            self._append_to_char_log(uuid, f"[WRITE {uuid}] Paste is empty or invalid.")
            return
        data = bytes(bytes_list)
        self._fill_write_from_bytes(uuid, data)
        shown = " ".join(f"{b:02X}" for b in data)
        self._append_to_char_log(uuid, f"[WRITE {uuid}] Pasted bytes applied ({len(data)}): {shown}")
    def _on_fill_and_write(self, uuid: str):
        # 1) Do the same fill you already have
        self._on_write_paste_fill(uuid)

        # 2) Reuse the existing Write path (same as clicking the Write button)
        self._write_from(uuid)

    def _on_fill_and_write(self, uuid: str):
        # 1) Fill the byte editor from the paste box
        self._on_write_paste_fill(uuid)
        # 2) Write using the existing path
        self._write_from(uuid)


    # decode
    @staticmethod
    def _u16_be(hi: int, lo: int) -> int: return ((hi & 0xFF) << 8) | (lo & 0xFF)
    def _decode_status(self, payload: bytes) -> Dict[str, Union[List[int], int]]:
        b = payload
        if len(b) < 34: return {}
        current_status = b[0]; error_code = b[1]
        def pairs(start, count):
            out = []
            for i in range(count):
                hi = b[start + 2*i]; lo = b[start + 2*i + 1]; out.append(self._u16_be(hi, lo))
            return out
        temps = pairs(2,4); press = pairs(10,6); levels = pairs(22,2); flows = pairs(26,4)
        return {"current_status": current_status, "error_code": error_code, "temperature": temps, "pressure": press, "level": levels, "flowrate": flows}

    def _clear_decoded_for(self, uuid: str, which: Optional[str]):
        page = self.char_pages.get(uuid)
        if not page: return
        def clear(rows_key, frame_key):
            frame = page[frame_key]
            for c in frame.winfo_children(): c.destroy()
            page[rows_key].clear()
        if which in (None,"read"): clear("decoded_read_rows","decoded_read_frame")
        if which in (None,"notify"): clear("decoded_notify_rows","decoded_notify_frame")

    def _update_decoded_for(self, uuid: str, which: str, d: Dict[str, Union[List[int], int]]):
        if which not in ("read","notify") or not d: return
        page = self.char_pages.get(uuid)
        if not page: return
        rows = page["decoded_read_rows"] if which == "read" else page["decoded_notify_rows"]
        frame = page["decoded_read_frame"] if which == "read" else page["decoded_notify_frame"]
        def ensure_row(name: str):
            if name in rows: return rows[name]
            row = ctk.CTkFrame(frame, fg_color="transparent"); row.pack(fill="x", padx=6, pady=2)
            k = ctk.CTkLabel(row, text=name, width=140, anchor="w"); k.pack(side="left")
            v = ctk.CTkLabel(row, text="", anchor="w", wraplength=700); v.pack(side="left", fill="x", expand=True)
            rows[name] = (k, v); return rows[name]
        def set_val(name: str, val: Union[int, List[int]]):
            _, v = ensure_row(name); v.configure(text=", ".join(str(x) for x in val) if isinstance(val, list) else str(val))
        set_val("current_status", d["current_status"]); set_val("error_code", d["error_code"])
        set_val("temperature[4]", d["temperature"]); set_val("pressure[6]", d["pressure"])
        set_val("level[2]", d["level"]); set_val("flowrate[4]", d["flowrate"])

    # computed values (notify)
    class _ExprSafeEval(ast.NodeVisitor):
        allowed_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
        allowed_unary = (ast.UAdd, ast.USub)
        def __init__(self, names: Dict[str, int]): self.names = names
        def visit(self, node):
            if isinstance(node, ast.Expression): return self.visit(node.body)
            if isinstance(node, ast.Num): return node.n
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)): return node.value
                raise ValueError("Only numeric constants allowed")
            if isinstance(node, ast.Name):
                if node.id in self.names: return self.names[node.id]
                raise ValueError(f"Unknown name '{node.id}'")
            if isinstance(node, ast.BinOp) and isinstance(node.op, self.allowed_ops):
                left = self.visit(node.left); right = self.visit(node.right)
                return self._apply_binop(node.op, left, right)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, self.allowed_unary):
                val = self.visit(node.operand); return +val if isinstance(node.op, ast.UAdd) else -val
            raise ValueError("Unsupported expression")
        @staticmethod
        def _apply_binop(op, a, b):
            if isinstance(op, ast.Add): return a + b
            if isinstance(op, ast.Sub): return a - b
            if isinstance(op, ast.Mult): return a * b
            if isinstance(op, ast.Div): return a / b
            if isinstance(op, ast.FloorDiv): return a // b
            if isinstance(op, ast.Mod): return a % b
            if isinstance(op, ast.Pow): return a ** b
            raise ValueError("Bad op")
    def _eval_formula(self, expr: str, names: Dict[str, int]) -> Union[int, float]:
        tree = ast.parse(expr, mode="eval"); return self._ExprSafeEval(names).visit(tree)
    def _prompt_add_notify_calc(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        win = ctk.CTkToplevel(self); win.title("Create Value")
        try: win.grab_set()
        except Exception: pass
        set_fg(win, THEME["panel"]); set_border(win, THEME["card_border"], 1)
        for r in range(3): win.grid_rowconfigure(r, weight=0)
        win.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(win, text="Name:").grid(row=0, column=0, padx=10, pady=(10,6), sticky="w")
        name_var = ctk.StringVar(); name_entry = ctk.CTkEntry(win, textvariable=name_var, width=240); name_entry.grid(row=0, column=1, padx=10, pady=(10,6), sticky="ew")
        ctk.CTkLabel(win, text="Calculation:").grid(row=1, column=0, padx=10, pady=6, sticky="w")
        hint = "Use b1, b2, ... for byte1, byte2 etc. Example: b1*255 + b2*1"
        calc_var = ctk.StringVar(value="")
        calc_entry = ctk.CTkEntry(win, textvariable=calc_var, width=360)
        calc_entry.grid(row=1, column=1, padx=10, pady=6, sticky="ew")
        ctk.CTkLabel(win, text=hint, text_color=THEME["muted"]).grid(row=2, column=0, columnspan=2, padx=10, pady=(0,10), sticky="w")
        btns = ctk.CTkFrame(win, fg_color="transparent"); btns.grid(row=3, column=0, columnspan=2, pady=(0,12), sticky="nsew")        def on_ok():
            nm = (name_var.get() or "").strip(); ex = (calc_var.get() or "").strip()
            if not nm or not ex: win.destroy(); return
            self._add_notify_calc(uuid, nm, ex, save=True); win.destroy()
        ctk.CTkButton(btns, text="Create", command=on_ok).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Cancel", command=win.destroy).pack(side="left", padx=8)
        name_entry.focus_set()
    def _add_notify_calc(self, uuid: str, name: str, expr: str, save: bool = True):
        page = self.char_pages.get(uuid)
        if not page: return
        calc_frame: ctk.CTkScrollableFrame = page["notify"]["calc_frame"]
        row = ctk.CTkFrame(calc_frame, fg_color="transparent"); row.pack(fill="x", padx=4, pady=3)
        name_lbl = ctk.CTkLabel(row, text=name, width=140, anchor="w"); name_lbl.pack(side="left")
        val_lbl = ctk.CTkLabel(row, text="—", anchor="w"); val_lbl.pack(side="left", fill="x", expand=True)
        def remove_row(nm=name):
            try: row.destroy()
            except Exception: pass
            page["notify"]["calc_defs"] = [c for c in page["notify"]["calc_defs"] if c.get("label") is not val_lbl]
            self._persist_notify_calcs(uuid)
            # also remove from any open graph
            self._graph_remove_series(uuid, nm)
        close_btn = ctk.CTkButton(row, text="×", width=26, fg_color=THEME["tab_close_bg"], command=remove_row); close_btn.pack(side="right", padx=(6,2))
        page["notify"]["calc_defs"].append({"name": name, "expr": expr, "label": val_lbl, "row": row})
        if save: self._persist_notify_calcs(uuid)
        self._recompute_notify_calcs(uuid); self._scroll_calc_to_bottom(uuid)
    def _persist_notify_calcs(self, uuid: str) -> None:
        page = self.char_pages.get(uuid)
        if not page: return
        defs = page["notify"]["calc_defs"]; prefs = self._uuid_prefs(uuid)
        prefs["notify_calcs"] = [{"name": d["name"], "expr": d["expr"]} for d in defs]; self._save_saved_prefs()
    def _restore_notify_calcs(self, uuid: str) -> None:
        prefs = self._uuid_prefs(uuid); items = prefs.get("notify_calcs", [])
        for it in items:
            name = it.get("name"); expr = it.get("expr")
            if name and expr: self._add_notify_calc(uuid, name, expr, save=False)
        self._persist_notify_calcs(uuid)
        try: self.attributes("-zoomed", True)
        except Exception: pass
    def _recompute_notify_calcs(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        calcs = page["notify"]["calc_defs"]
        if not calcs: return
        data: bytes = page.get("last_notify_bytes", b"") or b""
        names = {f"b{i+1}": (data[i] if i < len(data) else 0) for i in range(max(1, len(data)))}
        for c in calcs:
            try:
                val = self._eval_formula(c["expr"], names)
                if isinstance(val, float) and val.is_integer(): val = int(val)
                c["label"].configure(text=str(val))
                # push to graph if tracked
                if isinstance(val, (int, float)):
                    self._graph_push(uuid, c["name"], float(val))
            except Exception:
                c["label"].configure(text="Err")
    def _scroll_calc_to_bottom(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        canv = page["notify"].get("calc_canvas")
        if canv:
            try: canv.update_idletasks(); canv.yview_moveto(1.0)
            except Exception: pass
    def _toggle_notify_for(self, uuid: str):
        if self.notify_active_uuid == uuid:
            fut = self.bridge.run_coro(self._stop_notify_async(uuid)); fut.add_done_callback(lambda _f: self.after(0, self._notify_stopped_ui_for, uuid))
        else:
            fut = self.bridge.run_coro(self._start_notify_async(uuid)); fut.add_done_callback(lambda _f: self.after(0, self._notify_started_ui_for, uuid))
    def _notify_started_ui_for(self, uuid: str):
        page = self.char_pages.get(uuid)
        if page: page["notify"]["btn"].configure(text="Unsubscribe")
        try: self.notify_btn.configure(text="Unsubscribe")
        except Exception: pass
    def _notify_stopped_ui_for(self, uuid: str):
        page = self.char_pages.get(uuid)
        if page: page["notify"]["btn"].configure(text="Subscribe")
        try: self.notify_btn.configure(text="Subscribe")
        except Exception: pass

    # ---------------------- GRAPH: Live chart from computed values ---------------------- #
    def _open_graph_window(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        g = page["graph"]

        # Create or focus window
        if g["win"] and g["win"].winfo_exists():
            try: g["win"].deiconify(); g["win"].lift()
            except Exception: pass
        else:
            g["win"] = ctk.CTkToplevel(self)
            g["win"].title("Live Graph (Computed Values)")
            set_fg(g["win"], THEME["panel"]); set_border(g["win"], THEME["card_border"], 1)
            try: g["win"].geometry("820x520")
            except Exception: pass

            # Top control row: picker + Add button
            ctrl = ctk.CTkFrame(g["win"], fg_color="transparent")
            ctrl.pack(fill="x", padx=10, pady=(10,6))
            ctk.CTkLabel(ctrl, text="Select value:").pack(side="left")
            names = [c["name"] for c in page["notify"]["calc_defs"]] or ["(no values yet)"]
            g["picker_var"] = tk.StringVar(value=names[0])
            g["picker_menu"] = ctk.CTkOptionMenu(ctrl, variable=g["picker_var"], values=names, width=240)
            g["picker_menu"].pack(side="left", padx=(8,8))
            def on_add():
                nm = g["picker_var"].get()
                if nm and nm != "(no values yet)":
                    self._graph_add_series(uuid, nm)
            ctk.CTkButton(ctrl, text="Add", width=80, command=on_add).pack(side="left", padx=(4,4))
            ctk.CTkButton(ctrl, text="Close", width=80, command=lambda u=uuid: self._close_graph_for(u)).pack(side="right")


            # "Live" header row with blinking red dot (relocated like your screenshot)
            hdr = ctk.CTkFrame(g["win"], fg_color="transparent")
            hdr.pack(fill="x", padx=12, pady=(0, 2))
            try:
                live_font = ctk.CTkFont(size=20, weight="bold")
            except Exception:
                live_font = None
            g["live_label"] = ctk.CTkLabel(hdr, text="Live", font=live_font)
            g["live_label"].pack(side="left")

            g["live_dot"] = ctk.CTkButton(hdr, width=16, height=16, text="", corner_radius=8,
                                          fg_color="#FF3B30", hover=False, state="disabled")
            g["live_dot"].pack(side="left", padx=(8, 0))

            # blinking toggle
            def _blink():
                if not g["win"] or not g["win"].winfo_exists():
                    return
                g["blink_on"] = not g.get("blink_on", True)
                try:
                    g["live_dot"].configure(fg_color=("#FF3B30" if g["blink_on"] else "#3A3A3A"))
                except Exception:
                    pass
                try:
                    g["win"].after(500, _blink)
                except Exception:
                    pass
            try:
                g["win"].after(500, _blink)
            except Exception:
                pass
            # Figure
            g["fig"] = Figure(figsize=(7.8, 4.2), dpi=100)
            g["ax"] = g["fig"].add_subplot(111)
            g["ax"].set_title("Live (last 100 samples)")
            g["ax"].set_xlabel("Time (s)")
            g["ax"].set_ylabel("Value")
            g["canvas"] = FigureCanvasTkAgg(g["fig"], master=g["win"])
            g["canvas"].get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0,10))
            g["series"] = {}
            g["start_time"] = time.time()
            g["pending"] = False

            # If window is closed, clear reference
            def _on_close():
                self._close_graph_for(uuid)
            try:
                g["win"].protocol("WM_DELETE_WINDOW", _on_close)
            except Exception:
                pass

        # refresh picker list (in case new computed values were added)
        try:
            names = [c["name"] for c in page["notify"]["calc_defs"]] or ["(no values yet)"]
            if g["picker_menu"]: g["picker_menu"].configure(values=names)
            if g["picker_var"] and names:
                if g["picker_var"].get() not in names:
                    g["picker_var"].set(names[0])
        except Exception:
            pass

    def _close_graph_for(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page: return
        g = page.get("graph", {})
        try:
            if g.get("win") and g["win"].winfo_exists():
                g["win"].destroy()
        except Exception:
            pass
        # reset state (keep nothing)
        page["graph"] = {
            "win": None, "fig": None, "ax": None, "canvas": None,
            "picker_var": None, "picker_menu": None,
            "series": {},
            "start_time": time.time(),
            "pending": False,
            "live_label": None,
            "live_dot": None,
            "blink_on": True,
        }

    def _graph_add_series(self, uuid: str, name: str):
        page = self.char_pages.get(uuid)
        if not page: return
        g = page["graph"]
        if not g["win"] or not g["ax"]:
            return
        if name in g["series"]:
            return
        # create a line; matplotlib assigns a default color cycle
        line, = g["ax"].plot([], [], label=name)
        g["series"][name] = {"times": [], "values": [], "line": line}
        try:
            g["ax"].legend(loc="upper right")
        except Exception:
            pass
        self._graph_request_draw(uuid)

    def _graph_remove_series(self, uuid: str, name: str):
        page = self.char_pages.get(uuid)
        if not page: return
        g = page["graph"]
        s = g["series"].pop(name, None)
        if s and s.get("line"):
            try: s["line"].remove()
            except Exception: pass
        try:
            g["ax"].legend(loc="upper right")
        except Exception:
            pass
        self._graph_request_draw(uuid)

    def _graph_push(self, uuid: str, name: str, value: float):
        """Append a value for a named series (if it's selected). Keep only the latest 100 samples."""
        page = self.char_pages.get(uuid)
        if not page: return
        g = page["graph"]
        if not g["win"] or name not in g["series"]:
            return
        s = g["series"][name]
        t = time.time() - g["start_time"]
        s["times"].append(t)
        s["values"].append(float(value))
        if len(s["times"]) > 100:
            s["times"] = s["times"][-100:]
            s["values"] = s["values"][-100:]
        self._graph_request_draw(uuid)

    def _graph_request_draw(self, uuid: str):
        """Throttle redraws to ~10fps using Tk 'after'."""
        page = self.char_pages.get(uuid)
        if not page: return
        g = page["graph"]
        if not g["win"] or not g["ax"] or not g["canvas"]:
            return
        if g["pending"]:
            return
        g["pending"] = True
        def _do():
            g["pending"] = False
            ax = g["ax"]
            changed = False
            min_t, max_t = None, None
            for name, s in g["series"].items():
                if not s["times"]:
                    continue
                s["line"].set_data(s["times"], s["values"])
                if min_t is None or s["times"][0] < min_t: min_t = s["times"][0]
                if max_t is None or s["times"][-1] > max_t: max_t = s["times"][-1]
                changed = True
            if changed:
                try:
                    ax.relim(); ax.autoscale_view()
                    if min_t is not None and max_t is not None and max_t > min_t:
                        ax.set_xlim(min_t, max_t)
                    g["canvas"].draw_idle()
                except Exception:
                    pass
        try:
            self.after(100, _do)
        except Exception:
            pass
    # -------------------- END GRAPH SECTION -------------------- #

    # responsive + inner splitters
    def _on_root_resize(self, event=None):
        if self._resize_job:
            try: self.after_cancel(self._resize_job)
            except Exception: pass
        self._resize_job = self.after(80, self._apply_responsive_all)
    def _apply_responsive_all(self):
        self._apply_dev_width()
        width = max(1, self.winfo_width())
        for uuid in list(self.char_pages.keys()): self._apply_responsive_layout(uuid, width)

    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # LAYOUT CHANGE: READ is below; WRITE and NOTIFY are on the first row
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    def _apply_responsive_layout(self, uuid: str, width: int):
        page = self.char_pages.get(uuid)
        if not page: return
        boxes = page["boxes_container"]
        read_box   = page["read"]["box"]
        notify_box = page["notify"]["box"]
        write_box  = page["write"]["box"]
        split      = page["split"]
        sash1, sash2 = split["sash1"], split["sash2"]

        # Clear current grid placements
        for w in (read_box, notify_box, write_box, sash1, sash2):
            try: w.grid_forget()
            except Exception: pass

        # Reset column configs
        for c in range(5):
            try: boxes.grid_columnconfigure(c, weight=0, minsize=0)
            except Exception: pass
        boxes.grid_rowconfigure(0, weight=1)
        boxes.grid_rowconfigure(1, weight=1)

        # weights for top row (write vs notify)
        w_write  = max(1, int(split["w_w"] * 1000))
        w_notify = max(1, int(split["w_n"] * 1000))

        if width >= 1400:
            # Top row: WRITE | sash | NOTIFY
            boxes.grid_columnconfigure(0, weight=w_write,  minsize=split["min_w"])
            boxes.grid_columnconfigure(1, weight=0,       minsize=self._inner_sash_size)  # sash
            boxes.grid_columnconfigure(2, weight=w_notify, minsize=split["min_n"])

            write_box.grid( row=0, column=0, sticky="nsew", padx=(0,8),  pady=0)
            sash1.grid(     row=0, column=1, sticky="ns",   padx=(2,2),  pady=0)
            notify_box.grid(row=0, column=2, sticky="nsew", padx=(8,0),  pady=0)

            # Bottom row: READ spans full width
            read_box.grid(  row=1, column=0, columnspan=3, sticky="nsew", padx=0, pady=(8,0))

        elif width >= 1000:
            boxes.grid_columnconfigure(0, weight=w_write,  minsize=split["min_w"])
            boxes.grid_columnconfigure(1, weight=0,       minsize=self._inner_sash_size)
            boxes.grid_columnconfigure(2, weight=w_notify, minsize=split["min_n"])

            write_box.grid( row=0, column=0, sticky="nsew", padx=(0,8),  pady=(0,8))
            sash1.grid(     row=0, column=1, sticky="ns",   padx=(2,2),  pady=(0,8))
            notify_box.grid(row=0, column=2, sticky="nsew", padx=(8,0),  pady=(0,8))

            read_box.grid(  row=1, column=0, columnspan=3, sticky="nsew", padx=0,   pady=(0,0))
        else:
            # Stack vertically on narrow screens
            write_box.grid( row=0, column=0, sticky="nsew", padx=0, pady=(0,8))
            notify_box.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0,8))
            read_box.grid(  row=2, column=0, sticky="nsew", padx=0, pady=(0,0))
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # ---------- Inner sash handlers (updated for WRITE | NOTIFY top row) ----------
    def _inner_sash_press(self, uuid: str, which: int, event):
        page = self.char_pages.get(uuid)
        if not page:
            return
        split = page["split"]
        split["drag"] = which
        split["start_x"] = event.x_root

        write_box = page["write"]["box"]
        notify_box = page["notify"]["box"]

        try:
            write_px = max(1, write_box.winfo_width())
            notify_px = max(1, notify_box.winfo_width())
        except Exception:
            write_px, notify_px = 1, 1

        total_px = write_px + notify_px
        split["total_px"] = total_px
        split["w_px"] = write_px
        split["n_px"] = notify_px

    def _inner_sash_drag(self, uuid: str, which: int, event):
        page = self.char_pages.get(uuid)
        if not page:
            return
        split = page["split"]
        if split.get("drag", 0) != which:
            return

        dx = event.x_root - split.get("start_x", event.x_root)
        min_w = split.get("min_w", 320)
        min_n = split.get("min_n", 320)

        write_px = split.get("w_px", 1) + dx
        notify_px = split.get("n_px", 1) - dx

        # Clamp
        if write_px < min_w:
            notify_px -= (min_w - write_px)
            write_px = min_w
        if notify_px < min_n:
            write_px -= (min_n - notify_px)
            notify_px = min_n

        total = max(1, write_px + notify_px)
        split["w_w"] = float(write_px) / float(total)
        split["w_n"] = float(notify_px) / float(total)

        # Re-apply layout immediately
        try:
            self._apply_responsive_layout(uuid, max(1, self.winfo_width()))
        except Exception:
            pass

    def _inner_sash_release(self, uuid: str, which: int, event):
        page = self.char_pages.get(uuid)
        if not page:
            return
        split = page["split"]
        split["drag"] = 0

    def _inner_reset(self, uuid: str):
        page = self.char_pages.get(uuid)
        if not page:
            return
        split = page["split"]
        # Equal weights for WRITE and NOTIFY; READ is on its own row.
        split["w_w"] = 1.0
        split["w_n"] = 1.0
        try:
            self._apply_responsive_layout(uuid, max(1, self.winfo_width()))
        except Exception:
            pass

    # ---------------------- App shutdown ---------------------- #
    def on_close(self):
        try:
            if self.client and getattr(self.client, "is_connected", False):
                try:
                    self.bridge.run_coro(self.client.disconnect()).result(timeout=1.0)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.bridge.stop()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    app = BLEBrowserApp()
    app.mainloop()

    def _layout_medium(self):
        """
        Place WRITE and NOTIFY side-by-side (two columns), and READ as a full-width row below.
        This keeps more info above the fold on mid-size screens.
        """
        try:
            host = self.page_host if hasattr(self, "page_host") else self  # be flexible
            # Generic layout:
            # row 0: WRITE | NOTIFY
            # row 1: READ (span 2 cols)
            for r in range(2):
                try:
                    host.grid_rowconfigure(r, weight=1)
                except Exception:
                    pass
            for c in range(2):
                try:
                    host.grid_columnconfigure(c, weight=1)
                except Exception:
                    pass

            # WRITE panel in (0,0)
            try:
                self.write_panel.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            except Exception:
                pass

            # NOTIFY panel in (0,1)
            try:
                self.notify_panel.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
            except Exception:
                pass

            # READ panel across row 1 both columns
            try:
                self.read_panel.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=6)
            except Exception:
                pass

        except Exception:
            # If any of the above attribute names differ in your app, you can adjust them later.
            pass
    