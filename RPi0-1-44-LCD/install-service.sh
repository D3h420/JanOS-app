#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s) != Linux ]] || ! command -v systemctl >/dev/null; then
    echo "Uruchom ten instalator na Raspberry Pi z systemd." >&2
    exit 1
fi
if [[ $EUID -eq 0 ]]; then
    echo "Uruchom skrypt jako zwykly uzytkownik, bez sudo (skrypt sam go uzyje)." >&2
    exit 1
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
run_user=$(id -un)
if [[ ! $repo_dir =~ ^/[[:alnum:]_./-]+$ ]] || [[ ! $run_user =~ ^[[:alnum:]_-]+$ ]]; then
    echo "Sciezka projektu lub nazwa uzytkownika zawiera znaki wymagajace recznej konfiguracji uslugi." >&2
    exit 1
fi
if [[ ! -f $repo_dir/RPi0-1-44-LCD/splash.png ]]; then
    echo "Brakuje RPi0-1-44-LCD/splash.png w projekcie." >&2
    exit 1
fi

sudo tee /etc/systemd/system/janos-lcd.service >/dev/null <<EOF
[Unit]
Description=JanOS Seengreat LCD
After=local-fs.target

[Service]
Type=simple
User=$run_user
SupplementaryGroups=spi gpio dialout
WorkingDirectory=$repo_dir
ExecStart=/usr/bin/python3 $repo_dir/RPi0-1-44-LCD/app.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable janos-lcd.service
sudo systemctl restart janos-lcd.service
systemctl --no-pager --full status janos-lcd.service
