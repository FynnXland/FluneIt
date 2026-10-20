# Baut Fluneit.exe neu (nach Aenderungen an fluneit.py)
# Voraussetzung: python -m pip install -r requirements.txt pyinstaller
$dir = $PSScriptRoot
Get-Process Fluneit -ErrorAction SilentlyContinue | Stop-Process -Force
# Zwei Gruppen von Ausschluessen:
#  1. Die linux_*-Module und ihre Abhaengigkeiten (Xlib, pulsectl, dbus-next)
#     werden unter Windows nie erreicht - ohne --exclude-module folgt
#     PyInstaller dem toten Zweig trotzdem und meldet fehlende Pakete.
#  2. torch & Co: scipy verweist in seinen Array-API-Backends optional auf
#     torch/jax/cupy. Zur Laufzeit wird davon nichts geladen (geprueft), aber
#     PyInstaller packt es sonst mit ein - das dauert lange und macht die Datei
#     um Hunderte MB groesser.
# NICHT ausschliessen: scipy.optimize/interpolate/sparse/stats/spatial/integrate
# - die zieht scipy.signal wirklich nach (geprueft), ohne sie startet die Exe
# nicht mehr.
python -m PyInstaller --onefile --noconsole --name Fluneit `
    --icon "$dir\icon.ico" `
    --exclude-module linux_audio --exclude-module linux_icons `
    --exclude-module linux_input --exclude-module linux_media `
    --exclude-module linux_osd --exclude-module linux_tray `
    --exclude-module Xlib --exclude-module pulsectl --exclude-module dbus_next `
    --exclude-module torch --exclude-module tensorflow --exclude-module jax `
    --exclude-module cupy --exclude-module dask --exclude-module sparse `
    --exclude-module librosa --exclude-module matplotlib --exclude-module numba `
    --exclude-module IPython --exclude-module pytest `
    --exclude-module scipy.io --exclude-module scipy.cluster `
    --add-data "$dir\assets;assets" --add-data "$dir\icon.ico;." `
    --distpath "$dir\dist" --workpath "$env:LOCALAPPDATA\Temp\fluneit_build" `
    --specpath "$env:LOCALAPPDATA\Temp\fluneit_build" "$dir\fluneit.py"
Move-Item "$dir\dist\Fluneit.exe" "$dir\Fluneit.exe" -Force
Remove-Item "$dir\dist" -Recurse -Force
Write-Host "Fertig: $dir\Fluneit.exe"
Start-Process "$dir\Fluneit.exe"
