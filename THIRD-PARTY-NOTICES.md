# Third-party notices

FluneIt is licensed under the [MIT License](LICENSE). The Windows download
(`FluneIt.exe`) bundles the components below. Each keeps its own license; the
full texts are on the linked project pages.

| Component | License | Source |
|---|---|---|
| Python runtime | PSF License | https://www.python.org/ |
| Tcl/Tk (tkinter) | Tcl/Tk License (BSD-style) | https://www.tcl.tk/ |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Pillow | MIT-CMU | https://github.com/python-pillow/Pillow |
| pystray | LGPL-3.0 | https://github.com/moses-palmer/pystray |
| six (used by pystray) | MIT | https://github.com/benjaminp/six |
| pycaw | MIT | https://github.com/AndreMiras/pycaw |
| comtypes | MIT | https://github.com/enthought/comtypes |
| PyWinRT (`winrt-*` packages) | MIT | https://github.com/pywinrt/pywinrt |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| NumPy (bundles OpenBLAS) | BSD-3-Clause | https://github.com/numpy/numpy |
| SciPy (bundles OpenBLAS and other libraries, see its LICENSE.txt) | BSD-3-Clause | https://github.com/scipy/scipy |
| python-sounddevice | MIT | https://github.com/spatialaudio/python-sounddevice |
| PortAudio (bundled with python-sounddevice) | MIT-style | https://www.portaudio.com/ |
| CFFI, pycparser | MIT, BSD-3-Clause | https://github.com/python-cffi/cffi |
| PyInstaller bootloader | GPL-2.0-or-later with an exception that allows distributing bundled programs under any license | https://github.com/pyinstaller/pyinstaller |

pystray is licensed under the LGPL-3.0. It is included unmodified as Python
source code inside the executable. You can replace it: install a different
version and build FluneIt yourself (see [CONTRIBUTING.md](CONTRIBUTING.md)).

The experimental Linux version additionally uses pulsectl (MIT),
python-xlib (LGPL-2.1) and dbus-next (MIT); they are not part of the Windows
download.

FluneIt draws with the Windows fonts Segoe UI and Segoe Fluent Icons that are
already installed with Windows. They are not included in the download.
