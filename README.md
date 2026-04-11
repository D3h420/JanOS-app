# JanOS App
![IMG_7409](https://github.com/user-attachments/assets/6d367f35-297a-44ec-8572-a710b3c725ee)

Terminalowa aplikacja w Pythonie do sterowania firmware JanOS po UART.

## Co robi skrypt

`JanOS_app.py` łączy się z urządzeniem JanOS (np. ESP32-C5) przez port szeregowy i udostępnia interaktywne menu:

- `Scan`
- `Sniffer`
- `Attacks`
- `Wardrive`
- `SD data`

Skrypt wysyła komendy tekstowe do JanOS po UART (115200), a następnie parsuje odpowiedzi i pokazuje status w czasie rzeczywistym.

## Aktualne funkcje

- skanowanie WiFi i wybór sieci (`scan_networks`, `show_scan_results`, `select_networks`)
- sniffer + podgląd wyników/probe requests
ataki global WiFi:
- `Deauth`
- `Blackout`
- `WPA3 SAE Overflow`
- `Handshaker`
- `Portal`
- `Evil Twin`
- `Beacon spam` (+ zarządzanie `ssids.txt`)
ataki inside network:
- `ARP` (`list_hosts` + `arp_ban`)
- `MITM` (`start_pcap net`)
- `Stop ALL actions`
- wardrive + GPS setup
SD data:
- `htmls`
- `evil twin & portal` (`show_pass`)
- `warlogs`
- `handshakes`
- `pcap` (`/sdcard/lab/pcaps`, tylko pliki `.pcap`)

## Wymagania

- Python 3.10+
- `pyserial`
- dostęp do portu szeregowego urządzenia JanOS (`/dev/ttyUSB0`, `/dev/cu.usbserial-*`, itp.)

Instalacja zależności:

```bash
pip3 install pyserial
```

## Uruchamianie

```bash
git clone https://github.com/D3h420/JanOS-app.git
cd JanOS-app
python3 JanOS_app.py
```

Lub bezpośrednio z portem:

```bash
python3 JanOS_app.py /dev/ttyUSB0
```

## Uwaga o ARP/MITM i SSH

ARP/MITM wymagają aktywnego połączenia WiFi po stronie ESP.

W `INSIDE NETWORK SETUP` są opcje:

- `1) Scan nearby networks and choose target`
- `2) Enter SSID and password manually`
- `3) Skip connect (ESP already connected)`

Dodatkowo skrypt pyta o sync przez `stop` przed setupem ARP/MITM, żeby wyczyścić aktywne akcje na ESP.

Jeżeli pracujesz przez SSH do hosta, ataki sieciowe mogą przerwać sesję (to efekt działania JanOS na sieć, nie lokalnego `nmcli/ifconfig` w skrypcie).

## Struktura danych na SD (JanOS)

- `/sdcard/lab/htmls`
- `/sdcard/lab/wardrives`
- `/sdcard/lab/handshakes`
- `/sdcard/lab/pcaps`
- `/sdcard/lab/ssids.txt`

## Status

Projekt jest aktywnie rozwijany. README odzwierciedla bieżący stan `JanOS_app.py`.

## Disclaimer

Używaj wyłącznie w legalnym środowisku testowym i na infrastrukturze, do której masz uprawnienia.
