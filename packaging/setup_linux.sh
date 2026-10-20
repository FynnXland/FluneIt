#!/usr/bin/env bash
# Linux (experimental): installs system packages and a virtual environment
# with all dependencies in .venv-linux at the repository root.
# Tested only by import checks, not on a real Linux desktop yet.
set -e
cd "$(dirname "$0")/.."

echo "== FluneIt Linux setup (experimental) =="
echo "-- System packages (needs sudo): python3-tk, venv, pip --"
sudo apt-get install -y python3-tk python3-venv python3-pip

# Optional, for a cleaner tray icon outside KDE:
#   sudo apt-get install -y python3-gi gir1.2-ayatanaappindicator3-0.1

echo "-- Virtual environment (.venv-linux) --"
# --system-site-packages: reuse python3-gi (tray) from the system
python3 -m venv --system-site-packages .venv-linux
.venv-linux/bin/pip install --upgrade pip
# Force Pillow into the venv (the system Pillow has no ImageTk)
.venv-linux/bin/pip install --ignore-installed Pillow psutil
.venv-linux/bin/pip install -r requirements.txt

echo
echo "Done. Start with:  packaging/fluneit.sh"
