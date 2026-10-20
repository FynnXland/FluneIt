#!/usr/bin/env bash
# Baut das eigenstaendige Linux-Binary "fluneit" (PyInstaller, onefile).
# Gegenstueck zu build_exe.ps1 (Windows).
set -e
cd "$(dirname "$0")"

PY=.venv-linux/bin/python
$PY -m pip show pyinstaller >/dev/null 2>&1 || $PY -m pip install pyinstaller

$PY -m PyInstaller \
    --onefile --windowed --name fluneit \
    --add-data "assets:assets" \
    --add-data "icon.ico:." \
    --hidden-import linux_audio \
    --hidden-import linux_input \
    --hidden-import linux_media \
    --hidden-import linux_icons \
    --hidden-import linux_osd \
    --hidden-import linux_tray \
    --hidden-import PIL._tkinter_finder \
    --hidden-import ui \
    --hidden-import obs_bridge \
    fluneit.py

mv -f dist/fluneit ./fluneit-linux
rm -rf build dist fluneit.spec
echo
echo "Fertig: ./fluneit-linux"
