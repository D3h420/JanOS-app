# JanOS App
![IMG_7409](https://github.com/user-attachments/assets/6d367f35-297a-44ec-8572-a710b3c725ee)

A terminal-based Python controller for JanOS firmware over UART.

## What This Script Does

`JanOS_app.py` connects to a JanOS device (for example ESP32-C5) through a serial port and provides an interactive menu:

- `Scan`
- `Sniffer`
- `Attacks`
- `Wardrive`
- `SD data`

The script sends text commands to JanOS over UART (115200), parses responses, and displays live status output.

## Current Features

- WiFi scanning and selection (`scan_networks`, `show_scan_results`, `select_networks`)
- sniffer mode with results and probe request view

Global WiFi attacks:
- `Deauth`
- `Blackout`
- `WPA3 SAE Overflow`
- `Handshaker`
- `Portal`
- `Evil Twin`
- `Beacon spam` (with `ssids.txt` management)

Inside network attacks:
- `ARP` (`list_hosts` + `arp_ban`)
- `MITM` (`start_pcap net`)
- `Stop ALL actions`

Additional modules:
- wardrive + GPS setup
- SD data browser:
- `htmls`
- `evil twin & portal` (`show_pass`)
- `warlogs`
- `handshakes`
- `pcap` (`/sdcard/lab/pcaps`, `.pcap` files only)

## Requirements

- Python 3.10+
- `pyserial`
- serial access to your JanOS device (`/dev/ttyUSB0`, `/dev/cu.usbserial-*`, etc.)

Install dependency:

```bash
pip3 install pyserial
```

## Usage

```bash
git clone https://github.com/D3h420/JanOS-app.git
cd JanOS-app
python3 JanOS_app.py
```

Or run directly with a device path:

```bash
python3 JanOS_app.py /dev/ttyUSB0
```

## JanOS SD Card Paths

- `/sdcard/lab/htmls`
- `/sdcard/lab/wardrives`
- `/sdcard/lab/handshakes`
- `/sdcard/lab/pcaps`
- `/sdcard/lab/ssids.txt`

## Status

This project is under active development.  
README reflects the current `JanOS_app.py` behavior.

## Disclaimer

Use only in legal lab environments and only on infrastructure you are authorized to test.
