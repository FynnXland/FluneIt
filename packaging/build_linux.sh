#!/usr/bin/env bash
# Linux (experimental): builds dist/fluneit as a single file with PyInstaller.
# Counterpart of build_exe.ps1. Not part of the official releases.
set -e
cd "$(dirname "$0")/.."

PY=.venv-linux/bin/python
$PY -m pip show pyinstaller >/dev/null 2>&1 || $PY -m pip install pyinstaller

$PY -m PyInstaller --noconfirm --clean \
    --onefile --windowed --name fluneit \
    --paths . \
    --add-data "assets:assets" \
    --add-data "LICENSE:." \
    --add-data "THIRD-PARTY-NOTICES.md:." \
    --hidden-import fluneit.linux_audio \
    --hidden-import fluneit.linux_input \
    --hidden-import fluneit.linux_media \
    --hidden-import fluneit.linux_icons \
    --hidden-import fluneit.linux_osd \
    --hidden-import fluneit.linux_tray \
    --hidden-import PIL._tkinter_finder \
    --workpath "${TMPDIR:-/tmp}/fluneit_build" --specpath "${TMPDIR:-/tmp}/fluneit_build" \
    fluneit/__main__.py

echo
echo "Done: dist/fluneit"
