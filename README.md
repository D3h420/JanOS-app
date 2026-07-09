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
- `System`
- `SubGHz`

The script sends text commands to projectZero over UART (115200), parses responses, and displays live status output.

## ✅ Current Features

- WiFi scanning and selection (`scan_networks`, `show_scan_results`, `select_networks`)
- WiFi inspection (`inspect_network`) and selection reset (`unselect_networks`)
- sniffer mode with results, vendor view, probe request view, probe list, clear results
- live WiFi monitors (`start_sniffer_dog`, `deauth_detector`, `start_ap_locator`, `packet_monitor`, `channel_view`)

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
- Wardrive 2.0 (`start_wardrive_promisc`, trace mode, config, blacklist, anti-surveillance)
- BLE helpers (`scan_bt`, `scan_airtag`)
- `SD data browser`
- `System` (`version`, `board_name`, `sd_status`, `help`, raw command, vendor/display/LED/channel-time controls)
- `SubGHz` workflows: Listen RX, Hunter/analyzer, scanner, weather/TPMS, jammer, Tesla replay, mem/SD signal library, frequency correction
- `htmls`
- `evil twin & portal` (`show_pass`)
- `warlogs`
- `handshakes`
- `pcap` (`/sdcard/lab/pcaps`, `.pcap` files only)
- `subghz` (`subghz_list sd` + `subghz_delete`)

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
- `/lab/subghz/` - saved SubGHz radio signals managed by `subghz_list sd`, `subghz_info`, `subghz_save`, `subghz_delete`, and related SubGHz commands.

SubGHz uses two signal stores:

- `mem` - volatile captures from `subghz_rx` and Hunter mode; clear with `subghz_clear`, promote to SD with `subghz_save`.
- `sd` - persistent `/lab/subghz/*.sub` library; inspect, replay, rename, or delete via the SubGHz and SD data menus.

## 🚧 Status

This project is under active development.  
README reflects the current `JanOS_app.py` behavior.

## ⚠️ Disclaimer

Use only in legal lab environments and only on infrastructure you are authorized to test.
