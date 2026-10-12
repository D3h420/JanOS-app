# JanOS na Raspberry Pi Zero 2 W z ekranem Seengreat 1,44″

Ten katalog zawiera interfejs JanOS dla HAT-a Seengreat 128×128 (ST7735S).
Raspberry Pi steruje ekranem po SPI, odczytuje pięciopozycyjny joystick i
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
niebieski i biały kwadrat. Każdy ruch joysticka oraz jego wciśnięcie pokazuje
surową nazwę wejścia i akcję na ekranie oraz w terminalu. Zakończ test przez
`Ctrl+C`. Następnie podłącz ESP32-C5 i sprawdź port USB:

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
łączenie. Zakończenie aplikacji uruchomionej ręcznie z SSH: `Ctrl+C`.

Przy każdym starcie aplikacja wyświetla `RPi0-1-44-LCD/splash.png` przez
3 sekundy, a następnie otwiera menu. Aby ustawić inny czas, uruchom ją np.
z `--splash-seconds 5`; `--splash-seconds 0` pomija ekran powitalny. Obraz
jest skalowany do 128×128 pikseli z zachowaniem proporcji. Możesz zastąpić
plik `splash.png` własną grafiką PNG.

## Joystick i obsługa

Trzymaj HAT poziomo: joystick po lewej stronie ekranu, K1–K4 po prawej.
Sterowanie aplikacją odbywa się wyłącznie joystickiem; K1–K4 nie są
odczytywane ani przypisane do akcji. Na ekranie `O` oznacza wciśnięcie
joysticka, a `<` jego ruch w lewo.

| Ruch joysticka | Działanie |
|---|---|
| Góra | Poprzednia pozycja |
| Dół | Następna pozycja |
| Prawo lub wciśnięcie | Wybór / potwierdzenie |
| Lewo | Wstecz; na ekranie logu zatrzymuje bieżący monitor |

Menu udostępnia skan i wybór Wi-Fi, Sniffer, akcje RF, Wardrive, Bluetooth,
SubGHz (w tym pamięć i bibliotekę SD), podgląd karty SD oraz diagnostykę
urządzenia. Akcje wymagające parametrów można wysłać przez **Komenda UART**.
W edytorze góra/dół wybierają znak, prawo lub wciśnięcie go dodaje, a lewo
otwiera opcje: wyślij, spacja, usuń znak i wyczyść. Dłuższe wartości
wygodniej podać w oryginalnej aplikacji terminalowej po SSH
(`python3 JanOS_app.py`).

Ekran ma tylko 128×128 pikseli, więc lista i log pokazują skrócone fragmenty;
firmware ESP32 nadal przechowuje swoje wyniki. Ekran podaje status połączenia
(zielona/czerwona kropka). Dla monitorów uruchomionych z menu ruch w lewo wysyła
`stop` lub `subghz_stop`, aby nie zostawiać ich w tle. Przy dowolnej komendzie
wysłanej z edytora można użyć pozycji **Stop wszystkich** albo **Stop radia**.

## Start automatyczny po bootowaniu

Na Raspberry Pi uruchom instalator **jako zwykły użytkownik, bez `sudo`**.
Skrypt sam użyje `sudo` i poprosi o hasło. Instalator wpisuje aktualną nazwę
użytkownika i ścieżkę projektu do `/etc/systemd/system/janos-lcd.service`,
włącza usługę przy bootowaniu i uruchamia ją od razu:

```bash
cd ~/JanOS-app
bash RPi0-1-44-LCD/install-service.sh
```

Po instalacji możesz rozłączyć SSH: aplikacja uruchomi się sama przy kolejnych
startach Pi, także wtedy, gdy ESP32-C5 zostanie podłączony później. Sprawdzenie
stanu, logów i ponowne uruchomienie po aktualizacji plików:

```bash
systemctl is-enabled janos-lcd.service
systemctl --no-pager status janos-lcd.service
journalctl -u janos-lcd.service -b --no-pager
sudo systemctl restart janos-lcd.service
```

Nie uruchamiaj `check_hat.py` równocześnie z usługą: oba programy używają tego
samego SPI i GPIO. Na czas testu zatrzymaj usługę, a potem uruchom ją ponownie:

```bash
sudo systemctl stop janos-lcd.service
python3 RPi0-1-44-LCD/check_hat.py
sudo systemctl start janos-lcd.service
```

Wyłączenie autostartu i zatrzymanie aplikacji:

```bash
sudo systemctl disable --now janos-lcd.service
```

Jeżeli masz kilka portów szeregowych, możesz dopisać argument
`--port /dev/serial/by-id/...` do `ExecStart` przez
`sudo systemctl edit --full janos-lcd.service`, a potem wykonać
`sudo systemctl daemon-reload` i `sudo systemctl restart janos-lcd.service`.
Ponowne uruchomienie instalatora przywróci domyślny plik usługi.

## Sprawdzenie i diagnoza

Uruchom testy logiki i sterownika bez podłączonego HAT-a:

```bash
python3 -m unittest discover -s RPi0-1-44-LCD/tests -v
python3 RPi0-1-44-LCD/test_hardware.py
```

Jeśli ekran pozostaje czarny, sprawdź `/dev/spidev0.0`, grupy użytkownika i
log usługi. Domyślny obraz jest obrócony o 90° przeciwnie do ruchu wskazówek
zegara względem pierwotnego portu (`--rotation 270`). Jeśli Twoja orientacja
montażu wymaga innego ustawienia, użyj `--rotation 0`, `90` lub `180` (także
w `ExecStart` usługi). Przesunięcie obrazu można skorygować przez `--x-offset`
i `--y-offset`. Jeśli czerwień i błękit są zamienione, dodaj `--rgb-panel`.
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
