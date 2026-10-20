#!/usr/bin/env bash
# Einmalige Einrichtung unter Ubuntu/Kubuntu: Systempakete + virtuelles
# Python-Environment mit allen Abhaengigkeiten.
set -e
cd "$(dirname "$0")"

echo "== Fluneit Linux-Setup =="

echo "-- Systempakete (sudo noetig): python3-tk, venv, pip --"
sudo apt-get install -y python3-tk python3-venv python3-pip

# Optional, fuer sauberere Tray-Integration ausserhalb von KDE:
#   sudo apt-get install -y python3-gi gir1.2-ayatanaappindicator3-0.1

echo "-- Virtuelles Environment (.venv-linux) --"
# --system-site-packages: python3-gi (Tray) aus dem System mitbenutzen
python3 -m venv --system-site-packages .venv-linux
.venv-linux/bin/pip install --upgrade pip
# Pillow explizit ins venv zwingen (System-Pillow hat kein ImageTk)
.venv-linux/bin/pip install --ignore-installed Pillow psutil
.venv-linux/bin/pip install -r requirements.txt

echo
echo "Fertig. Starten mit:  ./fluneit.sh"
echo "Binary bauen mit:     ./build_linux.sh"
