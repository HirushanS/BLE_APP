import sys
import asyncio
import os
import json
import shutil
from typing import Optional, Dict

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QTabWidget, QSplitter,
    QToolButton, QMessageBox, QScrollArea, QGridLayout, QLineEdit, QTextEdit, QCheckBox,
    QFrame, QInputDialog, QComboBox, QTabBar, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QLinearGradient, QBrush, QPalette, QColor, QPixmap

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import re

import qasync

from bleak import BleakScanner, BleakClient

# =========================
#   Path Helpers for EXE
# =========================
def get_resource_path(relative_path: str) -> str:
    """Gets path for static resources (bundled assets in EXE)"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_data_path(filename: str) -> str:
    """Return a writable path for application preferences and presets.

    Existing JSON files from older versions are copied from the working
    directory the first time they are requested.
    """
    app_dir = os.path.join(
        os.getenv("APPDATA", os.path.expanduser("~")),
        "BLEBrowser",
    )
    os.makedirs(app_dir, exist_ok=True)

    target_path = os.path.join(app_dir, filename)
    legacy_path = os.path.abspath(filename)
    if not os.path.exists(target_path) and os.path.isfile(legacy_path):
        try:
            shutil.copy2(legacy_path, target_path)
        except OSError:
            pass
    return target_path

TARGET_STATUS_UUID = "f0002002-0451-4000-b000-000000000000"

# =========================
#   Safe Eval Helper
# =========================
import ast
class ExprSafeEval(ast.NodeVisitor):
    allowed_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    allowed_unary = (ast.UAdd, ast.USub)
    def __init__(self, names: Dict[str, int]): self.names = names
    def visit(self, node):
        if isinstance(node, ast.Expression): return self.visit(node.body)
        if isinstance(node, (ast.Num, ast.Constant)): 
            if hasattr(node, 'n'): return node.n # py < 3.8
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

def eval_formula(expr: str, names: Dict[str, int]):
    try:
        tree = ast.parse(expr, mode="eval")
        return ExprSafeEval(names).visit(tree)
    except Exception as e:
        raise e

def safe_color(color_str: str):
    """Converts 'rgba(r,g,b,a)' or hex to Matplotlib-compatible format"""
    if color_str.startswith("rgba"):
        # Parse rgba(15, 23, 42, 0.7)
        vals = re.findall(r"([0-9\.]+)", color_str)
        if len(vals) == 4:
            return (float(vals[0])/255, float(vals[1])/255, float(vals[2])/255, float(vals[3]))
    return color_str # Return as-is if hex or already safe

# =========================
#   SKYLIGHT DESIGN SYSTEM
# =========================
THEME = {
    "background": "#08111f",
    "background_alt": "#0b1628",
    "surface": "#111d30",
    "surface_alt": "#16243a",
    "surface_hover": "#1c2d47",
    "border": "#2a3a52",
    "border_soft": "#1f2d42",
    "text_primary": "#f8fafc",
    "text_secondary": "#9aa9bd",
    "text_muted": "#6f8199",
    "accent": "#3b82f6",
    "accent_hover": "#60a5fa",
    "accent_bright": "#60a5fa",
    "accent_soft": "rgba(59, 130, 246, 0.14)",
    "accent_glow": "rgba(59, 130, 246, 0.14)",
    "success": "#22c55e",
    "success_hover": "#4ade80",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "danger_hover": "#f87171",
    "input_bg": "#0b1628",
    "radius": "14px",
}


def get_stylesheet() -> str:
    """Return the application-wide premium dark dashboard stylesheet."""
    return f"""
        QMainWindow {{
            background: transparent;
        }}

        QWidget {{
            color: {THEME['text_primary']};
            font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
            font-size: 10pt;
        }}

        QToolTip {{
            color: {THEME['text_primary']};
            background-color: #13233a;
            border: 1px solid #31517c;
            border-radius: 7px;
            padding: 7px 9px;
        }}

        #sidebarFrame {{
            background-color: #0d192b;
            border: 1px solid #223652;
            border-radius: 16px;
        }}

        #mainPanelFrame {{
            background-color: rgba(5, 13, 24, 0.90);
            border: 1px solid #21344e;
            border-radius: 16px;
        }}

        #contentCard, #controlCard, #graphCard, #heroCard,
        #statusCard, #selectorCard, #welcomeCard, #characteristicHeader {{
            background-color: #101d30;
            border: 1px solid #223650;
            border-radius: 13px;
        }}

        #controlCard {{
            background-color: #0f1c2f;
        }}

        #graphCard {{
            background-color: #0d192b;
        }}

        #characteristicHeader {{
            background-color: #0c192b;
            border-color: #294566;
        }}

        #statusCard[connected="true"] {{
            border-color: rgba(34, 197, 94, 0.55);
            background-color: rgba(20, 83, 45, 0.18);
        }}

        #topBar {{
            background: transparent;
            border: none;
            border-bottom: 1px solid #263a55;
        }}

        QLabel#pageTitle {{
            color: #f8fafc;
            font-size: 19pt;
            font-weight: 750;
        }}

        QLabel#pageSubtitle, QLabel#mutedLabel {{
            color: #95a7bf;
        }}

        QLabel#sectionLabel {{
            color: #9db2cf;
            font-size: 8.2pt;
            font-weight: 750;
        }}

        QLabel#cardTitle {{
            color: #f8fafc;
            font-size: 10pt;
            font-weight: 750;
        }}

        QLabel#brandName {{
            color: #f8fafc;
            font-size: 12pt;
            font-weight: 800;
            letter-spacing: 0.5px;
        }}

        QLabel#brandMark {{
            background-color: #1473e6;
            color: white;
            border-radius: 8px;
            font-size: 14pt;
            font-weight: 900;
        }}

        QLabel#monoLabel {{
            color: #e5eefb;
            font-family: 'Cascadia Mono', 'Consolas', monospace;
        }}

        QLabel#statusBadge {{
            color: #b7c9e1;
            background-color: #0d1a2d;
            border: 1px solid #263c59;
            border-radius: 10px;
            padding: 6px 11px;
            font-size: 8.5pt;
            font-weight: 650;
        }}

        QLabel#successText {{
            color: #4ade80;
            font-weight: 700;
        }}

        QLabel#bluetoothGlyph {{
            color: #2788ff;
            font-size: 31pt;
            font-weight: 500;
        }}

        QPushButton {{
            min-height: 20px;
            background-color: #15243a;
            color: #eaf2ff;
            border: 1px solid #2b405e;
            border-radius: 8px;
            padding: 8px 13px;
            font-weight: 650;
        }}

        QPushButton:hover {{
            background-color: #1b304d;
            border-color: #378cf5;
        }}

        QPushButton:pressed {{
            background-color: #0b1627;
        }}

        QPushButton:disabled {{
            color: #53657d;
            background-color: #0d1726;
            border-color: #1a293d;
        }}

        QPushButton#primaryButton {{
            background-color: #1168e8;
            color: white;
            border-color: #247df5;
        }}
        QPushButton#primaryButton:hover {{
            background-color: #247df5;
            border-color: #4a9aff;
        }}

        QPushButton#successButton {{
            background-color: #159447;
            color: white;
            border-color: #22b85d;
        }}
        QPushButton#successButton:hover {{
            background-color: #1eae56;
            border-color: #4ade80;
        }}

        QPushButton#dangerButton {{
            background-color: rgba(185, 35, 52, 0.22);
            color: #ffb1bb;
            border-color: #a93a49;
        }}
        QPushButton#dangerButton:hover {{
            background-color: #c93649;
            color: white;
            border-color: #ef6677;
        }}

        QPushButton#ghostButton, QPushButton#smallButton,
        QPushButton#iconButton, QPushButton#toggleButton {{
            background-color: transparent;
            color: #9db1ca;
        }}
        QPushButton#ghostButton:hover, QPushButton#smallButton:hover,
        QPushButton#iconButton:hover, QPushButton#toggleButton:hover {{
            color: #67a9ff;
            background-color: rgba(47, 132, 255, 0.12);
            border-color: #2f84ff;
        }}
        QPushButton#smallButton {{
            min-height: 16px;
            padding: 4px 9px;
            font-size: 8pt;
        }}
        QPushButton#iconButton {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
            font-size: 12pt;
        }}
        QPushButton#toggleButton {{
            padding: 5px 8px;
            font-size: 8pt;
        }}

        QLineEdit, QComboBox, QTextEdit {{
            background-color: #081426;
            color: #f1f6fd;
            border: 1px solid #2a405e;
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: #247df5;
        }}

        QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
            border-color: #438ff2;
            background-color: #071120;
        }}

        QLineEdit:disabled, QComboBox:disabled, QTextEdit:disabled {{
            color: #53657d;
            background-color: #0d1726;
        }}

        QComboBox {{
            padding-right: 28px;
        }}
        QComboBox::drop-down {{
            width: 28px;
            border: none;
        }}
        QComboBox QAbstractItemView {{
            color: #f1f6fd;
            background-color: #122138;
            border: 1px solid #315071;
            selection-background-color: #1e67c8;
            outline: none;
        }}

        QTextEdit {{
            font-family: 'Cascadia Mono', 'Consolas', monospace;
            font-size: 9pt;
        }}

        QTextEdit#consoleText {{
            background-color: #071322;
            border-color: #203653;
        }}

        QCheckBox {{
            color: #9fb1c8;
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 1px solid #36506f;
            border-radius: 4px;
            background-color: #091426;
        }}
        QCheckBox::indicator:checked {{
            background-color: #2f84ff;
            border-color: #5aa2ff;
        }}

        QTreeWidget {{
            background-color: #0a1728;
            border: 1px solid #203550;
            border-radius: 10px;
            outline: none;
            padding: 5px;
        }}
        QTreeWidget::item {{
            min-height: 31px;
            padding: 3px 7px;
            border-radius: 7px;
        }}
        QTreeWidget::item:hover {{
            background-color: #142640;
        }}
        QTreeWidget::item:selected {{
            background-color: #173d73;
            color: #dcecff;
            border: 1px solid #2e78d5;
        }}

        QTabWidget::pane {{
            border: none;
            background: transparent;
            top: -1px;
        }}
        
        QTabBar {{
            background: transparent;
        }}

        QTabBar::tab {{
            min-width: 120px;
            min-height: 40px;
            max-height: 40px;

            background-color: #0c1728;
            color: #9caec5;

            padding: 0px 10px;
            margin-right: 8px;

            border: 1px solid #1c2e46;
            border-radius: 10px;

            font-weight: 650;
        }}

        QTabBar::tab:selected {{
            color: #75b2ff;
            background-color: #102745;
            border: 1px solid #2f84ff;
        }}

        QTabBar::tab:hover:!selected {{
            color: #eef5ff;
            background-color: #112238;
            border: 1px solid #28527f;
        }}

        /*
         * Custom tab close button.
         * This replaces Qt's platform-dependent orange close icon.
         */
        QWidget#tabCloseContainer {{
            background: transparent;
            border: none;
        }}

        QToolButton#tabCloseButton {{
            min-width: 18px;
            max-width: 18px;
            min-height: 18px;
            max-height: 18px;

            margin: 0px;
            padding: 0px;

            color: #b9c8da;
            background-color: transparent;
            border: none;
            border-radius: 9px;

            font-family: 'Segoe UI Symbol', 'Segoe UI', Arial, sans-serif;
            font-size: 12pt;
            font-weight: 700;
        }}

        QToolButton#tabCloseButton:hover {{
            color: #ffffff;
            background-color: #ef4444;
        }}

        QToolButton#tabCloseButton:pressed {{
            color: #ffffff;
            background-color: #b91c1c;
        }}

        QScrollArea {{
            border: none;
            background: transparent;
        }}

        QScrollBar:vertical {{
            width: 9px;
            margin: 3px 1px;
            background: transparent;
        }}
        QScrollBar::handle:vertical {{
            min-height: 28px;
            background: #354c6b;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: #55749d;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            height: 0px;
            background: transparent;
        }}

        QSplitter::handle {{
            background: transparent;
        }}
        QSplitter::handle:horizontal {{
            width: 10px;
        }}
        QSplitter::handle:vertical {{
            height: 10px;
        }}

        QMessageBox {{
            background-color: #101d30;
        }}
    """


class VirtualLED(QLabel):
    def __init__(self, size=16):
        super().__init__()
        self.setFixedSize(size, size)
        self.connected = False
        self.blink_state = True
        
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.toggle_blink)
        
        self.update_style()

    def set_state(self, connected):
        self.connected = connected
        if connected:
            if not self.blink_timer.isActive():
                self.blink_timer.start(500) 
        else:
            self.blink_timer.stop()
            self.blink_state = True # Reset to solid when off/red
        self.update_style()

    def toggle_blink(self):
        self.blink_state = not self.blink_state
        self.update_style()

    def update_style(self):
        if self.connected:
            base = THEME["success"] if self.blink_state else "#14532d"
            border = "#86efac" if self.blink_state else "#166534"
        else:
            base = THEME["danger"]
            border = "#fca5a5"

        radius = self.width() // 2
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {base};
                border: 2px solid {border};
                border-radius: {radius}px;
            }}
        """)


class LiveGraphPanel(QFrame):
    """Embedded, continuously updating graph used inside each characteristic tab."""

    SERIES_COLORS = (
        "#2f84ff",
        "#22c55e",
        "#f59e0b",
        "#a78bfa",
        "#22d3ee",
        "#fb7185",
    )

    def __init__(self, parent_control):
        super().__init__()
        self.parent_control = parent_control
        self.setObjectName("graphCard")
        self.plot_data = {}
        self.max_samples = 120
        self.paused = False
        self.setup_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_plot)
        self.timer.start(120)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("LIVE GRAPH")
        title.setObjectName("cardTitle")
        header.addWidget(title)
        header.addStretch()

        self.pause_btn = QPushButton("Ⅱ")
        self.pause_btn.setObjectName("iconButton")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setToolTip("Pause graph updates")
        self.pause_btn.toggled.connect(self._set_paused)
        header.addWidget(self.pause_btn)

        clear_icon_btn = QPushButton("×")
        clear_icon_btn.setObjectName("iconButton")
        clear_icon_btn.setToolTip("Remove all graph series")
        clear_icon_btn.clicked.connect(self.on_clear_graph)
        header.addWidget(clear_icon_btn)
        layout.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(9)
        add_label = QLabel("Add to graph")
        add_label.setObjectName("mutedLabel")
        controls.addWidget(add_label)

        self.calc_selector = QComboBox()
        self.calc_selector.setMinimumWidth(185)
        controls.addWidget(self.calc_selector)

        add_btn = QPushButton("Add series")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self.on_add_series)
        controls.addWidget(add_btn)

        clear_btn = QPushButton("Clear all")
        clear_btn.setObjectName("smallButton")
        clear_btn.clicked.connect(self.on_clear_graph)
        controls.addWidget(clear_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.active_series_lbl = QLabel("No active series")
        self.active_series_lbl.setObjectName("mutedLabel")
        layout.addWidget(self.active_series_lbl)

        self.figure = Figure(facecolor=safe_color("#091426"), tight_layout=False)
        self.figure.subplots_adjust(left=0.075, right=0.985, top=0.95, bottom=0.12)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(305)
        layout.addWidget(self.canvas, 1)

        self.ax = self.figure.add_subplot(111)
        self._style_axes()
        self.ax.text(
            0.5,
            0.5,
            "Add a byte or calculated value to begin plotting",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            color="#71849f",
            fontsize=10,
        )
        self.canvas.draw_idle()

        footer = QHBoxLayout()
        footer.addStretch()
        save_btn = QPushButton("Save preset")
        save_btn.setObjectName("smallButton")
        save_btn.clicked.connect(self.parent_control.on_save_preset)
        footer.addWidget(save_btn)
        load_btn = QPushButton("Load preset")
        load_btn.setObjectName("smallButton")
        load_btn.clicked.connect(self.parent_control.on_load_preset)
        footer.addWidget(load_btn)
        layout.addLayout(footer)

        self.refresh_selector()

    def _style_axes(self):
        self.ax.set_facecolor(safe_color("#081426"))
        self.ax.tick_params(colors="#c4d2e5", labelsize=8)
        for spine in self.ax.spines.values():
            spine.set_edgecolor("#29415f")
        self.ax.grid(True, color="#243b59", linestyle="--", linewidth=0.65, alpha=0.55)
        self.ax.set_axisbelow(True)
        self.ax.margins(x=0.02)

    def _set_paused(self, paused: bool):
        self.paused = paused
        self.pause_btn.setText("▶" if paused else "Ⅱ")
        self.pause_btn.setToolTip("Resume graph updates" if paused else "Pause graph updates")

    def refresh_selector(self):
        current_key = self.calc_selector.currentData()
        self.calc_selector.blockSignals(True)
        self.calc_selector.clear()

        for name_edit, formula_edit, _result_label, _row in self.parent_control.calc_widgets:
            name = name_edit.text().strip()
            if name:
                self.calc_selector.addItem(name, name)

        if self.calc_selector.count():
            self.calc_selector.insertSeparator(self.calc_selector.count())

        for index in range(32):
            self.calc_selector.addItem(f"b{index}  ·  Byte {index}", f"b{index}")

        restored = False
        if current_key is not None:
            for index in range(self.calc_selector.count()):
                if self.calc_selector.itemData(index) == current_key:
                    self.calc_selector.setCurrentIndex(index)
                    restored = True
                    break
        if not restored and self.calc_selector.count():
            self.calc_selector.setCurrentIndex(0)
        self.calc_selector.blockSignals(False)

    def on_add_series(self):
        key = self.calc_selector.currentData()
        label = self.calc_selector.currentText().split("  ·  ", 1)[0].strip()
        if not key:
            QMessageBox.information(self, "Graph", "Select a value to plot first.")
            return

        if key in self.plot_data:
            QMessageBox.information(self, "Graph", f"'{label}' is already plotted.")
            return

        self.plot_data[key] = {"label": label, "samples": []}
        self.update_active_label()
        self.update_plot(force=True)

    def update_active_label(self):
        labels = [series["label"] for series in self.plot_data.values()]
        self.active_series_lbl.setText(
            "Active: " + ", ".join(labels) if labels else "No active series"
        )

    def on_clear_graph(self):
        self.plot_data.clear()
        self.update_active_label()
        self.update_plot(force=True)

    def ingest_payload(self, data: bytes, calculated_values: Dict[str, float]):
        if self.paused or not self.plot_data:
            return

        sample_added = False

        for key, series in self.plot_data.items():
            value = None
            if key.startswith("b") and key[1:].isdigit():
                byte_index = int(key[1:])
                if byte_index < len(data):
                    value = data[byte_index]
            elif key in calculated_values:
                value = calculated_values[key]

            if isinstance(value, (int, float)):
                series["samples"].append(value)
                sample_added = True
                if len(series["samples"]) > self.max_samples:
                    del series["samples"][:-self.max_samples]

        # Refresh immediately after a valid sample. The timer remains as a fallback.
        if sample_added:
            self.update_plot(force=True)

    def update_plot(self, force=False):
        if self.paused and not force:
            return
        if not self.isVisible() and not force:
            return

        self.ax.clear()
        self._style_axes()

        has_data = False
        for series_index, series in enumerate(self.plot_data.values()):
            samples = series["samples"]
            if not samples:
                continue
            has_data = True
            self.ax.plot(
                range(len(samples)),
                samples,
                label=series["label"],
                linewidth=2.1,
                marker="o",
                markersize=3.2,
                color=self.SERIES_COLORS[series_index % len(self.SERIES_COLORS)],
            )

        if has_data:
            legend = self.ax.legend(
                loc="upper left",
                facecolor="#0c192b",
                edgecolor="#3b5270",
                framealpha=0.96,
                fontsize=8,
            )
            for label in legend.get_texts():
                label.set_color("#e6eef9")
        else:
            self.ax.text(
                0.5,
                0.5,
                "Add a byte or calculated value to begin plotting",
                transform=self.ax.transAxes,
                ha="center",
                va="center",
                color="#71849f",
                fontsize=10,
            )

        self.canvas.draw_idle()


class CharacteristicControlWidget(QWidget):
    char_renamed = pyqtSignal(str, str)  # uuid, new_name
    notification_received = pyqtSignal(bytes)

    def __init__(self, client: BleakClient, service_uuid: str, char_uuid: str, handle: int, properties: list):
        super().__init__()
        self.client = client
        self.service_uuid = service_uuid
        self.char_uuid = char_uuid
        self.handle = handle
        self.properties = properties
        
        self.read_byte_widgets = []
        self.notify_byte_widgets = []
        self.write_byte_widgets = []
        self.last_notify_bytes = b""
        self.calc_widgets = [] # (name_edit, formula_edit, result_lbl, row)
        self.decoded_rows = {} # name -> (key_lbl, val_lbl)
        self.graph_panel = None

        # Route Bleak notifications safely onto the Qt GUI thread.
        self.notification_received.connect(self._process_notification_payload)

        self.setup_ui()

    def _on_rename_clicked(self):
        new_name, ok = QInputDialog.getText(self, "Rename Characteristic", "Enter custom name:", text=self.char_val_lbl.text())
        if ok and new_name:
            self.char_renamed.emit(self.char_uuid, new_name)

    def _create_box(self, title_text: str):
        box = QFrame()
        box.setObjectName("contentCard")

        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(18, 16, 18, 18)
        box_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(9)

        accent_bar = QFrame()
        accent_bar.setFixedSize(4, 18)
        accent_bar.setStyleSheet(
            f"background-color: {THEME['accent']}; border-radius: 2px; border: none;"
        )
        header_layout.addWidget(accent_bar)

        title_lbl = QLabel(title_text.upper())
        title_lbl.setObjectName("cardTitle")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()
        box_layout.addLayout(header_layout)

        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        box_layout.addWidget(content)

        return box, content

    def setup_ui(self):
        main_vbox = QVBoxLayout(self)
        main_vbox.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        main_vbox.addWidget(self.scroll_area)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        self.scroll_area.setWidget(container)

        self.content_layout = QVBoxLayout(container)
        self.content_layout.setContentsMargins(12, 14, 12, 18)
        self.content_layout.setSpacing(12)

        # Compact characteristic header.
        header_box = QFrame()
        header_box.setObjectName("characteristicHeader")
        header_layout = QHBoxLayout(header_box)
        header_layout.setContentsMargins(17, 13, 15, 13)
        header_layout.setSpacing(13)

        char_mark = QLabel("G")
        char_mark.setFixedSize(38, 38)
        char_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        char_mark.setStyleSheet(
            f"background-color: {THEME['accent']}; color: white; border-radius: 10px; "
            "font-size: 13pt; font-weight: 900;"
        )
        header_layout.addWidget(char_mark)

        identity_layout = QVBoxLayout()
        identity_layout.setSpacing(2)
        identity_caption = QLabel("GATT CHARACTERISTIC")
        identity_caption.setObjectName("sectionLabel")
        self.char_val_lbl = QLabel(self.char_uuid)
        self.char_val_lbl.setObjectName("cardTitle")
        self.char_val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        identity_meta = QLabel(f"Service {self.service_uuid}   •   Handle {self.handle}")
        identity_meta.setObjectName("mutedLabel")
        identity_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        identity_meta.setWordWrap(True)
        identity_layout.addWidget(identity_caption)
        identity_layout.addWidget(self.char_val_lbl)
        identity_layout.addWidget(identity_meta)
        header_layout.addLayout(identity_layout, 1)

        properties_layout = QHBoxLayout()
        properties_layout.setSpacing(6)
        for prop in self.properties:
            chip = QLabel(prop.upper())
            chip.setStyleSheet(
                "background-color: rgba(47, 132, 255, 0.14); color: #75b2ff; "
                "border: 1px solid #2e5c91; border-radius: 9px; padding: 4px 9px; "
                "font-size: 7.5pt; font-weight: 800;"
            )
            properties_layout.addWidget(chip)
        header_layout.addLayout(properties_layout)

        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("smallButton")
        rename_btn.clicked.connect(self._on_rename_clicked)
        header_layout.addWidget(rename_btn)
        self.content_layout.addWidget(header_box)

        # Top dashboard row: activity log and live payload values.
        logs_splitter = QSplitter(Qt.Orientation.Horizontal)
        logs_splitter.setChildrenCollapsible(False)
        logs_splitter.setMinimumHeight(215)

        log_box, log_content = self._create_box("SYSTEM LOG")
        log_layout = QVBoxLayout(log_content)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_controls = QHBoxLayout()
        log_controls.addStretch()
        clear_log_btn = QPushButton("Clear")
        clear_log_btn.setObjectName("smallButton")
        log_controls.addWidget(clear_log_btn)
        log_layout.addLayout(log_controls)
        self.log_tx = QTextEdit()
        self.log_tx.setObjectName("consoleText")
        self.log_tx.setReadOnly(True)
        self.log_tx.setPlaceholderText("Connection and GATT activity will appear here.")
        clear_log_btn.clicked.connect(self.log_tx.clear)
        log_layout.addWidget(self.log_tx)
        logs_splitter.addWidget(log_box)

        values_box, values_content = self._create_box("LIVE VALUES")
        values_layout = QVBoxLayout(values_content)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_controls = QHBoxLayout()
        self.compact_cb = QCheckBox("Compact view")
        self.compact_cb.setChecked(True)
        values_controls.addWidget(self.compact_cb)
        values_controls.addStretch()
        clear_values_btn = QPushButton("Clear")
        clear_values_btn.setObjectName("smallButton")
        values_controls.addWidget(clear_values_btn)
        values_layout.addLayout(values_controls)
        self.values_tx = QTextEdit()
        self.values_tx.setObjectName("consoleText")
        self.values_tx.setReadOnly(True)
        self.values_tx.setPlaceholderText("Read and notification payloads will appear here.")
        clear_values_btn.clicked.connect(self.values_tx.clear)
        values_layout.addWidget(self.values_tx)
        logs_splitter.addWidget(values_box)
        logs_splitter.setSizes([560, 560])
        self.content_layout.addWidget(logs_splitter)

        # Main dashboard row: compact controls at left and integrated graph at right.
        dashboard_splitter = QSplitter(Qt.Orientation.Horizontal)
        dashboard_splitter.setChildrenCollapsible(False)
        dashboard_splitter.setMinimumHeight(420)

        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        self.read_box, read_content = self._create_box("READ")
        self.read_box.setObjectName("controlCard")
        self.setup_read_ui(read_content)
        controls_layout.addWidget(self.read_box)

        self.notify_box, notify_content = self._create_box("NOTIFY")
        self.notify_box.setObjectName("controlCard")
        self.setup_notify_ui(notify_content)
        controls_layout.addWidget(self.notify_box)

        self.write_box, write_content = self._create_box("WRITE")
        self.write_box.setObjectName("controlCard")
        self.setup_write_ui(write_content)
        controls_layout.addWidget(self.write_box)
        controls_layout.addStretch()

        dashboard_splitter.addWidget(controls_widget)
        self.graph_panel = LiveGraphPanel(self)
        self.graph_panel.refresh_selector()
        dashboard_splitter.addWidget(self.graph_panel)
        dashboard_splitter.setSizes([315, 790])
        self.content_layout.addWidget(dashboard_splitter)

        # Advanced formula tools remain available without crowding the dashboard.
        advanced_row = QHBoxLayout()
        advanced_hint = QLabel("Advanced tools")
        advanced_hint.setObjectName("sectionLabel")
        advanced_row.addWidget(advanced_hint)
        advanced_row.addStretch()
        self.advanced_toggle_btn = QPushButton("Show calculated values")
        self.advanced_toggle_btn.setObjectName("smallButton")
        advanced_row.addWidget(self.advanced_toggle_btn)
        self.content_layout.addLayout(advanced_row)

        self.calc_box_frame, calc_content = self._create_box("CALCULATED VALUES")
        self.calc_box_frame.hide()
        self.content_layout.addWidget(self.calc_box_frame)
        self.setup_calc_ui(calc_content)
        self.advanced_toggle_btn.clicked.connect(self._toggle_advanced_tools)

        self.decoded_box_frame, self.decoded_content_widget = self._create_box("DECODED DATA")
        self.decoded_layout = QVBoxLayout(self.decoded_content_widget)
        self.content_layout.addWidget(self.decoded_box_frame)
        self.decoded_box_frame.setVisible(self.char_uuid.lower() == TARGET_STATUS_UUID)

        self._apply_property_restrictions()
    def _toggle_advanced_tools(self):
        visible = not self.calc_box_frame.isVisible()
        self.calc_box_frame.setVisible(visible)
        self.advanced_toggle_btn.setText(
            "Hide calculated values" if visible else "Show calculated values"
        )
        if visible:
            self.scroll_area.ensureWidgetVisible(self.calc_box_frame, 20, 20)

    def _apply_property_restrictions(self):
        """Enables/Disables sections based on characteristic properties"""
        # 1. READ logic
        can_read = "read" in self.properties
        self.read_box.setEnabled(can_read)
        self._set_box_opacity(self.read_box, 1.0 if can_read else 0.4)
        
        # 2. NOTIFY logic
        can_notify = any(p in self.properties for p in ["notify", "indicate"])
        self.notify_box.setEnabled(can_notify)
        self._set_box_opacity(self.notify_box, 1.0 if can_notify else 0.4)
        
        # 3. WRITE logic
        can_write = any(p in self.properties for p in ["write", "write-without-response"])
        self.write_box.setEnabled(can_write)
        self._set_box_opacity(self.write_box, 1.0 if can_write else 0.4)

    def _set_box_opacity(self, widget, opacity):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(opacity)
        widget.setGraphicsEffect(effect)

    def setup_calc_ui(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        ctrl = QHBoxLayout()
        helper = QLabel("Create reusable formulas using b0, b1, b2 …")
        helper.setObjectName("mutedLabel")
        ctrl.addWidget(helper)
        ctrl.addStretch()

        graph_btn = QPushButton("Jump to graph")
        graph_btn.setObjectName("smallButton")
        graph_btn.clicked.connect(self.on_graph_clicked)
        ctrl.addWidget(graph_btn)

        add_btn = QPushButton("Add calculated value")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self.on_add_calc)
        ctrl.addWidget(add_btn)
        layout.addLayout(ctrl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(90)
        self.calc_area = QWidget()
        self.calc_layout = QVBoxLayout(self.calc_area)
        self.calc_layout.setContentsMargins(0, 0, 0, 0)
        self.calc_layout.setSpacing(7)
        self.calc_layout.addStretch()
        scroll.setWidget(self.calc_area)
        layout.addWidget(scroll)

        self._load_calcs()

    def on_graph_clicked(self):
        if self.graph_panel:
            self.scroll_area.ensureWidgetVisible(self.graph_panel, 20, 20)
            self.graph_panel.setFocus()

    def on_add_calc(self, checked=False, name="", formula=""):
        # checked is passed by the button's clicked signal
        if isinstance(checked, bool):
            # If triggered from button, name/formula will be empty
            pass
        elif isinstance(checked, str):
            # If called manually from _load_calcs with positional args
            formula = name
            name = checked
            
        row = QWidget()
        row_layout = QHBoxLayout(row)
        
        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("Name (e.g. Temp)")
        name_edit.textChanged.connect(self._on_calc_definition_changed)
        
        formula_edit = QLineEdit(formula)
        formula_edit.setPlaceholderText("Formula (e.g. b0 * 256 + b1)")
        formula_edit.textChanged.connect(self._on_calc_definition_changed)
        
        res_lbl = QLabel("Result: --")
        res_lbl.setStyleSheet(f"font-weight: bold; color: {THEME['success']};")
        
        del_btn = QPushButton("X")
        del_btn.setFixedWidth(30)
        del_btn.setStyleSheet(f"background-color: {THEME['danger']};")
        del_btn.clicked.connect(lambda: self._remove_calc(row))
        
        row_layout.addWidget(name_edit)
        row_layout.addWidget(formula_edit)
        row_layout.addWidget(res_lbl)
        row_layout.addWidget(del_btn)
        
        # Insert before the stretch
        self.calc_layout.insertWidget(self.calc_layout.count() - 1, row)
        self.calc_widgets.append((name_edit, formula_edit, res_lbl, row))
        self._save_calcs()
        if self.graph_panel:
            self.graph_panel.refresh_selector()

    def _on_calc_definition_changed(self, *_args):
        self._save_calcs()
        if self.graph_panel:
            self.graph_panel.refresh_selector()

    def _remove_calc(self, row_widget):
        for i, (n, f, r, w) in enumerate(self.calc_widgets):
            if w == row_widget:
                self.calc_widgets.pop(i)
                break
        row_widget.deleteLater()
        self._save_calcs()
        if self.graph_panel:
            self.graph_panel.refresh_selector()

    def _save_calcs(self):
        presets = {}
        path = get_data_path("char_calcs.json")
        if os.path.exists(path):
            try:
                with open(path, "r") as f: presets = json.load(f)
            except: pass
            
        data = []
        for name_edit, formula_edit, res_lbl, row in self.calc_widgets:
            data.append({"name": name_edit.text(), "formula": formula_edit.text()})
            
        presets[self.char_uuid] = data
        try:
            with open(path, "w") as f: json.dump(presets, f)
        except: pass

    def _load_calcs(self):
        path = get_data_path("char_calcs.json")
        if not os.path.exists(path): return
        try:
            with open(path, "r") as f:
                presets = json.load(f)
                char_data = presets.get(self.char_uuid, [])
                for item in char_data:
                    self.on_add_calc(item["name"], item["formula"])
        except: pass

    def _u16_be(self, hi: int, lo: int) -> int: return ((hi & 0xFF) << 8) | (lo & 0xFF)
    
    def _decode_status(self, payload: bytes) -> Dict:
        b = payload
        if len(b) < 34: return {}
        def pairs(start, count):
            out = []
            for i in range(count):
                if start + 2*i + 1 < len(b):
                    hi = b[start + 2*i]; lo = b[start + 2*i + 1]
                    out.append(self._u16_be(hi, lo))
            return out
        return {
            "current_status": b[0], "error_code": b[1],
            "temperature": pairs(2, 4), "pressure": pairs(10, 6),
            "level": pairs(22, 2), "flowrate": pairs(26, 4)
        }

    def _update_decoded_ui(self, data: Dict):
        for name, val in data.items():
            if name not in self.decoded_rows:
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 2, 0, 2)
                key_lbl = QLabel(f"{name}:")
                key_lbl.setFixedWidth(140)
                val_lbl = QLabel(str(val))
                val_lbl.setStyleSheet(f"font-weight: bold; color: {THEME['accent_bright']};")
                row_layout.addWidget(key_lbl)
                row_layout.addWidget(val_lbl)
                self.decoded_layout.addWidget(row)
                self.decoded_rows[name] = (key_lbl, val_lbl)
            else:
                _, val_lbl = self.decoded_rows[name]
                val_lbl.setText(str(val))

    def _update_calculations(self, data: bytes):
        namespace = {f"b{index}": value for index, value in enumerate(data)}
        calculated_values = {}

        for calc_index, (name_edit, formula_edit, result_label, _row) in enumerate(self.calc_widgets):
            name = name_edit.text().strip() or f"value_{calc_index + 1}"
            formula = formula_edit.text().strip()
            if not formula:
                continue
            try:
                result = eval_formula(formula, namespace)
                if isinstance(result, float) and result.is_integer():
                    result = int(result)
                result_label.setText(f"Result: {result}")
                calculated_values[name] = result
            except Exception:
                result_label.setText("Error")

        if self.graph_panel:
            self.graph_panel.ingest_payload(data, calculated_values)

        if self.char_uuid.lower() == TARGET_STATUS_UUID:
            decoded = self._decode_status(data)
            if decoded:
                self._update_decoded_ui(decoded)

    def _toggle_editor(self, container: QWidget, button: QPushButton, label: str):
        visible = not container.isVisible()
        container.setVisible(visible)
        button.setText(("Hide " if visible else "Show ") + label)

    def setup_read_ui(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        row = QHBoxLayout()
        label = QLabel("Byte count")
        label.setObjectName("mutedLabel")
        row.addWidget(label)
        self.read_size_input = QLineEdit("1")
        self.read_size_input.setFixedWidth(66)
        self.read_size_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.read_size_input)
        row.addStretch()
        self.read_btn = QPushButton("Read")
        self.read_btn.setObjectName("primaryButton")
        self.read_btn.clicked.connect(self.on_read_clicked)
        row.addWidget(self.read_btn)
        layout.addLayout(row)

        editor_toggle = QPushButton("Show byte editor")
        editor_toggle.setObjectName("toggleButton")
        layout.addWidget(editor_toggle)

        self.read_editor_container = QWidget()
        editor_layout = QVBoxLayout(self.read_editor_container)
        editor_layout.setContentsMargins(0, 3, 0, 0)
        build_btn = QPushButton("Build / refresh editor")
        build_btn.setObjectName("smallButton")
        build_btn.clicked.connect(self.on_create_read_editor)
        editor_layout.addWidget(build_btn)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(160)
        self.read_editor_widget = QWidget()
        self.read_editor_layout = QGridLayout(self.read_editor_widget)
        scroll.setWidget(self.read_editor_widget)
        editor_layout.addWidget(scroll)
        self.read_editor_container.hide()
        editor_toggle.clicked.connect(
            lambda: self._toggle_editor(self.read_editor_container, editor_toggle, "byte editor")
        )
        layout.addWidget(self.read_editor_container)

    def setup_notify_ui(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        status_row = QHBoxLayout()
        self.notify_state_dot = QLabel()
        self.notify_state_dot.setFixedSize(10, 10)
        status_row.addWidget(self.notify_state_dot)
        self.notify_state_lbl = QLabel("Not subscribed")
        self.notify_state_lbl.setObjectName("mutedLabel")
        status_row.addWidget(self.notify_state_lbl)
        status_row.addStretch()
        self.notify_btn = QPushButton("Subscribe")
        self.notify_btn.setObjectName("successButton")
        self.notify_btn.setCheckable(True)
        self.notify_btn.clicked.connect(self.on_notify_toggled)
        status_row.addWidget(self.notify_btn)
        layout.addLayout(status_row)
        self._set_notify_visual_state(False)

        options_row = QHBoxLayout()
        label = QLabel("Byte count")
        label.setObjectName("mutedLabel")
        options_row.addWidget(label)
        self.notify_size_input = QLineEdit("34")
        self.notify_size_input.setFixedWidth(66)
        self.notify_size_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        options_row.addWidget(self.notify_size_input)
        options_row.addStretch()
        editor_toggle = QPushButton("Show byte editor")
        editor_toggle.setObjectName("toggleButton")
        options_row.addWidget(editor_toggle)
        layout.addLayout(options_row)

        self.notify_editor_container = QWidget()
        editor_layout = QVBoxLayout(self.notify_editor_container)
        editor_layout.setContentsMargins(0, 3, 0, 0)
        build_btn = QPushButton("Build / refresh editor")
        build_btn.setObjectName("smallButton")
        build_btn.clicked.connect(self.on_create_notify_editor)
        editor_layout.addWidget(build_btn)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(165)
        self.notify_editor_widget = QWidget()
        self.notify_editor_layout = QGridLayout(self.notify_editor_widget)
        scroll.setWidget(self.notify_editor_widget)
        editor_layout.addWidget(scroll)
        self.notify_editor_container.hide()
        editor_toggle.clicked.connect(
            lambda: self._toggle_editor(self.notify_editor_container, editor_toggle, "byte editor")
        )
        layout.addWidget(self.notify_editor_container)

    def setup_write_ui(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        top_row = QHBoxLayout()
        label = QLabel("Byte count")
        label.setObjectName("mutedLabel")
        top_row.addWidget(label)
        self.write_size_input = QLineEdit("1")
        self.write_size_input.setFixedWidth(66)
        self.write_size_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self.write_size_input)
        top_row.addStretch()
        self.write_btn = QPushButton("Write")
        self.write_btn.setObjectName("primaryButton")
        self.write_btn.clicked.connect(self.on_fill_write_clicked)
        top_row.addWidget(self.write_btn)
        layout.addLayout(top_row)

        self.paste_input = QTextEdit()
        self.paste_input.setObjectName("consoleText")
        self.paste_input.setPlaceholderText("00   or   01 02 03 04")
        self.paste_input.setFixedHeight(54)
        layout.addWidget(self.paste_input)

        utility_row = QHBoxLayout()
        editor_toggle = QPushButton("Show byte editor")
        editor_toggle.setObjectName("toggleButton")
        utility_row.addWidget(editor_toggle)
        utility_row.addStretch()
        save_btn = QPushButton("Save preset")
        save_btn.setObjectName("smallButton")
        save_btn.clicked.connect(self.on_save_preset)
        utility_row.addWidget(save_btn)
        load_btn = QPushButton("Load preset")
        load_btn.setObjectName("smallButton")
        load_btn.clicked.connect(self.on_load_preset)
        utility_row.addWidget(load_btn)
        layout.addLayout(utility_row)

        self.write_editor_container = QWidget()
        editor_layout = QVBoxLayout(self.write_editor_container)
        editor_layout.setContentsMargins(0, 3, 0, 0)
        build_btn = QPushButton("Build / refresh editor")
        build_btn.setObjectName("smallButton")
        build_btn.clicked.connect(self.on_create_write_editor)
        editor_layout.addWidget(build_btn)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(185)
        self.write_editor_widget = QWidget()
        self.write_editor_layout = QGridLayout(self.write_editor_widget)
        scroll.setWidget(self.write_editor_widget)
        editor_layout.addWidget(scroll)
        send_editor_btn = QPushButton("Send editor bytes")
        send_editor_btn.setObjectName("successButton")
        send_editor_btn.clicked.connect(self.on_write_clicked)
        editor_layout.addWidget(send_editor_btn)
        self.write_editor_container.hide()
        editor_toggle.clicked.connect(
            lambda: self._toggle_editor(self.write_editor_container, editor_toggle, "byte editor")
        )
        layout.addWidget(self.write_editor_container)

    @staticmethod
    def _clear_grid_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_viewer_rows(self, layout, size, widgets_list):
        self._clear_grid_layout(layout)
        widgets_list.clear()

        headers = ("BYTE NAME", "HEX VALUE", "INDEX")
        for column, text in enumerate(headers):
            label = QLabel(text)
            label.setObjectName("sectionLabel")
            layout.addWidget(label, 0, column)

        names_path = get_data_path("char_names.json")
        saved_names = {}
        if os.path.exists(names_path):
            try:
                with open(names_path, "r", encoding="utf-8") as file:
                    all_names = json.load(file)
                    saved_names = all_names.get(self.char_uuid, {})
            except (OSError, json.JSONDecodeError):
                pass

        for index in range(size):
            default_name = saved_names.get(str(index), f"Byte {index + 1}")
            name_edit = QLineEdit(default_name)
            name_edit.textChanged.connect(
                lambda value, byte_index=index: self.on_byte_name_changed(byte_index, value)
            )

            value_label = QLabel("--")
            value_label.setObjectName("monoLabel")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            index_label = QLabel(f"#{index}")
            index_label.setObjectName("mutedLabel")
            index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            layout.addWidget(name_edit, index + 1, 0)
            layout.addWidget(value_label, index + 1, 1)
            layout.addWidget(index_label, index + 1, 2)
            widgets_list.append((name_edit, value_label, index_label))

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)

    def on_byte_name_changed(self, index, name):
        names_path = get_data_path("char_names.json")
        all_names = {}
        if os.path.exists(names_path):
            try:
                with open(names_path, "r", encoding="utf-8") as file:
                    all_names = json.load(file)
            except (OSError, json.JSONDecodeError):
                pass

        char_names = all_names.get(self.char_uuid, {})
        char_names[str(index)] = name
        all_names[self.char_uuid] = char_names

        try:
            with open(names_path, "w", encoding="utf-8") as file:
                json.dump(all_names, file, indent=2)
        except OSError:
            pass

    def _build_write_rows(self, layout, size, widgets_list):
        self._clear_grid_layout(layout)
        widgets_list.clear()

        headers = ("BYTE NAME", "HEX VALUE", "INDEX")
        for column, text in enumerate(headers):
            label = QLabel(text)
            label.setObjectName("sectionLabel")
            layout.addWidget(label, 0, column)

        for index in range(size):
            name_edit = QLineEdit(f"Byte {index + 1}")
            value_edit = QLineEdit("00")
            value_edit.setFixedWidth(76)
            value_edit.setMaxLength(2)
            value_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_edit.setToolTip("Enter one hexadecimal byte from 00 to FF")

            index_label = QLabel(f"#{index}")
            index_label.setObjectName("mutedLabel")
            index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            layout.addWidget(name_edit, index + 1, 0)
            layout.addWidget(value_edit, index + 1, 1)
            layout.addWidget(index_label, index + 1, 2)
            widgets_list.append((name_edit, value_edit, index_label))

        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 0)

    def _editor_size(self, field: QLineEdit) -> Optional[int]:
        try:
            size = int(field.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid byte count", "Enter a whole number from 1 to 512.")
            return None

        if not 1 <= size <= 512:
            QMessageBox.warning(self, "Invalid byte count", "Byte count must be between 1 and 512.")
            return None
        return size

    def on_create_read_editor(self):
        size = self._editor_size(self.read_size_input)
        if size is not None:
            self._build_viewer_rows(self.read_editor_layout, size, self.read_byte_widgets)

    def on_create_notify_editor(self):
        size = self._editor_size(self.notify_size_input)
        if size is not None:
            self._build_viewer_rows(self.notify_editor_layout, size, self.notify_byte_widgets)

    def on_create_write_editor(self):
        size = self._editor_size(self.write_size_input)
        if size is not None:
            self._build_write_rows(self.write_editor_layout, size, self.write_byte_widgets)

    def log(self, text):
        import datetime
        import html

        now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        tag_match = re.match(r"(\[[A-Z]+\])\s*(.*)", text)
        tag = tag_match.group(1) if tag_match else ""
        message = tag_match.group(2) if tag_match else text
        tag_colors = {
            "[READ]": "#4ade80",
            "[WRITE]": "#f59e0b",
            "[NOTIFY]": "#4f9cff",
            "[NOTIF]": "#4f9cff",
        }
        tag_color = tag_colors.get(tag, "#f87171" if "Error" in text else "#9fb1c8")
        tag_html = (
            f'<span style="color:{tag_color}; font-weight:700;">{html.escape(tag)}</span> '
            if tag else ""
        )
        self.log_tx.append(
            f'<span style="color:#71849f;">[{now}]</span> '
            f'{tag_html}<span style="color:#e5eefb;">{html.escape(message)}</span>'
        )

    def log_value(self, text):
        if self.compact_cb.isChecked():
            # Robust compacting using regex (from graph_live_blink)
            text = re.sub(r'^\[.*?\]\s*', '', text)
        self.values_tx.append(text)

    @qasync.asyncSlot()
    async def on_read_clicked(self):
        try:
            data = await self.client.read_gatt_char(self.char_uuid)
            hex_str = " ".join(f"{b:02X}" for b in data)
            self.log(f"[READ] {hex_str} (len={len(data)})")
            self.log_value(f"[READ] {hex_str}")
            
            # Update editor
            for i, (name_edit, val_lbl, idx_lbl) in enumerate(self.read_byte_widgets):
                if i < len(data):
                    val_lbl.setText(f"{data[i]:02X}")
                else:
                    val_lbl.setText("--")
            
            # Update calculations and decoding
            self._update_calculations(data)
        except Exception as e:
            self.log(f"[READ] Error: {e}")

    def parse_hex_string(self, text: str) -> bytes:
        # Robust hex parsing (from graph_live_blink)
        t = text.strip()
        t = re.sub(r'0x', '', t, flags=re.IGNORECASE)
        t = re.sub(r'[^0-9a-fA-F]', ' ', t)
        parts = [p for p in t.split() if p]
        out = []
        for p in parts:
            if len(p) <= 2:
                try: out.append(int(p, 16) & 0xFF)
                except: pass
            else:
                if len(p) % 2 == 1: p = "0" + p
                for i in range(0, len(p), 2):
                    try: out.append(int(p[i:i+2], 16) & 0xFF)
                    except: pass
        return bytes(out)

    @qasync.asyncSlot()
    async def on_write_clicked(self, checked=False):
        if not self.write_byte_widgets:
            QMessageBox.warning(self, "Write Error", "Create the WRITE editor first.")
            return
            
        try:
            data_list = []
            for name_edit, val_edit, idx_lbl in self.write_byte_widgets:
                val = val_edit.text().strip().replace("0x", "")
                if not val: val = "00"
                # 2. Validate hex values before sending
                data_list.append(int(val, 16) & 0xFF)
            data = bytes(data_list)
            
            # 3. Support write and write-without-response
            response = "write" in self.properties
            # 4. Send payload using write_gatt_char
            await self.client.write_gatt_char(self.char_uuid, data, response=response)
            self.log(f"[WRITE] {data.hex().upper()}")
        except ValueError:
            QMessageBox.critical(self, "Validation Error", "Invalid hex value detected in editor.")
        except Exception as e:
            self.log(f"[WRITE] Error: {e}")

    @qasync.asyncSlot()
    async def on_fill_write_clicked(self):
        # Use toPlainText() for QTextEdit
        text = self.paste_input.toPlainText().strip()
        try:
            # 6. Parse pasted hex into bytes
            data = self.parse_hex_string(text)
            if not data:
                QMessageBox.warning(self, "Write", "Enter at least one hexadecimal byte.")
                return
            # Fill the advanced editor, then send the payload.
            self.write_size_input.setText(str(len(data)))
            self.on_create_write_editor()
            for i, (name_edit, val_edit, idx_lbl) in enumerate(self.write_byte_widgets):
                val_edit.setText(f"{data[i]:02X}")
            await self.on_write_clicked()
        except Exception as e:
            QMessageBox.warning(self, "Fill & Write Error", f"Failed to parse hex string: {e}")

    @qasync.asyncSlot()
    async def on_save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not (ok and name): return
        
        data_list = []
        if self.write_byte_widgets:
            for _name_edit, val_edit, _idx_lbl in self.write_byte_widgets:
                val = val_edit.text().strip() or "00"
                data_list.append(int(val, 16) & 0xFF)
        else:
            data_list = list(self.parse_hex_string(self.paste_input.toPlainText()))

        if not data_list:
            QMessageBox.warning(self, "Save Preset", "Enter a payload before saving a preset.")
            return
            
        # For simplicity, we'll use a local json
        presets_file = get_data_path("char_presets_qt.json")
        presets = {}
        if os.path.exists(presets_file):
            with open(presets_file, "r") as f: presets = json.load(f)
        
        char_presets = presets.get(self.char_uuid, [])
        # Update if exists
        updated = False
        for p in char_presets:
            if p["name"] == name:
                p["bytes"] = data_list
                updated = True
                break
        if not updated:
            char_presets.append({"name": name, "bytes": data_list})
            
        presets[self.char_uuid] = char_presets
        with open(presets_file, "w") as f: json.dump(presets, f)
        self.log(f"Preset '{name}' saved.")

    @qasync.asyncSlot()
    async def on_load_preset(self):
        presets_file = get_data_path("char_presets_qt.json")
        if not os.path.exists(presets_file):
            QMessageBox.information(self, "Load Preset", "No presets saved yet.")
            return
            
        with open(presets_file, "r") as f: presets = json.load(f)
        char_presets = presets.get(self.char_uuid, [])
        if not char_presets:
            QMessageBox.information(self, "Load Preset", "No presets for this characteristic.")
            return
            
        names = [p["name"] for p in char_presets]
        name, ok = QInputDialog.getItem(self, "Load Preset", "Select preset:", names, 0, False)
        if not (ok and name): return
        
        for p in char_presets:
            if p["name"] == name:
                data = p["bytes"]
                self.paste_input.setPlainText(" ".join(f"{value:02X}" for value in data))
                self.write_size_input.setText(str(len(data)))
                self.on_create_write_editor()
                for i, (name_edit, val_edit, idx_lbl) in enumerate(self.write_byte_widgets):
                    val_edit.setText(f"{data[i]:02X}")
                self.log(f"Preset '{name}' loaded.")
                break

    def _set_notify_visual_state(self, subscribed: bool):
        if subscribed:
            self.notify_state_lbl.setText("Subscribed")
            self.notify_state_lbl.setObjectName("successText")
            self.notify_state_dot.setStyleSheet(
                "background-color: #22c55e; border: 1px solid #86efac; border-radius: 5px;"
            )
        else:
            self.notify_state_lbl.setText("Not subscribed")
            self.notify_state_lbl.setObjectName("mutedLabel")
            self.notify_state_dot.setStyleSheet(
                "background-color: #4b5f79; border: 1px solid #71849f; border-radius: 5px;"
            )
        self.notify_state_lbl.style().unpolish(self.notify_state_lbl)
        self.notify_state_lbl.style().polish(self.notify_state_lbl)

    @qasync.asyncSlot(bool)
    async def on_notify_toggled(self, checked):
        try:
            if checked:
                await self.client.start_notify(self.char_uuid, self.notification_handler)
                self.notify_btn.setText("Unsubscribe")
                self.notify_btn.setObjectName("dangerButton")
                self.notify_btn.style().unpolish(self.notify_btn)
                self.notify_btn.style().polish(self.notify_btn)
                self._set_notify_visual_state(True)
                self.log(f"[NOTIFY] Subscribed.")
            else:
                await self.client.stop_notify(self.char_uuid)
                self.notify_btn.setText("Subscribe")
                # Emerald Mist for Subscribe to make it very visible
                self.notify_btn.setObjectName("successButton")
                self.notify_btn.style().unpolish(self.notify_btn)
                self.notify_btn.style().polish(self.notify_btn)
                self._set_notify_visual_state(False)
                self.log(f"[NOTIFY] Unsubscribed.")
        except Exception as e:
            self.notify_btn.setChecked(not checked)
            self.log(f"[NOTIFY] Error: {e}")
            import traceback
            traceback.print_exc()

    def notification_handler(self, sender, data):
        # Bleak can invoke this callback outside the Qt GUI thread.
        # Emitting a Qt signal safely queues the payload for GUI processing.
        self.notification_received.emit(bytes(data))

    def _process_notification_payload(self, data: bytes):
        self.last_notify_bytes = bytes(data)
        hex_str = " ".join(f"{byte:02X}" for byte in data)

        self.log_value(f"[NOTIF] {hex_str}")

        for index, (_name_edit, value_label, _index_label) in enumerate(
            self.notify_byte_widgets
        ):
            value_label.setText(f"{data[index]:02X}" if index < len(data) else "--")

        # This updates formulas and sends both raw-byte and calculated samples
        # to the embedded graph.
        self._update_calculations(data)


class BLEBrowserMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SKYLIGHT BLE Browser")
        self.resize(1480, 860)
        self.setMinimumSize(1080, 700)

        self.setup_background()
        self.setStyleSheet(get_stylesheet())

        self.client: Optional[BleakClient] = None
        self.connected_address: Optional[str] = None
        self.char_map = {}
        self._disconnecting = False

        self.central = QWidget()
        self.setCentralWidget(self.central)
        main_layout = QVBoxLayout(self.central)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        main_layout.addWidget(self.splitter)

        self.setup_sidebar()
        self.setup_main_area()
        self.splitter.setSizes([315, 1165])

    def setup_background(self):
        palette = self.palette()
        gradient = QLinearGradient(0, 0, 0, 900)
        gradient.setColorAt(0.0, QColor(THEME["background"]))
        gradient.setColorAt(0.55, QColor("#0d1b2f"))
        gradient.setColorAt(1.0, QColor("#07101d"))
        palette.setBrush(QPalette.ColorRole.Window, QBrush(gradient))
        self.setPalette(palette)

    def setup_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebarFrame")
        sidebar.setMinimumWidth(292)
        sidebar.setMaximumWidth(370)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(17, 17, 17, 14)
        layout.setSpacing(12)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)

        self.logo_lbl = QLabel()
        self.logo_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(script_dir, "BLE_logo.png")

        logo_pixmap = QPixmap(logo_path)

        print("Logo path:", logo_path)
        print("Logo exists:", os.path.exists(logo_path))

        if not logo_pixmap.isNull():
            self.logo_lbl.setPixmap(
                logo_pixmap.scaled(
                    300,  # Logo width
                    120,   # Logo height
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.logo_lbl.setText("SKYLIGHT BLE")
            self.logo_lbl.setStyleSheet(
                "font-size: 15pt; font-weight: 800; color: white;"
            )
            print(f"Logo not found: {logo_path}")

        brand_row.addWidget(self.logo_lbl)
        brand_row.addStretch()

        menu_btn = QPushButton("☰")
        menu_btn.setObjectName("iconButton")
        menu_btn.setToolTip("Application menu")
        brand_row.addWidget(menu_btn)

        layout.addLayout(brand_row)

        self.status_card = QFrame()
        self.status_card.setObjectName("statusCard")
        self.status_card.setProperty("connected", False)
        status_layout = QHBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 13, 14, 13)
        status_layout.setSpacing(10)

        status_text_layout = QVBoxLayout()
        status_text_layout.setSpacing(2)
        status_title = QLabel("CONNECTION")
        status_title.setObjectName("sectionLabel")
        status_line = QHBoxLayout()
        self.status_led = VirtualLED(size=12)
        status_line.addWidget(self.status_led)
        self.connection_status_lbl = QLabel("Disconnected")
        self.connection_status_lbl.setObjectName("cardTitle")
        status_line.addWidget(self.connection_status_lbl)
        status_line.addStretch()
        status_subtitle = QLabel("Bluetooth Low Energy utility")
        status_subtitle.setObjectName("mutedLabel")
        status_text_layout.addWidget(status_title)
        status_text_layout.addLayout(status_line)
        status_text_layout.addWidget(status_subtitle)
        status_layout.addLayout(status_text_layout, 1)

        bluetooth_glyph = QLabel("ᛒ")
        bluetooth_glyph.setObjectName("bluetoothGlyph")
        bluetooth_glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_layout.addWidget(bluetooth_glyph)
        layout.addWidget(self.status_card)

        self.scan_btn = QPushButton("⌁  Scan for devices")
        self.scan_btn.setObjectName("primaryButton")
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.setMinimumHeight(39)
        self.scan_btn.clicked.connect(self.on_scan_clicked)
        layout.addWidget(self.scan_btn)

        list_header = QHBoxLayout()
        list_label = QLabel("DISCOVERED DEVICES")
        list_label.setObjectName("sectionLabel")
        list_header.addWidget(list_label)
        list_header.addStretch()
        self.device_count_lbl = QLabel("0")
        self.device_count_lbl.setObjectName("statusBadge")
        list_header.addWidget(self.device_count_lbl)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.setToolTip("Scan again")
        self.refresh_btn.clicked.connect(self.on_scan_clicked)
        list_header.addWidget(self.refresh_btn)
        layout.addLayout(list_header)

        self.device_list = QTreeWidget()
        self.device_list.setHeaderHidden(True)
        self.device_list.setIndentation(14)
        self.device_list.setUniformRowHeights(True)
        self.device_list.itemSelectionChanged.connect(self.on_device_selection_changed)
        layout.addWidget(self.device_list, 1)

        self.selected_device_lbl = QLabel("Select a device to connect")
        self.selected_device_lbl.setObjectName("mutedLabel")
        self.selected_device_lbl.setWordWrap(True)
        layout.addWidget(self.selected_device_lbl)

        self.connect_btn = QPushButton("⌁  Connect")
        self.connect_btn.setObjectName("successButton")
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self.on_connect_clicked)
        layout.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("×  Disconnect")
        self.disconnect_btn.setObjectName("dangerButton")
        self.disconnect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.disconnect_btn.setEnabled(False)
        self.disconnect_btn.clicked.connect(self.on_disconnect_clicked)
        layout.addWidget(self.disconnect_btn)

        footer_card = QFrame()
        footer_card.setObjectName("selectorCard")
        footer_layout = QHBoxLayout(footer_card)
        footer_layout.setContentsMargins(11, 8, 8, 8)
        footer_text = QLabel("SKYLIGHT BLE • Desktop")
        footer_text.setObjectName("mutedLabel")
        footer_layout.addWidget(footer_text)
        footer_layout.addStretch()
        version = QLabel("v1.1.0")
        version.setObjectName("mutedLabel")
        footer_layout.addWidget(version)
        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("iconButton")
        footer_layout.addWidget(settings_btn)
        layout.addWidget(footer_card)

        self.splitter.addWidget(sidebar)

    def set_connection_status(self, text: str, connected: bool = False):
        self.connection_status_lbl.setText(text)
        self.status_led.set_state(connected)
        self.status_card.setProperty("connected", connected)
        self.status_card.style().unpolish(self.status_card)
        self.status_card.style().polish(self.status_card)

    def on_device_selection_changed(self):
        selected_items = self.device_list.selectedItems()
        if not selected_items:
            self.connect_btn.setEnabled(False)
            self.selected_device_lbl.setText("Select a device to connect")
            return

        item = selected_items[0]
        address = item.data(0, Qt.ItemDataRole.UserRole)
        is_device = item.parent() is not None and bool(address)
        self.connect_btn.setEnabled(is_device and not bool(self.client and self.client.is_connected))

        if is_device:
            self.selected_device_lbl.setText(item.text(0))
        else:
            self.selected_device_lbl.setText("Select an available device")

    def setup_main_area(self):
        main_area = QFrame()
        main_area.setObjectName("mainPanelFrame")
        layout = QVBoxLayout(main_area)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(2, 0, 2, 4)

        title_layout = QVBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        title = QLabel("BLE Workspace")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Discover services, inspect characteristics, and monitor live data.")
        subtitle.setObjectName("pageSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        top_layout.addLayout(title_layout)
        top_layout.addStretch()

        self.workspace_status_lbl = QLabel("●  Ready")
        self.workspace_status_lbl.setObjectName("statusBadge")
        top_layout.addWidget(self.workspace_status_lbl)
        layout.addWidget(top_bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)

        # Do not use Qt's native close buttons. Their appearance depends on
        # the operating-system style and can show as an orange square.
        self.tabs.setTabsClosable(False)

        tab_bar = self.tabs.tabBar()
        tab_bar.setExpanding(False)
        tab_bar.setUsesScrollButtons(True)
        tab_bar.setElideMode(Qt.TextElideMode.ElideRight)

        layout.addWidget(self.tabs, 1)

        welcome_tab = QWidget()
        welcome_layout = QVBoxLayout(welcome_tab)
        welcome_layout.setContentsMargins(22, 22, 22, 22)
        welcome_layout.addStretch()

        welcome_card = QFrame()
        welcome_card.setObjectName("welcomeCard")
        welcome_card.setMaximumWidth(760)
        card_layout = QVBoxLayout(welcome_card)
        card_layout.setContentsMargins(34, 32, 34, 32)
        card_layout.setSpacing(16)

        welcome_title = QLabel("Start a BLE session")
        welcome_title.setObjectName("pageTitle")
        welcome_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(welcome_title)

        welcome_text = QLabel(
            "Scan nearby devices, connect to one, then open any GATT characteristic "
            "to read, write, subscribe, decode, or graph its values."
        )
        welcome_text.setObjectName("pageSubtitle")
        welcome_text.setWordWrap(True)
        welcome_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(welcome_text)

        steps_layout = QHBoxLayout()
        steps_layout.setSpacing(10)
        steps = (
            ("01", "Scan", "Discover nearby BLE devices."),
            ("02", "Connect", "Choose a device from the sidebar."),
            ("03", "Explore", "Open characteristics and inspect data."),
        )
        for number, step_title, description in steps:
            step_card = QFrame()
            step_card.setObjectName("selectorCard")
            step_layout = QVBoxLayout(step_card)
            step_layout.setContentsMargins(14, 14, 14, 14)
            number_label = QLabel(number)
            number_label.setStyleSheet(
                f"color: {THEME['accent_hover']}; font-size: 13pt; font-weight: 700;"
            )
            title_label = QLabel(step_title)
            title_label.setObjectName("cardTitle")
            description_label = QLabel(description)
            description_label.setObjectName("mutedLabel")
            description_label.setWordWrap(True)
            step_layout.addWidget(number_label)
            step_layout.addWidget(title_label)
            step_layout.addWidget(description_label)
            step_layout.addStretch()
            steps_layout.addWidget(step_card)
        card_layout.addLayout(steps_layout)

        welcome_layout.addWidget(welcome_card, 0, Qt.AlignmentFlag.AlignCenter)
        welcome_layout.addStretch()

        self._add_workspace_tab(welcome_tab, "Welcome", closable=False)
        self.splitter.addWidget(main_area)

    def _add_workspace_tab(self, widget: QWidget, title: str, closable: bool = True) -> int:
        """Add a tab with a close button positioned fully inside the tab."""

        index = self.tabs.addTab(widget, title)

        if closable:
            # A wrapper provides an inner right margin. Without it, Qt places
            # the tool button directly against the tab's rounded border.
            close_container = QWidget(self.tabs.tabBar())
            close_container.setObjectName("tabCloseContainer")
            close_container.setFixedSize(30, 28)

            close_layout = QHBoxLayout(close_container)
            close_layout.setContentsMargins(0, 0, 8, 0)
            close_layout.setSpacing(0)

            close_button = QToolButton(close_container)
            close_button.setObjectName("tabCloseButton")
            close_button.setText("×")
            close_button.setToolTip(f"Close {title}")
            close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            close_button.setAutoRaise(False)
            close_button.setFixedSize(18, 18)

            close_layout.addWidget(
                close_button,
                0,
                Qt.AlignmentFlag.AlignCenter,
            )

            close_button.clicked.connect(
                lambda _checked=False, page=widget: self._close_tab_page(page)
            )

            self.tabs.tabBar().setTabButton(
                index,
                QTabBar.ButtonPosition.RightSide,
                close_container,
            )
        else:
            self.tabs.tabBar().setTabButton(
                index,
                QTabBar.ButtonPosition.RightSide,
                None,
            )

        return index

    def _close_tab_page(self, widget: QWidget):
        """Route a custom close-button click through the normal cleanup path."""

        index = self.tabs.indexOf(widget)
        if index <= 0:
            return

        # qasync is already running on the application event loop.
        asyncio.create_task(self.on_tab_close(index))

    @qasync.asyncSlot(int)
    async def on_tab_close(self, index):
        if index == 0:
            return

        widget = self.tabs.widget(index)
        if isinstance(widget, CharacteristicControlWidget):
            # Cleanup notification if active
            if widget.notify_btn.isChecked():
                try:
                    await widget.client.stop_notify(widget.char_uuid)
                except: pass
        
        self.tabs.removeTab(index)
        if widget:
            widget.deleteLater()

    @qasync.asyncSlot()
    async def on_connect_clicked(self):
        selected_items = self.device_list.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        address = item.data(0, Qt.ItemDataRole.UserRole)
        if not address:
            return
            
        await self._connect_and_list(address)

    @qasync.asyncSlot()
    async def on_disconnect_clicked(self):
        if self._disconnecting:
            return

        self._disconnecting = True
        self.disconnect_btn.setText("×  Disconnecting…")
        self.disconnect_btn.setEnabled(False)

        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
        except Exception as error:
            print(f"Disconnect error: {error}")
        finally:
            self.set_connection_status("Disconnected", False)
            self.workspace_status_lbl.setText("●  Ready")
            self.client = None
            self.connected_address = None
            self.disconnect_btn.setText("×  Disconnect")
            self.disconnect_btn.setEnabled(False)
            self.scan_btn.setEnabled(True)

            while self.tabs.count() > 1:
                widget = self.tabs.widget(1)
                self.tabs.removeTab(1)
                if widget:
                    widget.deleteLater()
            self.tabs.setCurrentIndex(0)

            self._disconnecting = False
            self.on_device_selection_changed()

    async def _connect_and_list(self, address: str):
        print(f"Attempting to connect to {address}...")
        self.connect_btn.setText("⌁  Connecting…")
        self.connect_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.set_connection_status("Connecting…", False)
        self.workspace_status_lbl.setText("●  Connecting")
        
        try:
            # 1. Discover GATT services after BLE connection
            self.client = BleakClient(address, disconnected_callback=self.on_bleak_disconnected)
            await self.client.connect(timeout=15.0)
            
            if self.client.is_connected:
                print(f"Successfully connected to {address}")
                self.set_connection_status("Connected", True)
                self.workspace_status_lbl.setText("●  Connected")
                self.connected_address = address
                self.connect_btn.setText("⌁  Connect")
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                
                # Load custom names
                char_prefs = {}
                prefs_path = get_data_path("char_prefs.json")
                if os.path.exists(prefs_path):
                    try:
                        with open(prefs_path, "r", encoding="utf-8") as f: char_prefs = json.load(f)
                    except: pass

                # Access services (already discovered on connect in Bleak)
                services = self.client.services
                
                # 2. Store service UUID, characteristic UUID, handle, and properties
                # We'll store these in a mapping for the dropdown
                self.char_map = {} # uuid -> characteristic object
                
                # Create a clean device overview tab.
                device_tab = QWidget()
                tab_layout = QVBoxLayout(device_tab)
                tab_layout.setContentsMargins(12, 14, 12, 12)
                tab_layout.setSpacing(14)

                info_card = QFrame()
                info_card.setObjectName("heroCard")
                info_layout = QHBoxLayout(info_card)
                info_layout.setContentsMargins(18, 15, 18, 15)

                info_text = QVBoxLayout()
                info_title = QLabel("Connected device")
                info_title.setObjectName("sectionLabel")
                info_address = QLabel(address)
                info_address.setObjectName("monoLabel")
                info_text.addWidget(info_title)
                info_text.addWidget(info_address)
                info_layout.addLayout(info_text)
                info_layout.addStretch()

                characteristic_count = sum(
                    len(service.characteristics) for service in services
                )
                count_badge = QLabel(f"{characteristic_count} characteristics")
                count_badge.setObjectName("statusBadge")
                info_layout.addWidget(count_badge)
                tab_layout.addWidget(info_card)

                selector_card = QFrame()
                selector_card.setObjectName("selectorCard")
                selector_layout = QHBoxLayout(selector_card)
                selector_layout.setContentsMargins(16, 14, 16, 14)
                selector_layout.setSpacing(12)

                selector_label = QLabel("Characteristic")
                selector_label.setObjectName("sectionLabel")
                selector_layout.addWidget(selector_label)

                self.char_combo = QComboBox()
                self.char_combo.setMinimumWidth(420)
                self.char_combo.addItem("Select a characteristic…", None)

                for service in services:
                    for char in service.characteristics:
                        custom_name = char_prefs.get(char.uuid, {}).get("name")
                        if custom_name:
                            display_text = f"{custom_name} ({char.uuid[-4:]})"
                        else:
                            display_text = f"{char.description} ({char.uuid})"

                        self.char_map[char.uuid] = {
                            "obj": char,
                            "service_uuid": service.uuid,
                            "uuid": char.uuid,
                            "handle": char.handle,
                            "properties": char.properties,
                            "custom_name": custom_name,
                        }
                        self.char_combo.addItem(display_text, char.uuid)
                        self.char_combo.setItemData(
                            self.char_combo.count() - 1,
                            display_text,
                            Qt.ItemDataRole.ToolTipRole,
                        )

                self.char_combo.currentIndexChanged.connect(self.on_char_combo_changed)
                selector_layout.addWidget(self.char_combo, 1)
                tab_layout.addWidget(selector_card)

                # Control panel area
                self.char_scroll = QScrollArea()
                self.char_scroll.setWidgetResizable(True)
                tab_layout.addWidget(self.char_scroll, 1)
                
                # Initial placeholder
                placeholder = QLabel("Select a characteristic from the dropdown above to begin.")
                placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
                placeholder.setObjectName("mutedLabel")
                self.char_scroll.setWidget(placeholder)
                
                tab_name = f"Device: {address[-5:]}"
                device_index = self._add_workspace_tab(
                    device_tab,
                    tab_name,
                    closable=True,
                )
                self.tabs.setCurrentIndex(device_index)
            else:
                print(f"Failed to connect to {address} (is_connected is False)")
                self.connect_btn.setText("⌁  Connect")
                self.connect_btn.setEnabled(True)
                self.scan_btn.setEnabled(True)
                self.set_connection_status("Disconnected", False)
                self.workspace_status_lbl.setText("●  Connection failed")
                self.client = None
                
        except Exception as e:
            print(f"Connection error for {address}: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Connection Error", f"Failed to connect to {address}:\n{str(e)}")
            self.connect_btn.setText("⌁  Connect")
            self.connect_btn.setEnabled(True)
            self.scan_btn.setEnabled(True)
            self.set_connection_status("Disconnected", False)
            self.workspace_status_lbl.setText("●  Connection failed")
            self.client = None

    def on_char_combo_changed(self, index):
        uuid = self.char_combo.itemData(index)
        if not uuid:
            return
            
        # Check if tab already exists for this UUID
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, CharacteristicControlWidget) and widget.char_uuid == uuid:
                self.tabs.setCurrentIndex(i)
                return

        char_data = self.char_map.get(uuid)
        if char_data:
            # Create a NEW tab for this characteristic
            # Use pre-stored metadata from the dictionary
            char_widget = CharacteristicControlWidget(
                self.client, 
                char_data["service_uuid"], 
                char_data["uuid"], 
                char_data["handle"], 
                char_data["properties"]
            )
            char_widget.char_renamed.connect(self.on_characteristic_renamed)
            
            if char_data.get("custom_name"):
                tab_name = char_data["custom_name"]
            else:
                tab_name = f"Char: {char_data['uuid'][-4:]}"
            
            new_index = self._add_workspace_tab(
                char_widget,
                tab_name,
                closable=True,
            )
            self.tabs.setCurrentIndex(new_index)
            
            # Reset combo so user can re-select if they close the tab
            self.char_combo.setCurrentIndex(0)

    def on_characteristic_renamed(self, uuid, new_name):
        prefs_path = get_data_path("char_prefs.json")
        char_prefs = {}
        if os.path.exists(prefs_path):
            try:
                with open(prefs_path, "r", encoding="utf-8") as file:
                    char_prefs = json.load(file)
            except (OSError, json.JSONDecodeError):
                pass

        if uuid not in char_prefs:
            char_prefs[uuid] = {}
        char_prefs[uuid]["name"] = new_name

        try:
            with open(prefs_path, "w", encoding="utf-8") as file:
                json.dump(char_prefs, file, indent=2)
        except OSError:
            pass

        # 2. Update local map
        if uuid in self.char_map:
            self.char_map[uuid]["custom_name"] = new_name

        # 3. Update dropdown text
        for i in range(self.char_combo.count()):
            if self.char_combo.itemData(i) == uuid:
                self.char_combo.setItemText(i, f"{new_name} ({uuid[-4:]})")
                break

        # 4. Update tab title
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, CharacteristicControlWidget) and widget.char_uuid == uuid:
                self.tabs.setTabText(i, new_name)
                # Also update the label inside the widget
                widget.char_val_lbl.setText(new_name)
                break

    def on_char_selection_changed(self, tree):
        selected_items = tree.selectedItems()
        if not selected_items:
            return
            
        item = selected_items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        
        # Check if it's a characteristic (it will have properties)
        if hasattr(data, "properties"):
            # Try to get service uuid safely
            svc_uuid = "Unknown"
            if hasattr(data, "service"):
                svc_uuid = data.service.uuid
            elif item.parent():
                parent_data = item.parent().data(0, Qt.ItemDataRole.UserRole)
                if hasattr(parent_data, "uuid"):
                    svc_uuid = parent_data.uuid
                    
            char_widget = CharacteristicControlWidget(
                self.client, 
                svc_uuid, 
                data.uuid, 
                data.handle, 
                data.properties
            )
            # Use the tabs for tree selection too, for consistency
            # but for now let's just fix the crash if it's used
            # Actually, let's just make it open a new tab like the combo
            self.on_char_combo_changed_by_uuid(data.uuid)
        else:
            # It's a service, clear the panel if needed (or ignore)
            pass

    def on_char_combo_changed_by_uuid(self, uuid):
        # Helper to open tab by uuid (used by tree and combo)
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, CharacteristicControlWidget) and widget.char_uuid == uuid:
                self.tabs.setCurrentIndex(i)
                return

        char_data = self.char_map.get(uuid)
        if char_data:
            char_widget = CharacteristicControlWidget(
                self.client, 
                char_data["service_uuid"], 
                char_data["uuid"], 
                char_data["handle"], 
                char_data["properties"]
            )
            tab_name = f"Char: {char_data['uuid'][-4:]}"
            new_index = self._add_workspace_tab(
                char_widget,
                tab_name,
                closable=True,
            )
            self.tabs.setCurrentIndex(new_index)

    def on_bleak_disconnected(self, client):
        print(f"BLE device disconnected: {client.address}")

        def handle_disconnect():
            self.set_connection_status("Disconnected", False)
            if self._disconnecting:
                return
            self.workspace_status_lbl.setText("●  Connection lost")
            self.on_disconnect_clicked()

        QTimer.singleShot(0, handle_disconnect)

    @qasync.asyncSlot()
    async def on_scan_clicked(self):
        self.scan_btn.setText("⌁  Scanning…")
        self.scan_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.device_list.clear()
        self.connect_btn.setEnabled(False)
        self.device_count_lbl.setText("…")
        self.workspace_status_lbl.setText("●  Scanning")
        
        # Create category root nodes
        named_root = QTreeWidgetItem(["Named Devices"])
        unnamed_root = QTreeWidgetItem(["Unnamed Devices"])
        
        self.device_list.addTopLevelItem(named_root)
        self.device_list.addTopLevelItem(unnamed_root)
        
        # Expand them by default
        named_root.setExpanded(True)
        unnamed_root.setExpanded(True)
        
        try:
            # return_adv=True includes device and advertisement details
            discovered_devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
            
            # Convert to list of tuples for sorting
            device_list_data = list(discovered_devices.values())
            
            # Sort: Named devices first, then by RSSI (descending)
            def sort_key(item):
                dev, adv = item
                name = dev.name or adv.local_name
                is_unnamed = 1 if not name else 0
                rssi = adv.rssi if adv.rssi is not None else -100
                return (is_unnamed, -rssi)
                
            device_list_data.sort(key=sort_key)
            self.device_count_lbl.setText(str(len(device_list_data)))
            
            for dev, adv in device_list_data:
                name = dev.name or adv.local_name
                addr = dev.address
                rssi = adv.rssi
                
                display_name = name if name else "Unknown Device"
                item_text = f"{display_name} ({addr}) [{rssi} dBm]"
                
                child_item = QTreeWidgetItem([item_text])
                child_item.setToolTip(0, item_text)
                # Store device address in UserRole so we can use it later to connect
                child_item.setData(0, Qt.ItemDataRole.UserRole, addr)
                
                if name:
                    named_root.addChild(child_item)
                else:
                    unnamed_root.addChild(child_item)
                    
            # Clean up empty roots
            if named_root.childCount() == 0:
                named_root.addChild(QTreeWidgetItem(["No named devices found"]))
            if unnamed_root.childCount() == 0:
                unnamed_root.addChild(QTreeWidgetItem(["No unnamed devices found"]))
                
        except Exception as e:
            self.device_count_lbl.setText("0")
            self.workspace_status_lbl.setText("●  Scan failed")
            QMessageBox.critical(self, "Scan Error", f"An error occurred while scanning:\n{str(e)}")

        finally:
            self.scan_btn.setText("⌁  Scan for devices")
            self.scan_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)
            if self.workspace_status_lbl.text() == "●  Scanning":
                self.workspace_status_lbl.setText("●  Ready")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SKYLIGHT BLE Browser")
    app.setOrganizationName("SKYLIGHT")
    app.setStyle("Fusion")
    
    # Use qasync loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    window = BLEBrowserMainWindow()
    window.show()
    
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()
