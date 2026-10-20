# Builds dist\FluneIt.exe (Windows, one file).
# Requirements: python -m pip install -r requirements-dev.txt
#
# Two groups of exclusions:
#  1. The Linux modules and their dependencies (Xlib, pulsectl, dbus-next)
#     are never used on Windows. Without --exclude-module, PyInstaller follows
#     the dead branch anyway and reports missing packages.
#  2. torch and friends: scipy refers to torch/jax/cupy in its optional
#     array-API backends. Nothing of that is loaded at runtime, but PyInstaller
#     would bundle it, which takes long and adds hundreds of MB.
# Do NOT exclude scipy.optimize/interpolate/sparse/stats/spatial/integrate:
# scipy.signal really imports them, and the exe would not start without them.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:TEMP "fluneit_build"

python -m PyInstaller --noconfirm --clean --onefile --noconsole --name FluneIt `
    --icon "$root\assets\icon.ico" `
    --paths "$root" `
    --exclude-module fluneit.linux_audio --exclude-module fluneit.linux_icons `
    --exclude-module fluneit.linux_input --exclude-module fluneit.linux_media `
    --exclude-module fluneit.linux_osd --exclude-module fluneit.linux_tray `
    --exclude-module Xlib --exclude-module pulsectl --exclude-module dbus_next `
    --exclude-module torch --exclude-module tensorflow --exclude-module jax `
    --exclude-module cupy --exclude-module dask --exclude-module sparse `
    --exclude-module librosa --exclude-module matplotlib --exclude-module numba `
    --exclude-module IPython --exclude-module pytest `
    --exclude-module scipy.io --exclude-module scipy.cluster `
    --add-data "$root\assets;assets" `
    --add-data "$root\LICENSE;." `
    --add-data "$root\THIRD-PARTY-NOTICES.md;." `
    --distpath "$root\dist" --workpath $work --specpath $work `
    "$root\fluneit\__main__.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)" }

$exe = Join-Path $root "dist\FluneIt.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
"$hash  FluneIt.exe" | Set-Content -Encoding ascii (Join-Path $root "dist\SHA256SUMS.txt")
Write-Host "Done: $exe"
Write-Host "SHA256: $hash"
