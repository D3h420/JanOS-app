# JanOS na Raspberry Pi Zero 2 W z ekranem Seengreat 1,44″

Ten katalog zawiera interfejs JanOS dla HAT-a Seengreat 128×128 (ST7735S).
Raspberry Pi steruje ekranem po SPI, odczytuje cztery przyciski K1–K4 i
komunikuje się z zewnętrznym ESP32-C5 przez USB UART 115200 8N1. Nie potrzeba
środowiska graficznego ani monitora HDMI. Oryginalny `JanOS_app.py` nadal działa
przez terminal, na przykład po SSH.

## Sprzęt i system

- Raspberry Pi Zero 2 W z przylutowanym złączem GPIO 40 pin oraz HAT
  [Seengreat 1.44inch LCD Display](https://seengreat.com/wiki/68/1-44inch-lcd-display).
- Zasilanie Pi przez gniazdo **PWR IN**. ESP32-C5 podłącz przez adapter USB OTG
  do gniazda **USB** Pi (tego bliżej HDMI). Port USB musi działać jako host,
  więc nie włączaj trybu USB gadget na tym porcie.
- Karta microSD z **Raspberry Pi OS Legacy Lite 32-bit (Bookworm)**. Ten obraz
  jest dostępny w [Raspberry Pi Imager / oficjalnej liście systemów](https://www.raspberrypi.com/software/operating-systems/).
  Seengreat opisuje dla Bookworm sterowanie GPIO przez `lgpio`; Lite wystarcza,
  bo aplikacja sama rysuje po SPI.

W Raspberry Pi Imager ustaw nazwę użytkownika, Wi-Fi i SSH, jeżeli konfigurujesz
Pi bez HDMI/klawiatury. Po pierwszym uruchomieniu zaloguj się przez SSH.

## Montaż i SPI

Załóż HAT na wyłączone Pi. Złącze 40 pin musi być poprawnie ustawione; sygnały
HAT-a pracują z 3,3 V. Włącz SPI:

```bash
sudo raspi-config
```

Wybierz **Interface Options → SPI → Yes**, a następnie uruchom Pi ponownie.
Równoważnie można dopisać `dtparam=spi=on` do
`/boot/firmware/config.txt`. Nie trzeba instalować framebuffer ani overlay
`adafruit-st7735r`: aplikacja wysyła obraz bezpośrednio przez `/dev/spidev0.0`.

Po restarcie sprawdź:

```bash
ls -l /dev/spidev0.0 /dev/gpiochip0
```

## Instalacja

Pakiety z Raspberry Pi OS omijają problem PEP 668 z `sudo pip` na Bookworm:

```bash
sudo apt update
sudo apt install -y git python3-pil python3-spidev python3-lgpio python3-serial fonts-dejavu-core
git clone https://github.com/D3h420/JanOS-app.git
cd JanOS-app
sudo usermod -aG spi,gpio,dialout "$USER"
sudo reboot
```

Po ponownym zalogowaniu sprawdź `groups`. Użytkownik uruchamiający aplikację
powinien mieć dostęp do SPI, GPIO i portu szeregowego. Najpierw sprawdź HAT:

```bash
cd ~/JanOS-app
python3 RPi0-1-44-LCD/check_hat.py
```

Ten test HAT-a nie potrzebuje ESP32. Powinien pokazać czerwony, zielony,
niebieski i biały kwadrat; K1–K4 wypisują rozpoznane klawisze w terminalu,
a K4 kończy test. Następnie podłącz ESP32-C5 i sprawdź port USB:

```bash
ls -l /dev/serial/by-id/ /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Automatyczne wykrywanie wybiera port USB UART o najwyższym dopasowaniu. Jeśli
masz kilka adapterów, podaj stałą ścieżkę z `/dev/serial/by-id/`:

```bash
python3 RPi0-1-44-LCD/app.py --port /dev/serial/by-id/TWOJE_ESP32
```

Przy jednym ESP32-C5 wystarczy:

```bash
python3 RPi0-1-44-LCD/app.py
```

Port można odpiąć i podpiąć ponownie: interfejs pozostaje aktywny i ponawia
łączenie. Zakończenie aplikacji z SSH: `Ctrl+C`.

## Przyciski i obsługa

| Przycisk na HAT | Działanie |
|---|---|
| K1 | Góra / poprzednia pozycja |
| K2 | Dół / następna pozycja |
| K3 | Wybór / potwierdzenie |
| K4 | Wstecz; na ekranie logu zatrzymuje bieżący monitor |

Menu udostępnia skan i wybór Wi-Fi, Sniffer, akcje RF, Wardrive, Bluetooth,
SubGHz (w tym pamięć i bibliotekę SD), podgląd karty SD oraz diagnostykę
urządzenia. Akcje wymagające parametrów można wysłać przez **Komenda UART**.
W edytorze K1/K2 wybierają znak, K3 go dodaje, a K4 otwiera opcje: wyślij,
spacja, usuń znak i wyczyść. Dłuższe wartości wygodniej podać w oryginalnej
aplikacji terminalowej po SSH (`python3 JanOS_app.py`).

Ekran ma tylko 128×128 pikseli, więc lista i log pokazują skrócone fragmenty;
firmware ESP32 nadal przechowuje swoje wyniki. Ekran podaje status połączenia
(zielona/czerwona kropka). Dla monitorów uruchomionych z menu powrót K4 wysyła
`stop` lub `subghz_stop`, aby nie zostawiać ich w tle. Przy dowolnej komendzie
wysłanej z edytora można użyć pozycji **Stop wszystkich** albo **Stop radia**.

## Start automatyczny po bootowaniu (opcjonalnie)

Utwórz `/etc/systemd/system/janos-lcd.service` i **dopasuj** `User`,
`WorkingDirectory` oraz ścieżkę w `ExecStart` do swojej instalacji:

```ini
[Unit]
Description=JanOS Seengreat LCD
After=local-fs.target

[Service]
Type=simple
User=pi
SupplementaryGroups=spi gpio dialout
WorkingDirectory=/home/pi/JanOS-app
ExecStart=/usr/bin/python3 /home/pi/JanOS-app/RPi0-1-44-LCD/app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Następnie:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now janos-lcd.service
systemctl status janos-lcd.service
journalctl -u janos-lcd.service -f
```

Jeżeli chcesz przypiąć konkretny port ESP32, dodaj do `ExecStart` argument
`--port /dev/serial/by-id/...`.

## Sprawdzenie i diagnoza

Uruchom testy logiki i sterownika bez podłączonego HAT-a:

```bash
python3 -m unittest discover -s RPi0-1-44-LCD/tests -v
python3 RPi0-1-44-LCD/test_hardware.py
```

Jeśli ekran pozostaje czarny, sprawdź `/dev/spidev0.0`, grupy użytkownika i
log usługi. Jeśli obraz jest odwrócony lub przesunięty, przekaż np.
`--rotation 180 --x-offset 2 --y-offset 3` przy uruchamianiu aplikacji (także
w `ExecStart` usługi). Jeśli czerwień i błękit są zamienione, dodaj `--rgb-panel`.
Seengreat nie dokumentuje przesunięcia RAM ani orientacji dla wszystkich
rewizji modułu; domyślny profil 2/3 pochodzi ze standardowego panelu 1,44″
ST7735 i wymaga potwierdzenia na fizycznym HAT-cie. Ustawienie 2/3 odpowiada
[profilowi 1,44″ ST7735 w bibliotece Adafruit](https://github.com/adafruit/Adafruit-ST7735-Library/blob/master/Adafruit_ST7735.cpp).

Jeżeli ESP32 jest widoczny jako `/dev/ttyUSB0`/`/dev/ttyACM0`, ale kropka
połączenia nadal jest czerwona, sprawdź dostęp do portu (`groups`, `ls -l`) i
podaj `--port` jawnie. Gdy port w ogóle nie powstaje, sprawdź adapter OTG,
przewód danych oraz zasilanie Pi/ESP32.

Źródła: [dokumentacja Seengreat](https://seengreat.com/wiki/68/1-44inch-lcd-display),
[specyfikacja Zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/),
[dokumentacja konfiguracji Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).
