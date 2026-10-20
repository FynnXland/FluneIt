"""Linux-App-Icons: Aufloesung Prozess/Binary -> Icon aus Desktop-Dateien
und Icon-Themes (hicolor/pixmaps/snap). Ersetzt SHGetFileInfoW.

Der Index ueber alle .desktop-Dateien wird einmal aufgebaut und gecacht.
Liefert PIL-Bilder oder None (dann zeichnet die UI ihren Buchstaben-Glyph).
"""

import configparser
import glob
import logging
import os

from PIL import Image

_index = None          # {schluessel: icon-name/pfad}
_img_cache = {}


def _data_dirs():
    dirs = [os.path.expanduser("~/.local/share")]
    dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    dirs += ["/var/lib/flatpak/exports/share",
             os.path.expanduser("~/.local/share/flatpak/exports/share")]
    seen, out = set(), []
    for d in dirs:
        d = d.rstrip("/")
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _build_index():
    idx = {}
    for base in _data_dirs():
        for path in glob.glob(os.path.join(base, "applications", "*.desktop")):
            try:
                cp = configparser.RawConfigParser(interpolation=None, strict=False)
                cp.read(path, encoding="utf-8")
                if not cp.has_section("Desktop Entry"):
                    continue
                icon = cp.get("Desktop Entry", "Icon", fallback="").strip()
                if not icon:
                    continue
                exec_line = cp.get("Desktop Entry", "Exec", fallback="")
                wmclass = cp.get("Desktop Entry", "StartupWMClass", fallback="").strip().lower()
                keys = {os.path.basename(path)[:-8].lower()}
                if wmclass:
                    keys.add(wmclass)
                for tok in exec_line.split():
                    if "=" in tok or tok in ("env", "sh", "-c", "flatpak", "run"):
                        continue
                    if tok.startswith("-"):
                        continue
                    keys.add(os.path.basename(tok).lower())
                    break  # nur das erste echte Kommando
                for k in keys:
                    if k and k not in idx:
                        idx[k] = icon
            except Exception:
                continue
    return idx


def _icon_paths(name):
    if os.path.isabs(name) and os.path.exists(name):
        return [name]
    sizes = ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48", "32x32")
    paths = []
    for base in _data_dirs():
        for size in sizes:
            paths.append(os.path.join(base, "icons", "hicolor", size, "apps", name + ".png"))
        paths.append(os.path.join(base, "pixmaps", name + ".png"))
        paths.append(os.path.join(base, "pixmaps", name + ".xpm"))
    return paths


def _load_named_icon(name):
    for p in _icon_paths(name):
        if os.path.exists(p):
            try:
                return Image.open(p).convert("RGBA")
            except Exception:
                continue
    return None


def _snap_icon(binary):
    p = f"/snap/{binary}/current/meta/gui/icon.png"
    if os.path.exists(p):
        try:
            return Image.open(p).convert("RGBA")
        except Exception:
            pass
    return None


def get_app_icon(exe_path, size=24):
    """Programm-Icon zu einem Binary-Pfad oder Prozessnamen (oder None)."""
    global _index
    if not exe_path:
        return None
    key = os.path.basename(str(exe_path)).lower()
    if key.endswith(".exe"):
        key = key[:-4]
    cache_key = (key, size)
    if cache_key in _img_cache:
        return _img_cache[cache_key]
    if _index is None:
        try:
            _index = _build_index()
        except Exception:
            logging.exception("Desktop-Datei-Index fehlgeschlagen")
            _index = {}

    icon_name = _index.get(key)
    if icon_name is None:
        # Teilstring-Abgleich (chrome -> google-chrome-stable u. ae.)
        for k, v in _index.items():
            if key in k or k in key:
                icon_name = v
                break
    img = _load_named_icon(icon_name) if icon_name else None
    if img is None:
        img = _snap_icon(key)
    if img is not None:
        img = img.resize((size, size), Image.LANCZOS)
    _img_cache[cache_key] = img
    if len(_img_cache) > 128:
        _img_cache.clear()
    return img
