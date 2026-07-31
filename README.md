# Desktop BLE Testing & Visualization Tool

A desktop Bluetooth Low Energy (BLE) application developed using **Python, PyQt6, Bleak, qasync, and Matplotlib** for testing and debugging custom BLE devices.

The application was created because many commonly used BLE mobile applications are not suitable for testing custom characteristics with payloads larger than 20 bytes, while suitable Windows BLE tools with live visualization and flexible payload handling are limited.

## Hardware Tested

- **Texas Instruments CC2652R7 LaunchPad**
- **ESP32 Dev Module / ESP32-WROOM-32**

## Features

- Scan and connect to nearby BLE devices
- Explore GATT services and characteristics
- Read BLE characteristic values
- Write custom hexadecimal payloads
- Subscribe to notifications and indications
- Support larger custom BLE payloads
- Display live received values
- Plot raw bytes and calculated values in real time
- Save and load write presets
- Rename characteristics and individual bytes
- Decode custom packet structures
- Modern dark-themed PyQt6 interface

## Technologies

- Python
- PyQt6
- Bleak
- qasync
- asyncio
- Matplotlib
- Bluetooth Low Energy
- GATT

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
