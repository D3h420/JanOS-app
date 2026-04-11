# 🚀 JanOS App
<img width="1536" height="1024" alt="LAB5-projectZero" src="https://github.com/user-attachments/assets/32b9737d-cada-4d05-b972-6643e36cc2bc" />

[![Discord](https://img.shields.io/badge/Discord-LAB5-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/57wmJzzR8C)
[![GitHub stars](https://img.shields.io/github/stars/D3h420/JanOS-app?style=for-the-badge)](https://github.com/D3h420/JanOS-app/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/D3h420/JanOS-app?style=for-the-badge)](https://github.com/D3h420/JanOS-app/commits/main)

A terminal-based Python controller for [projectZero (JanOS)](https://github.com/C5Lab/projectZero) firmware over UART ⚡
Check our [LAB5 Discord community](https://discord.gg/57wmJzzR8C).

## 🧭 What This Script Does

`JanOS_app.py` connects to a [projectZero (aka JanOS)](https://github.com/C5Lab/projectZero) device through a serial port and provides an interactive menu:

- `Scan`
- `Sniffer`
- `Attacks`
- `Wardrive`
- `SD data`

The script sends text commands to projectZero over UART (115200), parses responses, and displays live status output.

## ✅ Current Features

- WiFi scanning and selection (`scan_networks`, `show_scan_results`, `select_networks`)
- sniffer mode with results and probe request view

🌐 Global WiFi attacks:
- `Deauth`
- `Blackout`
- `WPA3 SAE Overflow`
- `Handshaker`
- `Portal`
- `Evil Twin`
- `Beacon spam` (with `ssids.txt` management)

🕸️ Inside network attacks:
- `ARP` (`list_hosts` + `arp_ban`)
- `MITM` (`start_pcap net`)
- `Stop ALL actions`

🧩 Additional modules:
- `wardrive + GPS setup`
- `SD data browser`
- `htmls`
- `evil twin & portal` (`show_pass`)
- `warlogs`
- `handshakes`
- `pcap` (`/sdcard/lab/pcaps`, `.pcap` files only)

## 📦 Requirements

- Python 3.10+
- `pyserial`
- serial access to your JanOS device (`/dev/ttyUSB0`, `/dev/cu.usbserial-*`, etc.)

Install dependency:

```bash
pip3 install pyserial
```

## ▶️ Usage

```bash
git clone https://github.com/D3h420/JanOS-app.git
cd JanOS-app
python3 JanOS_app.py
```

Or run directly with a device path:

```bash
python3 JanOS_app.py /dev/ttyUSB0
```

## 💾 JanOS SD Card Paths

- `/sdcard/lab/htmls`
- `/sdcard/lab/wardrives`
- `/sdcard/lab/handshakes`
- `/sdcard/lab/pcaps`
- `/sdcard/lab/ssids.txt`

## 🚧 Status

This project is under active development.  
README reflects the current `JanOS_app.py` behavior.

## ⚠️ Disclaimer

Use only in legal lab environments and only on infrastructure you are authorized to test.
