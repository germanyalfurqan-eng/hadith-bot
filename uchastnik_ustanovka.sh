#!/bin/bash
# Установка «Участника β» на машине Oracle. Запускать из /opt/muslimoon после git pull:
#   sudo bash uchastnik_ustanovka.sh
# Делает: папку базы, службу systemd muslimoon-uchastnik (порт 8099), запуск и проверку /health.
# Бот начнёт слать сообщения только после выкатки bot.py с обработчиком group=12 (vykatka.sh).
set -e
cd /opt/muslimoon
mkdir -p /opt/muslimoon/uchastnik
cat > /etc/systemd/system/muslimoon-uchastnik.service <<'UNIT'
[Unit]
Description=Muslimoon: Участник β (агент группового чата)
After=network-online.target muslimoon-mozg.service muslimoon-vektory.service

[Service]
WorkingDirectory=/opt/muslimoon
ExecStart=/usr/bin/python3 /opt/muslimoon/uchastnik.py
Restart=always
RestartSec=10
Nice=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now muslimoon-uchastnik
sleep 3
systemctl is-active muslimoon-uchastnik
curl -s -m 5 http://127.0.0.1:8099/health; echo
