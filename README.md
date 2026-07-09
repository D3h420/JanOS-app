# 🚀 JanOS-app
<img width="1983" height="793" alt="JanOS-app" src="https://github.com/user-attachments/assets/a85d787e-7214-41dd-8386-25f5118f7eee" />

[![Discord](https://img.shields.io/badge/Discord-LAB5-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/57wmJzzR8C)
[![GitHub stars](https://img.shields.io/github/stars/D3h420/JanOS-app?style=for-the-badge)](https://github.com/D3h420/JanOS-app/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/D3h420/JanOS-app?style=for-the-badge)](https://github.com/D3h420/JanOS-app/commits/main)

A terminal-based Python controller for [projectZero (JanOS)](https://github.com/C5Lab/projectZero) firmware over UART ⚡

## 🧭 What This Script Does

`JanOS_app.py` connects to a LAB5 devices through a serial port and provides an interactive menu:

- `Scan`
- `Sniffer`
- `Attacks`
- `Wardrive`
- `SD data`
- `System`
- `SubGHz`

The script sends text commands to projectZero over UART (115200), parses responses, and displays live status output.

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

## 💾 SD Card Files

All paths below are on the JanOS device SD card (under `/sdcard`):

- `/lab/htmls/` - captive portal HTML templates used by Portal / Evil Twin / Rogue AP flows.
- `/lab/htmls/*.html` - templates discovered by `list_sd`.
- `/lab/white.txt` - whitelist BSSIDs (colon or dash separated), respected by Blackout and Sniffer Dog.
- `/lab/wardrives/wXXXX.log` - WiGLE-compatible wardrive logs, auto-incremented.
- `/lab/wigle.txt` - WiGLE API credentials loaded on boot (`api_name:api_token`, one line, no quotes).
- `/lab/wpa-sec.txt` - WPA-SEC API key used for handshake uploads.
- `/lab/portals.txt` - persistent CSV-like log of captive portal form submissions.
- `/lab/ssids.txt` - SSID list used by Beacon Spam file mode (`start_beacon_spam_ssids`).
- `/lab/oui_wifi.bin` - vendor lookup table streamed on demand.
- `/lab/handshakes/*.pcap` - captured WPA handshake files.
- `/lab/pcaps/*.pcap` - packet captures from `start_pcap` (radio/net mode, including MITM workflow).
- `/lab/subghz/` - saved SubGHz radio signals

## 🚧 Status

This project is under active development.  
README reflects the current `JanOS_app.py` behavior.

## ⚠️ Disclaimer

Use only in legal lab environments and only on infrastructure you are authorized to test.
