# BLE Browser



**BLE Browser** is a professional desktop application for Bluetooth Low Energy (BLE) testing, debugging, and validation. It is mainly designed for embedded BLE development with **TI CC2652R7** boards and **ESP32 BLE** devices.

The application provides a complete desktop workflow for scanning BLE devices, connecting to targets, inspecting GATT services and characteristics, performing Read / Write / Notify operations, editing byte-level packets, decoding notification payloads, and visualizing live BLE telemetry.

---

## Why I Built This

While working with BLE devices, I faced a major limitation in many existing BLE tools. Most mobile BLE apps on Android and many desktop BLE tools on Windows are useful for basic BLE testing, but they become difficult to use when working with larger structured BLE payloads.

A common issue is handling BLE Read, Write, and Notify operations beyond small payload sizes such as 20 bytes. This becomes a problem when testing embedded devices that use custom GATT profiles, larger command packets, status frames, sensor data, motor-control data, and live telemetry streams.

**BLE Browser was built to solve this issue** by providing a flexible desktop-based BLE debugging tool that supports larger structured payloads and engineering-focused workflows.

---

## Key Features

- BLE device scanning and discovery
- BLE connection and disconnection management
- GATT service and characteristic inspection
- Read, Write, Notify, and Indicate support
- Byte-level packet editor for custom BLE payloads
- Support for larger structured Read / Write / Notify packets
- Custom UUID naming for easier debugging
- Custom byte-field naming for packet interpretation
- Saved write presets for repeatable command testing
- Real-time BLE notification monitoring
- Computed values from raw notification byte streams
- Live BLE telemetry graphing
- Device filtering and characteristic tab management
- Dark modern desktop UI for engineering workflows
- Persistent preferences for UUID names, byte names, and presets

---

## Supported Platforms / Targets

This tool is mainly designed and tested for embedded BLE development using:

- **TI CC2652R7 BLE boards**
- **ESP32 BLE devices**
- Custom embedded BLE peripherals
- Custom GATT profiles
- BLE devices using structured command and status packets

---

## Tech Stack

- **Python**
- **Bleak** for BLE communication
- **CustomTkinter** for the desktop UI
- **Tkinter** for native UI support
- **AsyncIO** for asynchronous BLE operations
- **Matplotlib** for live graph visualization
- **JSON** for saving UUID names, byte names, preferences, and presets

---

## Main Use Cases

BLE Browser is useful for:

- Embedded BLE debugging
- Firmware validation
- Hardware testing
- GATT profile testing
- Custom command packet testing
- Sensor data monitoring
- Motor/control command testing
- Status frame decoding
- Real-time telemetry visualization
- Repeated BLE write command testing using presets

---

## Application Workflow

1. **Scan for BLE devices**
   - Discover nearby BLE peripherals.
   - View available devices from the device list.

2. **Connect to a BLE target**
   - Select a discovered BLE device.
   - Connect directly from the desktop interface.

3. **Inspect GATT services and characteristics**
   - View available services and characteristics.
   - Check characteristic properties such as Read, Write, Notify, and Indicate.

4. **Read characteristic values**
   - Read raw byte data from supported characteristics.
   - View received data in hexadecimal format.

5. **Write custom BLE packets**
   - Create byte-level command packets.
   - Edit each byte manually.
   - Send structured command payloads to BLE devices.

6. **Subscribe to notifications**
   - Monitor real-time data from Notify / Indicate characteristics.
   - Decode notification bytes into meaningful values.

7. **Save and reuse presets**
   - Store commonly used write commands.
   - Reload presets for repeatable BLE testing.

8. **Visualize live telemetry**
   - Plot selected values from BLE notifications.
   - Monitor live sensor or status data in graph form.

---

## Example BLE Data Use Cases

The application can be used to decode and monitor structured BLE data such as:

- Current status
- Error codes
- Temperature values
- Pressure values
- Level values
- Flow values
- Motor control parameters
- PWM values
- BPM values
- Custom command/status bytes

---

## Project Structure

```text
BLE-Browser/
├── graph_live_blink.py      # Main BLE Browser application
├── char_names.json          # Saved UUID display names
├── char_prefs.json          # Saved byte names, computed values, and write presets
└── README.md                # Project documentation
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/ble-browser.git
cd ble-browser
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it:

**Windows**

```bash
venv\Scripts\activate
```

**Linux / macOS**

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install bleak customtkinter matplotlib
```

---

## Running the Application

```bash
python graph_live_blink.py
```

---

## Requirements

- Python 3.9 or later recommended
- Bluetooth adapter with BLE support
- BLE-enabled target device
- Windows, Linux, or macOS with BLE support

> Note: BLE permissions and adapter behavior may vary depending on the operating system.

---

## Highlights

### Larger BLE Payload Workflow

BLE Browser is designed to make it easier to work with larger BLE payloads than typical basic BLE testing tools. This is useful when your embedded device uses structured command packets, multi-byte status frames, or telemetry packets that need to be decoded and monitored.

### Byte-Level Debugging

The byte editor allows you to create, name, edit, and send custom BLE packets. This makes it easier to test firmware commands and validate embedded communication protocols.

### Real-Time Notification Decoding

Notification data can be decoded into computed values such as pressure, flow, level, temperature, status, and error information.

### Live Graphing

The live graph feature helps visualize changing BLE telemetry values over time, making debugging easier during hardware testing.

---

## Future Improvements

Planned or possible future improvements:

- Export logs to CSV
- Save BLE sessions
- Import / export command presets
- Add multi-device support
- Add MTU configuration visibility
- Add packet template support
- Add protocol-specific decoders
- Improve graph customization
- Package as a standalone Windows executable

---

## LinkedIn Project Summary

BLE Browser is a custom desktop BLE debugging tool designed for embedded engineers working with TI CC2652R7 and ESP32 BLE devices. It solves practical limitations found in common BLE mobile and desktop tools by supporting larger structured Read, Write, and Notify payload workflows, byte-level packet editing, real-time notification decoding, saved presets, and live telemetry visualization.

---

**Author:** S.G.M.H.S Dissanayaka
