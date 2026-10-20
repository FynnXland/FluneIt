"""Fluneit - Benutzeroberflaeche nach dem SoundControl Design System.

Implementiert die claude.ai/design-Vorlagen (Projekt "SoundControl Design System"):
Einstellungsfenster (Allgemein / Steuerung / Mixer / Regeln / Ueber),
Tray-Flyout (Mini-Mixer mit Geraetewechsler) und Erststart-Onboarding.

Alle Farb-/Mass-Token stammen aus tokens/colors.css bzw. tokens/layout.css
des Design-Projekts. Fonts: Segoe UI Variable (negativ = Pixelgroessen in Tk).
"""

import ctypes
import logging
import math
import os
import shutil
import subprocess
import sys
import time
import threading
import tkinter as tk
import tkinter.font as tkfont

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

from PIL import Image, ImageDraw, ImageTk

core = None  # wird von fluneit.init_ui() gesetzt (das Hauptmodul)

# ----------------------------- Design-Token ---------------------------------

class T:
    WINDOW = "#202020"
    CARD = "#2d2d2c"
    HOVER = "#383837"
    PRESSED = "#303030"
    STROKE = "#3f3f3e"
    ACCENT = "#4cc2ff"
    ACCENT_PRESSED = "#3aa0d8"
    ACCENT_FG = "#1a1a1a"
    TRACK = "#8a8a8a"
    TEXT = "#ffffff"
    SEC = "#c5c5c5"
    DIS = "#787878"
    DANGER = "#ff99a4"
    WARN = "#fce100"          # Windows-11-Achtung, fuer Pegel kurz vor 0 dBFS


FONT = "Segoe UI"
FONT_DISPLAY = "Segoe UI"
ICON_FONT = "Segoe Fluent Icons"

# Segoe-Fluent/MDL2-Glyphen fuer die Icon-Namen des Design-Systems
ICONS = {
    "apps": "\uE71D",
    "settings": "", "monitor": "", "info": "",
    "keyboard": "", "mixer": "", "rules": "",
    "search": "", "chevron-down": "", "chevron-right": "",
    "check": "", "add": "", "delete": "", "edit": "",
    "refresh": "", "download": "", "close": "",
    "headphones": "", "mute": "", "mic": "",
    "folder": "", "document": "",
    "speaker-0": "", "speaker-1": "", "speaker-2": "",
}

GLYPH_COLORS = ["#1f7a4d", "#b3541e", "#5b5fc7", "#8a3ab9", "#1f6a7a", "#7a1f45"]

# Unicode-Ersatz fuer die Segoe-Fluent-Glyphen (Linux; DejaVu Sans deckt alle ab)
ICONS_FALLBACK = {
    "apps": "▤",
    "settings": "⚙", "monitor": "▢", "info": "ⓘ",
    "keyboard": "⌨", "mixer": "≡", "rules": "☰",
    "search": "⌕", "chevron-down": "▾", "chevron-right": "▸",
    "check": "✓", "add": "+", "delete": "✕", "edit": "✎",
    "refresh": "↻", "download": "↓", "close": "✕",
    "headphones": "🎧", "mute": "🔇", "mic": "🎤",
    "folder": "📁", "document": "📄",
    "speaker-0": "🔈", "speaker-1": "🔉", "speaker-2": "🔊",
}


def _init_fonts():
    global FONT, FONT_DISPLAY, ICON_FONT
    fams = set(tkfont.families())
    for cand in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI",
                 "Noto Sans", "Ubuntu", "DejaVu Sans"):
        if cand in fams:
            FONT = cand
            break
    for cand in ("Segoe UI Variable Display", "Segoe UI Variable", "Segoe UI",
                 "Noto Sans", "Ubuntu", "DejaVu Sans"):
        if cand in fams:
            FONT_DISPLAY = cand
            break
    for cand in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if cand in fams:
            ICON_FONT = cand
            break
    else:
        # Keine Fluent-Icons (Linux): Unicode-Symbole aus DejaVu Sans
        ICONS.update(ICONS_FALLBACK)
        ICON_FONT = "DejaVu Sans" if "DejaVu Sans" in fams else FONT


def F(px, semibold=False, display=False):
    """Font-Tupel mit Pixelgroesse (negativ = px in Tk)."""
    return (FONT_DISPLAY if display else FONT, -px, "bold" if semibold else "normal")


def IF(px):
    return (ICON_FONT, -px)


def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", None) or core.APP_DIR
    return os.path.join(base, *parts)


_img_cache = {}


def app_icon_image(size):
    key = ("app", size)
    if key not in _img_cache:
        img = Image.open(resource_path("assets", "app-icon-256.png")).resize((size, size), Image.LANCZOS)
        _img_cache[key] = ImageTk.PhotoImage(img)
    return _img_cache[key]


def screen_geometry(win):
    """(x, y, breite, hoehe) des Bildschirms, auf dem Fenster zentriert werden:
    Windows: Hauptbildschirm (Tk-Werte); Linux: Primaermonitor (RandR), damit
    Fenster bei mehreren Monitoren nicht auf der Nahtstelle landen."""
    if not IS_WINDOWS:
        try:
            import linux_osd
            return linux_osd.primary_geometry(win)
        except Exception:
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight()


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    pts = [x0+r,y0, x1-r,y0, x1,y0, x1,y0+r, x1,y1-r, x1,y1,
           x1-r,y1, x0+r,y1, x0,y1, x0,y1-r, x0,y0+r, x0,y0]
    return cv.create_polygon(pts, smooth=True, **kw)


def open_path(path):
    """Datei/Ordner/URL mit der Standard-App oeffnen (startfile bzw. xdg-open).
    Gibt False zurueck, wenn nichts passiert ist - der Aufrufer kann dann eine
    Rueckmeldung zeigen, statt dass der Knopf still ins Leere greift."""
    try:
        if IS_WINDOWS:
            os.startfile(path)
        else:
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if not opener:
                logging.warning("Weder xdg-open noch gio gefunden (xdg-utils "
                                "installieren), %s nicht geoeffnet", path)
                return False
            cmd = [opener, str(path)] if opener.endswith("xdg-open") \
                else [opener, "open", str(path)]
            subprocess.Popen(cmd, start_new_session=True)
        return True
    except Exception:
        logging.exception("Konnte %s nicht oeffnen", path)
        return False


def set_dark_titlebar(win):
    if not IS_WINDOWS:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
    except Exception:
        pass


def _descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += _descendants(c)
    return out


def context_menu(parent, x_root, y_root, items):
    """Kleines Rechtsklick-Menue im Stil des Tray-Menues aus dem Design."""
    pop = tk.Toplevel(parent)
    pop.overrideredirect(True)
    pop.attributes("-topmost", True)
    pop.configure(bg=T.STROKE)
    inner = tk.Frame(pop, bg=T.CARD)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    for label, cb in items:
        lbl = tk.Label(inner, text=label, bg=T.CARD, fg=T.TEXT, font=F(13),
                       anchor="w", padx=14, pady=7, cursor="hand2")
        lbl.pack(fill="x", padx=3, pady=2)
        lbl.bind("<Enter>", lambda e, w=lbl: w.configure(bg=T.HOVER))
        lbl.bind("<Leave>", lambda e, w=lbl: w.configure(bg=T.CARD))
        lbl.bind("<Button-1>", lambda e, c=cb: (pop.destroy(), c()))
    pop.geometry(f"+{x_root}+{y_root}")
    pop.update_idletasks()
    round_corners(pop)
    pop.lift()
    pop.focus_force()
    pop.grab_set()
    pop.bind("<Escape>", lambda e: pop.destroy())
    pop.bind("<ButtonPress-1>", lambda e: pop.destroy()
             if not (0 <= e.x_root - pop.winfo_rootx() <= pop.winfo_width()
                     and 0 <= e.y_root - pop.winfo_rooty() <= pop.winfo_height()) else None)


def round_corners(win):
    if not IS_WINDOWS:
        return  # KDE zeichnet keine DWM-Ecken; Fenster bleiben eckig (kosmetisch)
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(val), 4)
    except Exception:
        pass


# ----------------------------- Basis-Widgets --------------------------------

class Icon(tk.Label):
    def __init__(self, parent, name, size=16, color=T.TEXT, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, text=ICONS.get(name, "?"), font=IF(size), fg=color, bg=bg)


class AppGlyph(tk.Canvas):
    """Generischer App-Platzhalter: farbiges Quadrat (Radius 6) mit Buchstabe."""

    def __init__(self, parent, letter, color=None, size=32, image=None, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        if image is not None:
            self._img = ImageTk.PhotoImage(image.resize((size, size), Image.LANCZOS))
            self.create_image(size // 2, size // 2, image=self._img)
        else:
            color = color or GLYPH_COLORS[sum(map(ord, letter)) % len(GLYPH_COLORS)]
            round_rect(self, 1, 1, size - 1, size - 1, 6, fill=color, outline="")
            self.create_text(size // 2, size // 2, text=letter.upper(), fill="#ffffff",
                             font=F(round(size * 0.45), semibold=True))


class PushButton(tk.Canvas):
    """Button nach components/inputs/Button.jsx (primary/secondary, Hoehe 32, Radius 8)."""

    def __init__(self, parent, text, command=None, icon=None, variant="secondary", bg=None):
        self.text, self.icon, self.variant, self.command = text, icon, variant, command
        self.disabled = False
        f = tkfont.Font(family=FONT, size=-13)
        w = f.measure(text) + 32 + (24 if icon else 0)
        bg = bg or parent["bg"]
        super().__init__(parent, width=w, height=32, bg=bg, highlightthickness=0, cursor="hand2")
        self._bw = w
        self._state = "normal"
        self._draw()
        self.bind("<Enter>", lambda e: self._set("hover"))
        self.bind("<Leave>", lambda e: self._set("normal"))
        self.bind("<Button-1>", lambda e: self._set("pressed"))
        self.bind("<ButtonRelease-1>", self._release)

    def _release(self, e):
        self._set("hover")
        if not self.disabled and self.command and 0 <= e.x <= self._bw and 0 <= e.y <= 32:
            self.command()

    def _set(self, s):
        self._state = s
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.disabled:
            bg, fg, outline = T.CARD, T.DIS, T.STROKE
        elif self.variant == "primary":
            bg = {"pressed": T.ACCENT_PRESSED, "hover": "#47b4ec"}.get(self._state, T.ACCENT)
            fg, outline = T.ACCENT_FG, ""
        else:
            bg = {"pressed": T.PRESSED, "hover": T.HOVER}.get(self._state, T.CARD)
            fg = T.SEC if self._state == "pressed" else T.TEXT
            outline = T.STROKE
        round_rect(self, 1, 1, self._bw - 1, 31, 8, fill=bg, outline=outline)
        cx = self._bw / 2
        if self.icon:
            total = 24 + tkfont.Font(family=FONT, size=-13).measure(self.text)
            ix = cx - total / 2 + 8
            self.create_text(ix, 16, text=ICONS.get(self.icon, "?"), font=IF(16), fill=fg)
            self.create_text(ix + 12 + 4, 16, text=self.text, font=F(13), fill=fg, anchor="w")
        else:
            self.create_text(cx, 16, text=self.text, font=F(13), fill=fg)


class IconButton(tk.Canvas):
    def __init__(self, parent, icon, command=None, size=32, active=False, bg=None, icon_size=14):
        bg = bg or parent["bg"]
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, cursor="hand2")
        self.icon, self.command, self.size, self.active = icon, command, size, active
        self.icon_size = icon_size
        self._hover = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", lambda e: self.command and self.command())

    def _set(self, h):
        self._hover = h
        self._draw()

    def set_icon(self, icon, active=None):
        self.icon = icon
        if active is not None:
            self.active = active
        self._draw()

    def _draw(self):
        self.delete("all")
        if self._hover:
            round_rect(self, 1, 1, self.size - 1, self.size - 1, 4, fill=T.HOVER, outline="")
        color = T.ACCENT if self.active else T.TEXT
        self.create_text(self.size // 2, self.size // 2, text=ICONS.get(self.icon, "?"),
                         font=IF(self.icon_size), fill=color)


class Toggle(tk.Canvas):
    """Windows-11-Schalter nach Toggle.jsx (40x20, Pille, Knopf waechst bei Hover)."""

    def __init__(self, parent, get, on_change, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, width=40, height=20, bg=bg, highlightthickness=0, cursor="hand2")
        self.get, self.on_change = get, on_change
        self.disabled = False
        self._hover = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", self._click)

    def _set(self, h):
        self._hover = h
        self._draw()

    def _click(self, _):
        if not self.disabled:
            self.on_change(not self.get())
            self._draw()

    def refresh(self):
        self._draw()

    def _draw(self):
        self.delete("all")
        checked = self.get()
        if self.disabled:
            border, fill, knob = T.DIS, "", T.DIS
        elif checked:
            border, fill, knob = T.ACCENT, T.ACCENT, T.ACCENT_FG
        else:
            border, fill, knob = T.TRACK, "", T.SEC
        round_rect(self, 1, 1, 39, 19, 9, fill=fill or self["bg"], outline=border)
        k = 14 if (self._hover and not self.disabled) else 12
        cx = 40 - 3 - k / 2 - 1 if checked else 3 + k / 2 + 1
        self.create_oval(cx - k / 2, 10 - k / 2, cx + k / 2, 10 + k / 2, fill=knob, outline="")


class Slider(tk.Canvas):
    """Slider nach Slider.jsx: 4-px-Track, Akzentfuellung, Griff mit #454545-Ring."""

    def __init__(self, parent, get, on_change, width=140, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, width=width, height=22, bg=bg, highlightthickness=0, cursor="hand2")
        self.get, self.on_change, self.w = get, on_change, width
        self.disabled = False
        self._hover = False
        self._drag = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def _set_hover(self, h):
        self._hover = h
        self._draw()

    def _press(self, e):
        if self.disabled:
            return
        self._drag = True
        self._from_x(e.x)

    def _move(self, e):
        if self._drag:
            self._from_x(e.x)

    def _release(self, _):
        self._drag = False
        self._draw()

    def _from_x(self, x):
        pad = 12
        frac = min(1.0, max(0.0, (x - pad) / (self.w - 2 * pad)))
        self.on_change(frac)
        self._draw()

    def refresh(self):
        self._draw()

    def _draw(self):
        self.delete("all")
        frac = min(1.0, max(0.0, self.get()))
        pad = 12
        fill = T.DIS if self.disabled else T.ACCENT
        y = 11
        self.create_line(pad, y, self.w - pad, y, fill=T.TRACK, width=4, capstyle="round")
        if frac > 0:
            self.create_line(pad, y, pad + (self.w - 2 * pad) * frac, y, fill=fill, width=4, capstyle="round")
        kx = pad + (self.w - 2 * pad) * frac
        self.create_oval(kx - 11, y - 11, kx + 11, y + 11, fill="#454545", outline=T.STROKE)
        inner = 10 if self._drag else (16 if self._hover and not self.disabled else 14)
        self.create_oval(kx - inner / 2, y - inner / 2, kx + inner / 2, y + inner / 2, fill=fill, outline="")


class Dropdown(tk.Canvas):
    """Dropdown nach Dropdown.jsx (32 h, Radius 4, Popup mit Haekchen)."""

    def __init__(self, parent, options, get, on_change, width=160, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, width=width, height=32, bg=bg, highlightthickness=0, cursor="hand2")
        self.options, self.get, self.on_change, self.w = options, get, on_change, width
        self.disabled = False
        self._hover = False
        self._draw()
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<Button-1>", self._open)

    def _set(self, h):
        self._hover = h
        self._draw()

    def refresh(self):
        self._draw()

    def _draw(self):
        self.delete("all")
        bg = T.HOVER if (self._hover and not self.disabled) else T.CARD
        fg = T.DIS if self.disabled else T.TEXT
        round_rect(self, 1, 1, self.w - 1, 31, 4, fill=bg, outline=T.STROKE)
        self.create_text(12, 16, text=str(self.get()), font=F(13), fill=fg, anchor="w")
        self.create_text(self.w - 14, 16, text=ICONS["chevron-down"], font=IF(12), fill=T.SEC)

    def _open(self, _):
        if self.disabled:
            return
        pop = tk.Toplevel(self)
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        pop.configure(bg=T.STROKE)
        inner = tk.Frame(pop, bg=T.CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        cur = self.get()

        def choose(opt):
            pop.destroy()
            self.on_change(opt)
            self._draw()

        for opt in self.options:
            row = tk.Frame(inner, bg=T.CARD, cursor="hand2")
            row.pack(fill="x", padx=4, pady=1)
            check = tk.Label(row, text=ICONS["check"] if opt == cur else " ", font=IF(12),
                             fg=T.ACCENT, bg=T.CARD, width=2)
            check.pack(side="left", padx=(6, 2))
            lbl = tk.Label(row, text=opt, font=F(13), fg=T.TEXT, bg=T.CARD, anchor="w")
            lbl.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=5)
            for wdg in (row, check, lbl):
                wdg.bind("<Button-1>", lambda e, o=opt: choose(o))
                wdg.bind("<Enter>", lambda e, r=row: [c.configure(bg=T.HOVER) for c in (r, *r.winfo_children())])
                wdg.bind("<Leave>", lambda e, r=row: [c.configure(bg=T.CARD) for c in (r, *r.winfo_children())])

        pop.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + 36
        pop.geometry(f"+{x}+{y}")
        round_corners(pop)
        pop.grab_set()
        pop.bind("<Button-1>", lambda e: pop.destroy() if e.widget is pop else None)
        pop.bind("<Escape>", lambda e: pop.destroy())
        pop.focus_set()
        # Klick ausserhalb schliesst (grab faengt alles ab)
        pop.bind("<ButtonPress-1>", lambda e: pop.destroy()
                 if not (0 <= e.x_root - pop.winfo_rootx() <= pop.winfo_width()
                         and 0 <= e.y_root - pop.winfo_rooty() <= pop.winfo_height()) else None, add="+")


class Stepper(tk.Frame):
    """Zahleneingabe nach Stepper.jsx: Wert + Verringern/Erhoehen."""

    def __init__(self, parent, get, on_change, vmin, vmax, step=1, suffix="", bg=None):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        self.get, self.on_change = get, on_change
        self.vmin, self.vmax, self.step, self.suffix = vmin, vmax, step, suffix
        self.disabled = False
        self.lbl = tk.Label(self, bg=T.CARD, fg=T.TEXT, font=F(13), width=7, anchor="e")
        self.lbl.pack(side="left", padx=(10, 8), pady=4)
        sep = tk.Frame(self, bg=T.STROKE, width=1)
        sep.pack(side="left", fill="y")
        self.btn_down = IconButton(self, "chevron-down", self._dec, size=30, bg=T.CARD, icon_size=11)
        self.btn_down.pack(side="left")
        self.btn_up = IconButton(self, "add", self._inc, size=30, bg=T.CARD, icon_size=11)
        self.btn_up.pack(side="left")
        self.refresh()

    def _dec(self):
        if not self.disabled:
            self.on_change(max(self.vmin, self.get() - self.step))
            self.refresh()

    def _inc(self):
        if not self.disabled:
            self.on_change(min(self.vmax, self.get() + self.step))
            self.refresh()

    def refresh(self):
        self.lbl.config(text=f"{self.get()}{self.suffix}", fg=T.DIS if self.disabled else T.TEXT)


class EqStrip(tk.Canvas):
    """Grafischer Equalizer: alle Baender als senkrechte Regler in einer
    einzigen Zeichenflaeche - das ist schlanker als sieben Einzelwidgets und
    zeigt zugleich die resultierende Kurve.

    Ziehen aendert die Anhebung, Doppelklick setzt ein Band auf 0 dB,
    Mausrad feinjustiert.
    """

    RANGE = 12.0          # Regelbereich +-12 dB
    PAD_L, PAD_R = 34, 10
    PAD_T, PAD_B = 10, 24

    def __init__(self, parent, bands, on_change, height=180, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, height=height, bg=bg, highlightthickness=0)
        self.bands = bands            # Liste von Band-Dicts (wird veraendert)
        self.on_change = on_change
        self.h = height
        self._drag = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", self._reset_band)
        self.bind("<MouseWheel>", self._wheel)

    # -- Geometrie ---------------------------------------------------------
    def _cols(self):
        w = max(self.winfo_width(), 260)
        inner = w - self.PAD_L - self.PAD_R
        n = max(1, len(self.bands))
        step = inner / n
        return [self.PAD_L + step * (i + 0.5) for i in range(n)], step

    def _y_for_db(self, db):
        top, bot = self.PAD_T, self.h - self.PAD_B
        frac = (self.RANGE - db) / (2 * self.RANGE)
        return top + frac * (bot - top)

    def _db_for_y(self, y):
        top, bot = self.PAD_T, self.h - self.PAD_B
        frac = (y - top) / max(1, bot - top)
        return max(-self.RANGE, min(self.RANGE, self.RANGE - frac * 2 * self.RANGE))

    def _band_at(self, x):
        xs, step = self._cols()
        for i, cx in enumerate(xs):
            if abs(x - cx) <= step / 2:
                return i
        return None

    # -- Interaktion -------------------------------------------------------
    def _press(self, e):
        i = self._band_at(e.x)
        if i is None:
            return
        self._drag = i
        self._set(i, self._db_for_y(e.y))

    def _motion(self, e):
        if self._drag is not None:
            self._set(self._drag, self._db_for_y(e.y))

    def _release(self, e):
        self._drag = None

    def _reset_band(self, e):
        i = self._band_at(e.x)
        if i is not None:
            self._set(i, 0.0)

    def _wheel(self, e):
        i = self._band_at(e.x)
        if i is not None:
            cur = float(self.bands[i].get("db", 0.0))
            self._set(i, cur + (0.5 if e.delta > 0 else -0.5))

    def _set(self, i, db):
        db = max(-self.RANGE, min(self.RANGE, round(db * 2) / 2))
        if abs(float(self.bands[i].get("db", 0.0)) - db) < 1e-6:
            return
        self.bands[i]["db"] = db
        self.redraw()
        if self.on_change:
            self.on_change(self.bands)

    # -- Zeichnen ----------------------------------------------------------
    def _curve_points(self, xs):
        """Frequenzantwort der aktuellen Baender - echt gerechnet, wenn der
        DSP-Kern da ist, sonst als Interpolation der Reglerwerte."""
        w = max(self.winfo_width(), 260)
        x0, x1 = self.PAD_L, w - self.PAD_R
        try:
            import numpy as np

            import fx_dsp
            eq = fx_dsp.Equalizer(48000, 1)
            eq.set_bands(self.bands)
            freqs = np.geomspace(30.0, 18000.0, 96)
            db = eq.response_db(freqs)
            lo = math.log10(30.0)
            span = math.log10(18000.0) - lo
            pts = []
            for f, d in zip(freqs, db):
                fx = x0 + (math.log10(float(f)) - lo) / span * (x1 - x0)
                pts.extend((fx, self._y_for_db(float(d))))
            return pts
        except Exception:
            pts = [x0, self._y_for_db(float(self.bands[0].get("db", 0.0)))]
            for cx, b in zip(xs, self.bands):
                pts.extend((cx, self._y_for_db(float(b.get("db", 0.0)))))
            pts.extend((x1, self._y_for_db(float(self.bands[-1].get("db", 0.0)))))
            return pts

    @staticmethod
    def _hz_label(hz):
        return f"{hz/1000:g}k" if hz >= 1000 else f"{hz:g}"

    def redraw(self):
        self.delete("all")
        w = max(self.winfo_width(), 260)
        xs, step = self._cols()
        top, bot = self.PAD_T, self.h - self.PAD_B
        mid = self._y_for_db(0.0)

        # Hilfslinien und dB-Skala
        for db in (12, 6, 0, -6, -12):
            y = self._y_for_db(db)
            self.create_line(self.PAD_L - 4, y, w - self.PAD_R, y,
                             fill=T.STROKE if db else T.SEC,
                             dash=() if db == 0 else (2, 4))
            self.create_text(self.PAD_L - 8, y, text=f"{db:+d}" if db else "0",
                             font=F(9), fill=T.DIS, anchor="e")

        # Kurve hinter den Reglern
        pts = self._curve_points(xs)
        if len(pts) >= 4:
            self.create_line(*pts, fill=T.ACCENT, width=2, smooth=True)

        # Regler
        for cx, b in zip(xs, self.bands):
            db = float(b.get("db", 0.0))
            y = self._y_for_db(db)
            self.create_line(cx, top, cx, bot, fill=T.STROKE, width=2)
            if abs(db) > 0.05:
                self.create_line(cx, mid, cx, y, fill=T.ACCENT, width=3)
            r = 6
            self.create_oval(cx - r, y - r, cx + r, y + r, fill=T.ACCENT,
                             outline=T.CARD, width=2)
            self.create_text(cx, bot + 8, text=self._hz_label(b.get("hz", 0)),
                             font=F(9), fill=T.SEC)
            if abs(db) > 0.05:
                self.create_text(cx, bot + 18, text=f"{db:+.1f}",
                                 font=F(9), fill=T.ACCENT)


class LevelBar(tk.Canvas):
    """Schmale Pegelanzeige fuer den Effektstatus."""

    def __init__(self, parent, width=90, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, width=width, height=8, bg=bg,
                         highlightthickness=0)
        self.w = width
        self.value = 0.0

    def set(self, value):
        self.value = max(0.0, min(1.0, float(value)))
        self.delete("all")
        round_rect(self, 0, 1, self.w, 7, 3, fill=T.HOVER, outline="")
        if self.value > 0.001:
            # ab -6 dBFS gelb, ab -1 dBFS rot
            col = T.ACCENT
            if self.value > 0.89:
                col = T.DANGER
            elif self.value > 0.5:
                col = T.WARN
            round_rect(self, 0, 1, max(4, self.w * self.value), 7, 3,
                       fill=col, outline="")


class Badge(tk.Canvas):
    def __init__(self, parent, text, variant="neutral", bg=None):
        f = tkfont.Font(family=FONT, size=-12)
        w = f.measure(text) + 18
        bg = bg or parent["bg"]
        super().__init__(parent, width=w, height=20, bg=bg, highlightthickness=0)
        colors = {
            "accent": (T.ACCENT, T.ACCENT_FG, ""),
            "neutral": (T.HOVER, T.SEC, T.STROKE),
            "warning": (bg, T.DANGER, T.DANGER),
        }[variant]
        round_rect(self, 1, 1, w - 1, 19, 9, fill=colors[0], outline=colors[2])
        self.create_text(w / 2, 10, text=text, font=F(12), fill=colors[1])


class Keycap(tk.Frame):
    """Tastenkappe nach Keycap.jsx: 1-px-Rahmen, 3-px-Unterkante."""

    def __init__(self, parent, text, bg=None):
        super().__init__(parent, bg=T.STROKE)
        inner = tk.Label(self, text=text, bg=T.HOVER, fg=T.TEXT, font=F(12, semibold=True), padx=8, pady=4)
        inner.pack(padx=1, pady=(1, 3))


class KeyCombo(tk.Frame):
    def __init__(self, parent, keys, result, dimmed=False, bg=None):
        bg = bg or parent["bg"]
        super().__init__(parent, bg=bg)
        fg = T.DIS if dimmed else T.TEXT
        for i, k in enumerate(keys):
            if i:
                tk.Label(self, text="+", bg=bg, fg=T.SEC, font=F(13)).pack(side="left", padx=4)
            Keycap(self, k).pack(side="left")
        tk.Label(self, text="→", bg=bg, fg=T.SEC, font=F(13)).pack(side="left", padx=8)
        tk.Label(self, text=result, bg=bg, fg=fg, font=F(13)).pack(side="left")


class SettingsCard(tk.Frame):
    """Card-Container, buendelt SettingsRows mit 1-px-Trennern."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        self._first = True

    def divider(self):
        tk.Frame(self, bg=T.STROKE, height=1).pack(fill="x", padx=12)

    def row(self, icon, title, description, control_fn=None, dimmed=False):
        if not self._first:
            self.divider()
        self._first = False
        row = tk.Frame(self, bg=T.CARD)
        row.pack(fill="x", padx=16, pady=10)
        if icon:
            circ = tk.Canvas(row, width=32, height=32, bg=T.CARD, highlightthickness=0)
            circ.create_oval(1, 1, 31, 31, fill=T.HOVER, outline="")
            circ.create_text(16, 16, text=ICONS.get(icon, "?"), font=IF(14),
                             fill=T.DIS if dimmed else T.TEXT)
            circ.pack(side="left", padx=(0, 14))
        ctl = tk.Frame(row, bg=T.CARD)
        ctl.pack(side="right", padx=(12, 0))
        if control_fn:
            control_fn(ctl)
        txt = tk.Frame(row, bg=T.CARD)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=title, bg=T.CARD, fg=T.DIS if dimmed else T.TEXT, font=F(13),
                 anchor="w").pack(fill="x")
        if description:
            # wraplength an die tatsaechlich verfuegbare Breite anpassen. Fest
            # verdrahtete 300 px waren zu breit, sobald rechts ein grosses
            # Bedienelement sitzt - dann wurde der Text rechts abgeschnitten.
            desc = tk.Label(txt, text=description, bg=T.CARD,
                            fg=T.DIS if dimmed else T.SEC, font=F(12),
                            anchor="w", wraplength=200, justify="left")
            desc.pack(fill="x")

            def rewrap(e, lbl=desc):
                w = max(120, e.width)
                if abs(getattr(lbl, "_wrap", 0) - w) > 2:
                    lbl._wrap = w
                    lbl.configure(wraplength=w)

            desc.bind("<Configure>", rewrap)
        return row


class SearchField(tk.Frame):
    def __init__(self, parent, on_change, placeholder="Apps durchsuchen", width=260):
        super().__init__(parent, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        self.on_change, self.placeholder = on_change, placeholder
        tk.Label(self, text=ICONS["search"], font=IF(13), fg=T.SEC, bg=T.CARD).pack(side="left", padx=(10, 4))
        self.var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self.var, bg=T.CARD, fg=T.DIS, bd=0,
                              insertbackground=T.TEXT, font=F(13), width=int(width / 8))
        self.entry.pack(side="left", padx=(0, 10), pady=7)
        self._placeholder = True
        self.var.set(placeholder)
        self.entry.bind("<FocusIn>", self._focus)
        self.entry.bind("<FocusOut>", self._blur)
        self.var.trace_add("write", lambda *a: self._changed())

    def _focus(self, _):
        if self._placeholder:
            self._placeholder = False
            self.var.set("")
            self.entry.config(fg=T.TEXT)

    def _blur(self, _):
        if not self.var.get():
            self._placeholder = True
            self.var.set(self.placeholder)
            self.entry.config(fg=T.DIS)

    def _changed(self):
        if not self._placeholder:
            self.on_change(self.var.get())

    def value(self):
        return "" if self._placeholder else self.var.get()


class EmptyState(tk.Frame):
    def __init__(self, parent, icon, text, action=None):
        super().__init__(parent, bg=T.CARD)
        tk.Label(self, text=ICONS.get(icon, "?"), font=IF(28), fg=T.DIS, bg=T.CARD).pack(pady=(28, 8))
        tk.Label(self, text=text, font=F(13), fg=T.SEC, bg=T.CARD, wraplength=380,
                 justify="center").pack(padx=24)
        if action:
            action(self)
        tk.Frame(self, bg=T.CARD, height=28).pack()


class Toast:
    """'Gespeichert'-Hinweis unten mittig im Fenster."""

    def __init__(self, win):
        self.win = win
        self.frame = None
        self._job = None

    def show(self, text="Gespeichert"):
        if self.frame:
            self.frame.destroy()
        self.frame = tk.Frame(self.win, bg=T.STROKE)
        inner = tk.Frame(self.frame, bg=T.HOVER)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=ICONS["check"], font=IF(12), fg=T.ACCENT, bg=T.HOVER).pack(side="left", padx=(12, 4), pady=5)
        tk.Label(inner, text=text, font=F(12), fg=T.TEXT, bg=T.HOVER).pack(side="left", padx=(0, 12), pady=5)
        self.frame.place(relx=0.5, rely=1.0, y=-16, anchor="s")
        if self._job:
            self.win.after_cancel(self._job)
        self._job = self.win.after(1400, self._hide)

    def _hide(self):
        self._job = None
        if self.frame:
            self.frame.destroy()
            self.frame = None


class Dialog(tk.Toplevel):
    """Modaler Dialog nach feedback/Dialog: Card, Titel, Aktionen rechts."""

    def __init__(self, parent, title, width=360):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg=T.STROKE)
        self.attributes("-topmost", True)
        outer = tk.Frame(self, bg=T.CARD)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(outer, text=title, bg=T.CARD, fg=T.TEXT, font=F(14, semibold=True),
                 anchor="w").pack(fill="x", padx=20, pady=(16, 4))
        self.body = tk.Frame(outer, bg=T.CARD)
        self.body.pack(fill="both", expand=True, padx=20, pady=8)
        self.actions = tk.Frame(outer, bg=T.CARD)
        self.actions.pack(fill="x", padx=20, pady=(4, 16))
        self.update_idletasks()
        w = width
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + 120
        self.geometry(f"{w}x{self.winfo_reqheight()}+{x}+{y}")
        round_corners(self)
        self.transient(parent)
        # overrideredirect-Fenster werden von Windows nicht automatisch nach vorn
        # geholt -> explizit anheben und fokussieren, sonst liegt der (modale)
        # Dialog hinter dem Hauptfenster und schluckt trotzdem alle Klicks.
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def finish(self):
        self.update_idletasks()
        self.geometry(f"{self.winfo_width()}x{self.winfo_reqheight()}")


# ----------------------------- Fenster-Chrome -------------------------------

NAV_ITEMS = [
    ("allgemein", "settings", "Allgemein"),
    ("steuerung", "keyboard", "Steuerung"),
    ("mixer", "mixer", "Mixer"),
    ("effekte", "speaker-2", "Effekte"),
    ("regeln", "rules", "Regeln"),
    ("ueber", "info", "Über"),
]


class NavRail(tk.Frame):
    def __init__(self, parent, on_select):
        super().__init__(parent, bg=T.WINDOW, width=200)
        self.pack_propagate(False)
        self.on_select = on_select
        self.active = None
        self.items = {}
        tk.Frame(self, bg=T.WINDOW, height=8).pack()
        for pid, icon, label in NAV_ITEMS:
            self.items[pid] = self._item(pid, icon, label)

    def _item(self, pid, icon, label):
        holder = tk.Frame(self, bg=T.WINDOW)
        holder.pack(fill="x", padx=8, pady=1)
        cv = tk.Canvas(holder, height=36, bg=T.WINDOW, highlightthickness=0, cursor="hand2")
        cv.pack(fill="x")
        cv.bind("<Button-1>", lambda e: self.on_select(pid))
        cv.bind("<Enter>", lambda e: self._draw(pid, hover=True))
        cv.bind("<Leave>", lambda e: self._draw(pid, hover=False))
        cv._icon, cv._label = icon, label
        return cv

    def select(self, pid):
        self.active = pid
        for p in self.items:
            self._draw(p)

    def _draw(self, pid, hover=False):
        cv = self.items[pid]
        cv.delete("all")
        w = max(cv.winfo_width(), 184)
        active = pid == self.active
        bg = T.CARD if active else (T.HOVER if hover else T.WINDOW)
        if bg != T.WINDOW:
            round_rect(cv, 0, 0, w, 36, 4, fill=bg, outline="")
        if active:
            round_rect(cv, 0, 9, 3, 27, 2, fill=T.ACCENT, outline="")
        cv.create_text(14, 18, text=ICONS[cv._icon], font=IF(15),
                       fill=T.ACCENT if active else T.SEC, anchor="w")
        cv.create_text(40, 18, text=cv._label, font=F(13), fill=T.TEXT, anchor="w")


def page_title(parent, text):
    tk.Label(parent, text=text, bg=T.WINDOW, fg=T.TEXT, font=F(20, semibold=True, display=True),
             anchor="w").pack(fill="x", pady=(4, 20))


def section_title(parent, text):
    tk.Label(parent, text=text, bg=T.WINDOW, fg=T.TEXT, font=F(14, semibold=True),
             anchor="w").pack(fill="x", pady=(20, 8))


class ScrollFrame(tk.Frame):
    def __init__(self, parent, bg=T.WINDOW):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.canvas.pack(fill="both", expand=True)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, e):
        try:
            under = self.winfo_containing(e.x_root, e.y_root)
        except Exception:
            return
        w = under
        while w is not None:
            if w is self:
                self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
                return
            w = getattr(w, "master", None)


# ----------------------------- Einstellungsfenster --------------------------

_settings_window = None


def open_settings(root, page="allgemein"):
    global _settings_window
    if _settings_window is not None and _settings_window.winfo_exists():
        _settings_window.deiconify()
        _settings_window.lift()
        _settings_window.focus_force()
        _settings_window.show_page(page)
        return _settings_window
    _settings_window = SettingsWindow(root, page)
    return _settings_window


class SettingsWindow(tk.Toplevel):
    W, H = 760, 520

    def __init__(self, root, page="allgemein"):
        super().__init__(root)
        self.title("Fluneit")
        self.configure(bg=T.WINDOW)
        self.resizable(False, False)
        sx, sy, sw, sh = screen_geometry(self)
        self.geometry(f"{self.W}x{self.H}+{sx + (sw - self.W) // 2}+{sy + (sh - self.H) // 2 - 30}")
        try:
            if IS_WINDOWS:
                self.iconbitmap(resource_path("icon.ico"))
            else:
                self.iconphoto(True, app_icon_image(64))
        except Exception:
            pass
        set_dark_titlebar(self)

        self.nav = NavRail(self, self.show_page)
        self.nav.pack(side="left", fill="y")
        self.content = tk.Frame(self, bg=T.WINDOW)
        self.content.pack(side="left", fill="both", expand=True, padx=(12, 24), pady=(6, 12))
        self.toast = Toast(self)
        self.show_page(page)

    def saved(self):
        core.save_config()
        core.apply_config()
        self.toast.show("Gespeichert")

    def show_page(self, pid):
        self.nav.select(pid)
        for child in self.content.winfo_children():
            child.destroy()
        sf = ScrollFrame(self.content)
        sf.pack(fill="both", expand=True)
        body = sf.inner
        {"allgemein": self._page_allgemein, "steuerung": self._page_steuerung,
         "mixer": self._page_mixer, "effekte": self._page_effekte,
         "regeln": self._page_regeln,
         
         "ueber": self._page_ueber}[pid](body)

    # --- Seite: Allgemein ---
    def _page_allgemein(self, body):
        page_title(body, "Allgemein")
        cfg = core.CONFIG
        card = SettingsCard(body)
        card.pack(fill="x")

        def autostart_ctl(ctl):
            def change(v):
                # set_autostart meldet jetzt, ob es geklappt hat. Frueher
                # wurde "Gespeichert" auch dann gezeigt, wenn nichts
                # eingerichtet wurde - der Schalter sprang danach zurueck.
                ok = core.set_autostart(v)
                if ok:
                    self.toast.show("Autostart an" if v else "Autostart aus")
                else:
                    self.toast.show("Hat nicht geklappt - siehe Hinweis unten")
                self.show_page("allgemein")
            Toggle(ctl, core.autostart_enabled, change, bg=T.CARD).pack()

        card.row("settings", core.AUTOSTART_LABEL,
                 core.autostart_status()[1], autostart_ctl)

        def design_ctl(ctl):
            Badge(ctl, "Bald verfügbar", bg=T.CARD).pack(side="left", padx=(0, 8))
            dd = Dropdown(ctl, ["Dunkel", "Hell", "System"], lambda: "Dunkel", lambda v: None, width=120, bg=T.CARD)
            dd.disabled = True
            dd.refresh()
            dd.pack(side="left")

        card.row("monitor", "Design", "Farbschema der Oberfläche", design_ctl)

        section_title(body, "Overlay")
        card2 = SettingsCard(body)
        card2.pack(fill="x")
        stepper_holder = {}

        def overlay_ctl(ctl):
            def change(v):
                cfg["overlay_anzeigen"] = v
                self.saved()
                st = stepper_holder.get("st")
                if st:
                    st.disabled = not v
                    st.refresh()
            Toggle(ctl, lambda: cfg.get("overlay_anzeigen", True), change, bg=T.CARD).pack()

        card2.row("speaker-2", "Overlay anzeigen", "Lautstärkeanzeige beim Regeln einblenden", overlay_ctl)

        def dauer_ctl(ctl):
            def change(v):
                cfg["anzeige_dauer_ms"] = v
                self.saved()
            st = Stepper(ctl, lambda: int(cfg.get("anzeige_dauer_ms", 1500)), change,
                         500, 5000, 250, " ms", bg=T.CARD)
            st.disabled = not cfg.get("overlay_anzeigen", True)
            st.refresh()
            st.pack()
            stepper_holder["st"] = st

        card2.row("info", "Anzeigedauer", "Wie lange das Overlay sichtbar bleibt", dauer_ctl)

        if IS_WINDOWS:
            def sysovl_ctl(ctl):
                def change(v):
                    cfg["system_overlay"] = v
                    self.saved()
                Toggle(ctl, lambda: bool(cfg.get("system_overlay", True)), change, bg=T.CARD).pack()

            card2.row("speaker-2", "Windows-Anzeige ersetzen",
                      "Auch bei der System-Lautstärke unser Overlay zeigen statt der Windows-Anzeige", sysovl_ctl)

        def hint_ctl(ctl):
            def change(v):
                cfg["modus_hinweis"] = v
                self.saved()
            Toggle(ctl, lambda: bool(cfg.get("modus_hinweis", True)), change, bg=T.CARD).pack()

        card2.row("keyboard", "Modus-Hinweis beim Halten",
                  "Nach kurzem Halten einer Taste zeigen, was das Rad gerade regelt", hint_ctl)

        foot = tk.Frame(body, bg=T.WINDOW)
        foot.pack(fill="x", pady=(16, 0))
        tk.Label(foot, text=ICONS["info"], font=IF(14), fg=T.SEC, bg=T.WINDOW).pack(side="left")
        tk.Label(foot, text=" Erweiterte Optionen: ", font=F(12), fg=T.SEC, bg=T.WINDOW).pack(side="left")
        link = tk.Label(foot, text="Konfigurationsdatei öffnen", font=F(12), fg=T.ACCENT,
                        bg=T.WINDOW, cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: open_path(core.CONFIG_FILE))

    # --- Seite: Steuerung ---
    def _page_steuerung(self, body):
        page_title(body, "Steuerung")
        cfg = core.CONFIG
        NAMES = {"shift": "Shift", "strg": "Strg", "ctrl": "Strg", "alt": "Alt"}

        def mod_label(spec):
            parts = [x for x in str(spec).lower().replace(" ", "").split("+") if x]
            return "+".join(NAMES.get(x, x.capitalize()) for x in parts) if parts else "Aus"

        def mod_keys(spec):
            return [NAMES.get(x, x.capitalize())
                    for x in str(spec).lower().replace(" ", "").split("+") if x]

        card = SettingsCard(body)
        card.pack(fill="x")

        def mod_ctl(ctl):
            def change(v):
                cfg["modifier"] = v.lower()
                self.saved()
                self.show_page("steuerung")
            Dropdown(ctl, ["Shift", "Strg", "Alt"],
                     lambda: mod_label(cfg.get("modifier", "strg")), change,
                     width=120, bg=T.CARD).pack()

        card.row("keyboard", "App-Lautst\u00e4rke",
                 "Taste, die mit dem Rad die App im Vordergrund regelt", mod_ctl)

        def step_ctl(ctl):
            def change(v):
                cfg["schrittweite_prozent"] = v
                self.saved()
            Stepper(ctl, lambda: int(cfg.get("schrittweite_prozent", 5)), change,
                    1, 20, 1, " %", bg=T.CARD).pack()

        card.row("mixer", "Schrittweite pro Rad-Tick",
                 "\u00c4nderung der Lautst\u00e4rke je Raster des Rads", step_ctl)

        def mic_ctl(ctl):
            def change(v):
                cfg["mikrofon_modifier"] = "" if v == "Aus" else v.lower()
                self.saved()
                self.show_page("steuerung")
            Dropdown(ctl, ["Shift", "Strg", "Alt", "Strg+Shift", "Aus"],
                     lambda: mod_label(cfg.get("mikrofon_modifier", "")), change,
                     width=140, bg=T.CARD).pack()

        card.row("mic", "Mikrofon",
                 "Tastenkombination f\u00fcr die Mikrofon-Lautst\u00e4rke", mic_ctl)

        def round_ctl(ctl):
            val_map = {"Aus": 0, "5 %": 5, "10 %": 10}

            def change(v):
                cfg["runden_auf"] = val_map[v]
                self.saved()

            inv = {0: "Aus", 5: "5 %", 10: "10 %"}
            n = int(cfg.get("runden_auf", 0))
            Dropdown(ctl, ["Aus", "5 %", "10 %"],
                     lambda: inv.get(int(cfg.get("runden_auf", 0)), f"{n} %"), change,
                     width=120, bg=T.CARD).pack()

        card.row("check", "Auf runde Werte einrasten",
                 "Krumme Werte wie 12 % rasten kurz danach auf 10 % ein", round_ctl)

        def media_ctl(ctl):
            def change(v):
                if v == "Aus":
                    cfg["medien_steuerung"] = False
                else:
                    cfg["medien_steuerung"] = True
                    cfg["medien_modifier"] = v.lower()
                self.saved()
                self.show_page("steuerung")

            def cur():
                if not cfg.get("medien_steuerung", False):
                    return "Aus"
                return mod_label(cfg.get("medien_modifier", "shift"))

            Dropdown(ctl, ["Shift", "Strg", "Alt", "Aus"], cur, change,
                     width=120, bg=T.CARD).pack()

        card.row("mixer", "Medien-Steuerung",
                 "Rad wechselt den Titel, Stumm-Taste pausiert (+ Alt + Rad spult)", media_ctl)

        def bg_ctl(ctl):
            def change(v):
                cfg["hintergrund_modifier"] = "" if v == "Aus" else v.lower()
                self.saved()
                self.show_page("steuerung")
            Dropdown(ctl, ["Shift", "Strg", "Alt", "Aus"],
                     lambda: mod_label(cfg.get("hintergrund_modifier", "")), change,
                     width=120, bg=T.CARD).pack()

        card.row("speaker-2", "Musik-App regeln",
                 "Modifier f\u00fcr die App, die gerade Musik/Medien wiedergibt \u2013 auch ohne Fokus", bg_ctl)

        # --- Belegungs\u00fcbersicht (generisch aus der Config) ---
        section_title(body, "Belegung")
        card2 = SettingsCard(body)
        card2.pack(fill="x")
        inner = tk.Frame(card2, bg=T.CARD)
        inner.pack(fill="x", padx=16, pady=14)

        def combo(keys, result):
            KeyCombo(inner, keys, result, bg=T.CARD).pack(anchor="w", pady=(0, 12))

        app_keys = mod_keys(cfg.get("modifier", "strg"))
        combo(app_keys + ["Rad"], "App-Lautst\u00e4rke \u00e4ndern")
        combo(app_keys + ["Stumm"], "App stumm schalten")

        mic = cfg.get("mikrofon_modifier", "")
        if mic:
            combo(mod_keys(mic) + ["Rad"], "Mikrofon-Lautst\u00e4rke")

        if cfg.get("medien_steuerung", False):
            mk = mod_keys(cfg.get("medien_modifier", "shift"))
            combo(mk + ["Rad"], "Titel wechseln")
            combo(mk + ["Stumm"], "Wiedergabe / Pause")
            combo(mk + ["Alt", "Rad"], "Im Titel spulen")

        comm = cfg.get("kommunikation_modifier", "")
        if comm and cfg.get("kommunikations_apps"):
            combo(mod_keys(comm) + ["Rad"], "Kommunikations-Apps (Discord, TeamSpeak …)")

        bg = cfg.get("hintergrund_modifier", "")
        if bg:
            KeyCombo(inner, mod_keys(bg) + ["Rad"], "Musik-App regeln (← → wechselt die App)",
                     bg=T.CARD).pack(anchor="w")

    # --- Seite: Mixer ---
    def _page_mixer(self, body):
        page_title(body, "Mixer")
        state = {"q": ""}

        list_holder = tk.Frame(body, bg=T.WINDOW)

        def refresh(q=""):
            state["q"] = q.lower()
            for c in list_holder.winfo_children():
                c.destroy()
            self._build_mixer_rows(list_holder, state["q"])

        SearchField(body, refresh).pack(anchor="w")
        list_holder.pack(fill="x", pady=(16, 0))
        refresh()

    def _build_mixer_rows(self, holder, q):
        # System-Zeile (Master)
        sys_card = tk.Frame(holder, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        sys_card.pack(fill="x")
        try:
            ep = core._default_endpoint(0, 1)
            self._app_row(sys_card, "System",
                          lambda: ep.GetMasterVolumeLevelScalar(),
                          lambda f: ep.SetMasterVolumeLevelScalar(f, None),
                          lambda: bool(ep.GetMute()),
                          lambda m: ep.SetMute(m, None),
                          glyph_icon="speaker-2", badge="Master")
        except Exception:
            logging.exception("Master-Lautstaerke nicht verfuegbar")

        card = tk.Frame(holder, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        card.pack(fill="x", pady=(8, 0))
        hidden_apps = list(core.CONFIG.get("ausgeblendete_apps", []))
        apps = core.collect_audio_apps()
        shown = {k: v for k, v in apps.items()
                 if q in v["name"].lower() and k not in set(hidden_apps)}
        if not shown:
            EmptyState(card, "speaker-0",
                       "Keine App gefunden." if q else "Gerade spielt nichts Audio ab.").pack(fill="x")
        first = True
        for key in sorted(shown, key=lambda x: shown[x]["name"].lower()):
            e = shown[key]
            if not first:
                tk.Frame(card, bg=T.STROKE, height=1).pack(fill="x", padx=8)
            first = False
            vols = [s.SimpleAudioVolume for s in e["sessions"]]

            def mk(vols):
                return (lambda: self._safe(lambda: vols[0].GetMasterVolume(), 0.0),
                        lambda f: [self._safe(lambda v=v: v.SetMasterVolume(f, None)) for v in vols],
                        lambda: self._safe(lambda: bool(vols[0].GetMute()), False),
                        lambda m: [self._safe(lambda v=v: v.SetMute(m, None)) for v in vols])

            def mk_hide(key=key):
                def hide():
                    lst = core.CONFIG.setdefault("ausgeblendete_apps", [])
                    if key not in lst:
                        lst.append(key)
                    self.saved()
                    self.show_page("mixer")
                return hide

            g, s, gm, sm = mk(vols)
            icon_img = core.get_app_icon(e["exe"], 32)
            self._app_row(card, e["name"], g, s, gm, sm, icon_img=icon_img, on_hide=mk_hide())

        self._hidden_section(holder)

    def _hidden_section(self, holder):
        """Ausgeblendete Apps/Geraete auflisten und wieder einblendbar machen."""
        hidden_apps = list(core.CONFIG.get("ausgeblendete_apps", []))
        hidden_devs = list(core.CONFIG.get("ausgeblendete_geraete", []))
        if not hidden_apps and not hidden_devs:
            return
        tk.Label(holder, text="Ausgeblendet", bg=T.WINDOW, fg=T.TEXT,
                 font=F(14, semibold=True), anchor="w").pack(fill="x", pady=(20, 8))
        card = tk.Frame(holder, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        card.pack(fill="x")
        first = True

        def entry(name, badge_text, on_show, glyph_letter=None, glyph_icon=None):
            nonlocal first
            if not first:
                tk.Frame(card, bg=T.STROKE, height=1).pack(fill="x", padx=8)
            first = False
            row = tk.Frame(card, bg=T.CARD)
            row.pack(fill="x", padx=12, pady=8)
            if glyph_icon:
                tk.Label(row, text=ICONS[glyph_icon], font=IF(16), fg=T.SEC, bg=T.CARD,
                         width=2).pack(side="left", padx=(2, 10))
            else:
                AppGlyph(row, glyph_letter, size=32, bg=T.CARD).pack(side="left", padx=(0, 12))
            PushButton(row, "Einblenden", command=on_show, bg=T.CARD).pack(side="right")
            Badge(row, badge_text, bg=T.CARD).pack(side="right", padx=10)
            tk.Label(row, text=name, font=F(13), fg=T.SEC, bg=T.CARD,
                     anchor="w").pack(side="left", fill="x", expand=True)

        for key in hidden_apps:
            def mk_show(key=key):
                def show():
                    core.CONFIG["ausgeblendete_apps"] = [
                        a for a in core.CONFIG.get("ausgeblendete_apps", []) if a != key]
                    self.saved()
                    self.show_page("mixer")
                return show
            name = core.pretty_name(key)
            entry(name, "App", mk_show(), glyph_letter=name[0])

        for dev in hidden_devs:
            def mk_show_dev(dev=dev):
                def show():
                    core.CONFIG["ausgeblendete_geraete"] = [
                        d for d in core.CONFIG.get("ausgeblendete_geraete", [])
                        if d.get("id") != dev.get("id")]
                    self.saved()
                    self.show_page("mixer")
                return show
            entry(dev.get("name", "Audiogerät"), "Gerät", mk_show_dev(), glyph_icon="speaker-2")

    @staticmethod
    def _safe(fn, default=None):
        try:
            return fn()
        except Exception:
            return default

    def _app_row(self, card, name, get_vol, set_vol, get_mute, set_mute,
                 icon_img=None, glyph_icon=None, badge=None, on_hide=None):
        row = tk.Frame(card, bg=T.CARD)
        row.pack(fill="x", padx=12, pady=8)
        if glyph_icon:
            tk.Label(row, text=ICONS[glyph_icon], font=IF(18), fg=T.TEXT, bg=T.CARD,
                     width=2).pack(side="left", padx=(2, 10))
        else:
            AppGlyph(row, name[0], size=32, image=icon_img, bg=T.CARD).pack(side="left", padx=(0, 12))
        name_holder = tk.Frame(row, bg=T.CARD, height=32)
        name_holder.pack(side="left", fill="x", expand=True)
        name_holder.pack_propagate(False)
        tk.Label(name_holder, text=name, font=F(13), fg=T.TEXT, bg=T.CARD, anchor="w").pack(side="left")
        if badge:
            Badge(name_holder, badge, bg=T.CARD).pack(side="left", padx=6)

        mute_btn = IconButton(row, "speaker-2", size=32, bg=T.CARD, icon_size=15)
        val = tk.Label(row, font=F(13), fg=T.TEXT, bg=T.CARD, width=5, anchor="e")
        slider = Slider(row, get_vol, lambda f: (set_vol(f), val.config(text=f"{round(f*100)}%")),
                        width=230, bg=T.CARD)
        mute_btn.pack(side="right", padx=(6, 0))
        val.pack(side="right", padx=(8, 2))
        slider.pack(side="right")

        def sync():
            muted = get_mute()
            v = get_vol() or 0
            val.config(text=f"{round(v*100)}%", fg=T.DIS if muted else T.TEXT)
            slider.disabled = muted
            slider.refresh()
            icon = "mute" if muted else ("speaker-0" if v == 0 else "speaker-1" if v < 0.5 else "speaker-2")
            mute_btn.set_icon(icon, active=muted)

        mute_btn.command = lambda: (set_mute(not get_mute()), sync())
        sync()
        if on_hide:
            for w in _descendants(row):
                w.bind("<Button-3>", lambda ev: context_menu(
                    self, ev.x_root, ev.y_root, [("Im Mixer ausblenden", on_hide)]))

    # --- Seite: Effekte ---
    def _page_effekte(self, body):
        page_title(body, "Effekte")
        cfg = core.CONFIG

        if not core.fx_available():
            card = SettingsCard(body)
            card.pack(fill="x")
            card.row("info", "Effekte nicht verfügbar",
                     "Dafür fehlen numpy, scipy und sounddevice. "
                     "Installieren mit:  pip install -r requirements.txt")
            return

        import fx_dsp
        import fx_engine

        fx = cfg.setdefault("effekte", {})
        if not fx.get("baender"):
            fx["baender"] = fx_dsp.default_bands()

        def save_and_apply():
            self.saved()
            core.fx_apply_params()

        # -- Hauptschalter ------------------------------------------------
        st = core.fx_status()
        card = SettingsCard(body)
        card.pack(fill="x")

        def master_ctl(ctl):
            def change(v):
                if v:
                    ok, why = core.fx_start()
                    self.toast.show("Effekte an" if ok
                                    else (why[:60] or "Start fehlgeschlagen"))
                else:
                    core.fx_stop()
                    self.toast.show("Effekte aus")
                self.show_page("effekte")
            Toggle(ctl, core.fx_running, change, bg=T.CARD).pack()

        running = bool(st.get("laeuft"))
        card.row("speaker-2", "Effekte aktiv",
                 (f"Läuft – {st.get('quelle', '')} → {st.get('ziel', '')}"
                  if running else
                  "Legt Equalizer und Effekte auf alles, was der PC ausgibt"),
                 master_ctl)

        if running:
            status_lbl = {}

            def status_ctl(ctl):
                bar = LevelBar(ctl, width=80, bg=T.CARD)
                bar.pack()
                bar.set(st.get("pegel_out", 0.0))
                status_lbl["bar"] = bar

            row = card.row("info", "Status", "…", status_ctl)
            # Zeile suchen, deren Beschreibungstext wir laufend ersetzen
            for w in _descendants(row):
                if isinstance(w, tk.Label) and w.cget("text") == "…":
                    status_lbl["txt"] = w
                    break

            def tick():
                bar, txt = status_lbl.get("bar"), status_lbl.get("txt")
                if bar is None or not bar.winfo_exists():
                    return                      # Seite wurde verlassen
                s = core.fx_status()
                if not s.get("laeuft"):
                    self.show_page("effekte")   # Engine ist ausgefallen
                    return
                bar.set(s.get("pegel_out", 0.0))
                if txt is not None and txt.winfo_exists():
                    txt.config(text=f"≈{s.get('latenz_ms', 0):.0f} ms Verzögerung · "
                                    f"{s.get('last', 0):.0f} % Rechenlast · "
                                    f"{s.get('aussetzer', 0)} Aussetzer · "
                                    f"{s.get('abtastrate', 0)} Hz")
                bar.after(250, tick)

            tick()
        elif st.get("fehler"):
            card.row("close", "Letzter Fehler", str(st["fehler"])[:120])

        # -- Klang --------------------------------------------------------
        section_title(body, "Klang")

        pcard = SettingsCard(body)
        pcard.pack(fill="x")
        preset_names = {k: v["name"] for k, v in fx_dsp.PRESETS.items()}
        rev = {v: k for k, v in preset_names.items()}

        def preset_ctl(ctl):
            def change(label):
                key = rev.get(label)
                if not key:
                    return
                neu = fx_dsp.preset_params(key)
                # Preset-Kurve auf die sieben Regler abbilden: so zeigt die
                # Anzeige, was das Preset tut, und man kann von dort
                # weiterdrehen, statt ein fremdes Bandraster vorzufinden.
                neu["baender"] = fx_dsp.bands_to_ui(neu.get("baender"))
                cfg["effekte"] = neu
                save_and_apply()
                self.show_page("effekte")
            cur = preset_names.get(fx.get("voreinstellung", "neutral"), "Neutral")
            Dropdown(ctl, list(preset_names.values()), lambda: cur, change,
                     width=172, bg=T.CARD).pack()

        key_now = fx.get("voreinstellung", "")
        pcard.row("apps", "Voreinstellung",
                  fx_dsp.PRESETS.get(key_now, {}).get(
                      "beschreibung", "Fertige Klangprofile als Startpunkt"),
                  preset_ctl)

        # Equalizer-Streifen
        eqcard = tk.Frame(body, bg=T.CARD, highlightbackground=T.STROKE,
                          highlightthickness=1)
        eqcard.pack(fill="x", pady=(8, 0))
        head = tk.Frame(eqcard, bg=T.CARD)
        head.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(head, text="Equalizer", bg=T.CARD, fg=T.TEXT,
                 font=F(13)).pack(side="left")
        tk.Label(head, text="  ziehen · Doppelklick setzt zurück",
                 bg=T.CARD, fg=T.DIS, font=F(11)).pack(side="left")

        def flat():
            for b in fx["baender"]:
                b["db"] = 0.0
            fx["voreinstellung"] = ""
            save_and_apply()
            self.show_page("effekte")

        PushButton(head, "Zurücksetzen", command=flat, icon="refresh",
                   bg=T.CARD).pack(side="right")

        def eq_changed(_bands):
            fx["voreinstellung"] = ""      # eigene Einstellung, kein Preset mehr
            save_and_apply()

        strip = EqStrip(eqcard, fx["baender"], eq_changed, height=180, bg=T.CARD)
        strip.pack(fill="x", padx=12, pady=(6, 12))
        strip.after(30, strip.redraw)

        gcard = SettingsCard(body)
        gcard.pack(fill="x", pady=(8, 0))

        def pre_ctl(ctl):
            def change(v):
                fx["vorverstaerkung_db"] = float(v)
                save_and_apply()
            Stepper(ctl, lambda: int(fx.get("vorverstaerkung_db", 0)), change,
                    -12, 12, 1, " dB", bg=T.CARD).pack()

        gcard.row("mixer", "Vorverstärkung",
                  "Ausgleich, wenn der Equalizer laut anhebt (negativ = leiser)",
                  pre_ctl)

        def hp_ctl(ctl):
            def change(v):
                fx["hochpass_hz"] = 0.0 if int(v) < 20 else float(v)
                fx["voreinstellung"] = ""
                save_and_apply()
            Stepper(ctl, lambda: int(fx.get("hochpass_hz", 0) or 0), change,
                    0, 300, 10, " Hz", bg=T.CARD).pack()

        gcard.row("speaker-0", "Rumpelfilter",
                  "Schneidet alles unterhalb dieser Frequenz weg (0 = aus)",
                  hp_ctl)

        # -- Dynamik & Rauschen -------------------------------------------
        section_title(body, "Dynamik & Rauschen")
        dcard = SettingsCard(body)
        dcard.pack(fill="x")

        def toggle_row(icon, title, desc, key):
            def ctl(c):
                def change(v):
                    fx[key] = bool(v)
                    fx["voreinstellung"] = ""
                    save_and_apply()
                    self.show_page("effekte")
                Toggle(c, lambda: bool(fx.get(key, False)), change, bg=T.CARD).pack()
            dcard.row(icon, title, desc, ctl)

        toggle_row("mixer", "Kompressor",
                   "Macht Laute leiser und Leises hörbarer – Explosionen "
                   "reißen nicht mehr, Schritte gehen nicht unter", "kompressor")

        toggle_row("mic", "Rauschunterdrückung",
                   "Filtert gleichmäßiges Rauschen heraus. Kostet etwas "
                   "Verzögerung – fürs Mikrofon sinnvoller als für Musik",
                   "rauschunterdrueckung")

        if fx.get("rauschunterdrueckung"):
            def strength_ctl(ctl):
                def change(v):
                    fx["rausch_staerke"] = round(float(v), 2)
                    save_and_apply()
                Slider(ctl, lambda: float(fx.get("rausch_staerke", 0.8)), change,
                       width=130, bg=T.CARD).pack()
            dcard.row("mixer", "Stärke der Rauschunterdrückung",
                      "Zu hoch klingt blechern", strength_ctl)

        toggle_row("mute", "Noise Gate",
                   "Schaltet unter einer Schwelle ganz ab – gegen Grundrauschen "
                   "in Pausen", "noise_gate")

        # -- Audioweg -----------------------------------------------------
        section_title(body, "Audioweg")
        info = tk.Label(
            body,
            text="Fluneit legt sich als Zwischenstation in den Ton: Windows spielt "
                 "auf ein Gerät, das niemand hört (die Brücke), Fluneit nimmt das "
                 "auf, legt die Effekte darauf und gibt es auf deinen Kopfhörern "
                 "aus. Dafür braucht es keinen Treiber. Beim Ausschalten wird "
                 "alles zurückgestellt.",
            bg=T.WINDOW, fg=T.SEC, font=F(12), wraplength=470, justify="left",
            anchor="w")
        info.pack(fill="x", pady=(0, 8))

        wcard = SettingsCard(body)
        wcard.pack(fill="x")
        try:
            devices, _cur = core.list_output_devices()
        except Exception:
            devices = []
        names = [n for _i, n in devices]

        def dev_ctl(key, exclude_key):
            def ctl(c):
                def change(v):
                    cfg[key] = v
                    self.saved()
                    self.show_page("effekte")
                opts = [n for n in names
                        if n.lower() != str(cfg.get(exclude_key, "")).lower()]
                Dropdown(c, opts or ["(kein Gerät)"],
                         lambda: cfg.get(key) or "(nicht gewählt)", change,
                         width=186, bg=T.CARD).pack()
            return ctl

        sugg = ""
        try:
            cands = fx_engine.bridge_candidates(exclude_name=cfg.get("effekte_ausgabe"))
            if cands:
                sugg = cands[0]["name"]
        except Exception:
            pass

        wcard.row("headphones", "Ausgabegerät",
                  "Wo du wirklich zuhörst – hierauf gibt Fluneit aus",
                  dev_ctl("effekte_ausgabe", "effekte_bruecke"))
        wcard.row("speaker-0", "Brücke",
                  ("Gerät, auf das Windows spielt. Am besten ein Ausgang, an dem "
                   "nichts hängt" + (f" – Vorschlag: {sugg}" if sugg else "")),
                  dev_ctl("effekte_bruecke", "effekte_ausgabe"))

        def lat_ctl(ctl):
            modes = fx_engine.LATENCY_MODES
            labels = {k: v["name"] for k, v in modes.items()}
            rv = {v: k for k, v in labels.items()}

            def change(label):
                cfg["effekte_latenz"] = rv.get(label, "mittel")
                self.saved()
                if core.fx_running():
                    self.toast.show("Wirkt nach dem nächsten Einschalten")
            cur = labels.get(cfg.get("effekte_latenz", "mittel"), "Mittel (empfohlen)")
            Dropdown(ctl, list(labels.values()), lambda: cur, change,
                     width=172, bg=T.CARD).pack()

        wcard.row("info", "Verzögerung",
                  "Niedriger reagiert schneller, kann aber knacken. "
                  "Beim Zocken „Niedrig“ probieren", lat_ctl)

        # -- Mikrofon -----------------------------------------------------
        section_title(body, "Mikrofon")
        mcard = SettingsCard(body)
        mcard.pack(fill="x")
        mfx = cfg.setdefault("effekte_mikrofon", {})
        mst = core.fx_mic_status()

        def mic_master_ctl(ctl):
            def change(v):
                if v:
                    ok, why = core.fx_mic_start()
                    if not ok:
                        self.toast.show(why[:60])
                else:
                    core.fx_mic_stop()
                self.show_page("effekte")
            Toggle(ctl, core.fx_mic_running, change, bg=T.CARD).pack()

        mcard.row("mic", "Mikrofon bearbeiten",
                  (f"Läuft – ≈{mst.get('latenz_ms', 0):.0f} ms, "
                   f"{mst.get('last', 0):.0f} % Last" if mst.get("laeuft") else
                   "Rauschunterdrückung und Klangkorrektur für dein Mikrofon"),
                  mic_master_ctl)

        mic_names = {k: v["name"] for k, v in fx_dsp.MIC_PRESETS.items()}
        mrev = {v: k for k, v in mic_names.items()}

        def mic_preset_ctl(ctl):
            def change(label):
                key = mrev.get(label)
                if key:
                    cfg["effekte_mikrofon"] = fx_dsp.preset_params(key)
                    self.saved()
                    core.fx_mic_apply_params()
                    self.show_page("effekte")
            cur = mic_names.get(mfx.get("voreinstellung", "mic_klar"),
                                "Mikrofon - Klar")
            Dropdown(ctl, list(mic_names.values()), lambda: cur, change,
                     width=172, bg=T.CARD).pack()

        mcard.row("apps", "Mikrofon-Profil",
                  fx_dsp.MIC_PRESETS.get(mfx.get("voreinstellung", ""), {}).get(
                      "beschreibung", "Fertige Profile für Sprache"),
                  mic_preset_ctl)

        def mic_out_ctl(ctl):
            def change(v):
                cfg["effekte_mikrofon_ausgabe"] = v
                self.saved()
            Dropdown(ctl, names or ["(kein Gerät)"],
                     lambda: cfg.get("effekte_mikrofon_ausgabe") or "(nicht gewählt)",
                     change, width=186, bg=T.CARD).pack()

        mcard.row("headphones", "Bearbeitetes Signal nach",
                  "Gerät zum Mithören", mic_out_ctl)

        tk.Label(body,
                 text="Hinweis: Das bearbeitete Mikrofon lässt sich mithören, aber "
                      "nicht als Eingang an Discord oder TeamSpeak weiterreichen – "
                      "dafür bräuchte es ein virtuelles Audiokabel, und das ist ein "
                      "Treiber. Fluneit kommt bewusst ohne aus.",
                 bg=T.WINDOW, fg=T.DIS, font=F(12), wraplength=470,
                 justify="left", anchor="w").pack(fill="x", pady=(8, 0))

    # --- Seite: Regeln ---
    RULE_LABELS = {"startlautstaerke": "Start bei fester Lautstärke",
                   "stumm": "Immer stumm", "ausschliessen": "Vom Rad ausschließen"}

    def _page_regeln(self, body):
        head = tk.Frame(body, bg=T.WINDOW)
        head.pack(fill="x")
        tk.Label(head, text="Regeln", bg=T.WINDOW, fg=T.TEXT,
                 font=F(20, semibold=True, display=True)).pack(side="left", pady=(4, 20))
        PushButton(head, "Regel hinzufügen", icon="add", variant="primary",
                   command=lambda: self._rule_dialog()).pack(side="right")

        rules = core.CONFIG.get("regeln", [])
        card = tk.Frame(body, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        card.pack(fill="x")
        if not rules:
            EmptyState(card, "rules",
                       "Noch keine Regeln. Eine Regel legt fest, wie Fluneit eine App behandelt "
                       "— z. B. immer stumm oder mit fester Start-Lautstärke.",
                       action=lambda p: PushButton(p, "Regel hinzufügen", icon="add", variant="primary",
                                                   command=lambda: self._rule_dialog(), bg=T.CARD).pack(pady=(12, 0))
                       ).pack(fill="x")
            return
        for i, rule in enumerate(rules):
            if i:
                tk.Frame(card, bg=T.STROKE, height=1).pack(fill="x", padx=8)
            row = tk.Frame(card, bg=T.CARD)
            row.pack(fill="x", padx=12, pady=8)
            app = str(rule.get("app", "?"))
            name = core.pretty_name(app)
            AppGlyph(row, name[0], size=32, bg=T.CARD).pack(side="left", padx=(0, 12))
            tk.Label(row, text=name, font=F(13), fg=T.TEXT, bg=T.CARD).pack(side="left")
            typ = rule.get("typ", "")
            label = (f"Start bei {rule.get('wert', 100)} %" if typ == "startlautstaerke"
                     else self.RULE_LABELS.get(typ, typ))
            IconButton(row, "delete", command=lambda r=rule: self._delete_rule(r),
                       bg=T.CARD).pack(side="right", padx=(4, 0))
            IconButton(row, "edit", command=lambda r=rule: self._rule_dialog(r),
                       bg=T.CARD).pack(side="right")
            Badge(row, label, variant="accent", bg=T.CARD).pack(side="right", padx=10)

    def _delete_rule(self, rule):
        core.CONFIG["regeln"] = [r for r in core.CONFIG.get("regeln", []) if r is not rule]
        self.saved()
        self.show_page("regeln")

    def _rule_dialog(self, rule=None):
        from tkinter import filedialog
        dlg = Dialog(self, "Regel bearbeiten" if rule else "Regel hinzufügen")
        apps = sorted({core.pretty_name(k): k for k in core.collect_audio_apps()}.items())
        options = [n for n, _ in apps] + ["Durchsuchen…"]
        name_by_label = dict(apps)
        state = {
            "app": core.pretty_name(rule["app"]) if rule else (options[0] if apps else "Durchsuchen…"),
            "app_exe": rule["app"] if rule else (apps[0][1] if apps else ""),
            "typ": self.RULE_LABELS.get(rule.get("typ"), list(self.RULE_LABELS.values())[0]) if rule
                   else list(self.RULE_LABELS.values())[0],
            "wert": int(rule.get("wert", 40)) if rule else 40,
        }
        typ_by_label = {v: k for k, v in self.RULE_LABELS.items()}

        tk.Label(dlg.body, text="App", bg=T.CARD, fg=T.TEXT, font=F(13), anchor="w").pack(fill="x")

        def pick_app(v):
            if v == "Durchsuchen…":
                ftypes = [("Programme", "*.exe")] if IS_WINDOWS else [("Alle Dateien", "*")]
                path = filedialog.askopenfilename(parent=dlg, filetypes=ftypes)
                if path:
                    state["app_exe"] = os.path.basename(path).lower()
                    state["app"] = core.pretty_name(state["app_exe"])
            else:
                state["app"] = v
                state["app_exe"] = name_by_label.get(
                    v, v.lower() + (".exe" if IS_WINDOWS else ""))
            app_dd.refresh()

        app_dd = Dropdown(dlg.body, options, lambda: state["app"], pick_app, width=300, bg=T.CARD)
        app_dd.pack(anchor="w", pady=(4, 10))

        tk.Label(dlg.body, text="Regeltyp", bg=T.CARD, fg=T.TEXT, font=F(13), anchor="w").pack(fill="x")
        slider_holder = tk.Frame(dlg.body, bg=T.CARD)

        def pick_typ(v):
            state["typ"] = v
            typ_dd.refresh()
            update_slider()

        typ_dd = Dropdown(dlg.body, list(self.RULE_LABELS.values()), lambda: state["typ"], pick_typ,
                          width=300, bg=T.CARD)
        typ_dd.pack(anchor="w", pady=(4, 10))
        slider_holder.pack(fill="x")

        def update_slider():
            for c in slider_holder.winfo_children():
                c.destroy()
            if typ_by_label[state["typ"]] == "startlautstaerke":
                tk.Label(slider_holder, text="Lautstärke", bg=T.CARD, fg=T.TEXT, font=F(13),
                         anchor="w").pack(fill="x")
                row = tk.Frame(slider_holder, bg=T.CARD)
                row.pack(fill="x", pady=(4, 4))
                vlbl = tk.Label(row, text=f"{state['wert']}%", bg=T.CARD, fg=T.TEXT, font=F(13), width=5, anchor="e")

                def setv(f):
                    state["wert"] = round(f * 100)
                    vlbl.config(text=f"{state['wert']}%")
                Slider(row, lambda: state["wert"] / 100, setv, width=240, bg=T.CARD).pack(side="left")
                vlbl.pack(side="left", padx=6)
            dlg.finish()

        update_slider()

        def confirm():
            new_rule = {"app": state["app_exe"].lower(), "typ": typ_by_label[state["typ"]]}
            if new_rule["typ"] == "startlautstaerke":
                new_rule["wert"] = state["wert"]
            rules = core.CONFIG.setdefault("regeln", [])
            if rule is not None and rule in rules:
                rules[rules.index(rule)] = new_rule
            else:
                rules.append(new_rule)
            dlg.destroy()
            self.saved()
            self.show_page("regeln")

        PushButton(dlg.actions, "Hinzufügen" if rule is None else "Speichern", variant="primary",
                   command=confirm, bg=T.CARD).pack(side="left")
        PushButton(dlg.actions, "Abbrechen", command=dlg.destroy, bg=T.CARD).pack(side="left", padx=8)
        dlg.finish()

    # --- Seite: Ueber ---
    def _page_ueber(self, body):
        page_title(body, "Über")
        card = tk.Frame(body, bg=T.CARD, highlightbackground=T.STROKE, highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=T.CARD)
        inner.pack(fill="x", padx=20, pady=20)
        tk.Label(inner, image=app_icon_image(64), bg=T.CARD).pack(side="left", padx=(0, 20))
        txt = tk.Frame(inner, bg=T.CARD)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text="Fluneit", bg=T.CARD, fg=T.TEXT,
                 font=F(20, semibold=True, display=True), anchor="w").pack(fill="x")
        tk.Label(txt, text=f"Version {core.__version__}", bg=T.CARD, fg=T.SEC, font=F(12),
                 anchor="w").pack(fill="x", pady=(2, 8))
        tk.Label(txt, text="Regelt die Lautstärke einzelner Programme über das\nLautstärkerad der Tastatur.",
                 bg=T.CARD, fg=T.SEC, font=F(13), anchor="w", justify="left").pack(fill="x")

        actions = tk.Frame(body, bg=T.WINDOW)
        actions.pack(fill="x", pady=(16, 0))
        status = tk.Frame(actions, bg=T.WINDOW)

        def check():
            for c in status.winfo_children():
                c.destroy()
            tk.Label(status, text=ICONS["check"], font=IF(14), fg=T.SEC, bg=T.WINDOW).pack(side="left")
            tk.Label(status, text=" Fluneit ist aktuell", font=F(12), fg=T.SEC,
                     bg=T.WINDOW).pack(side="left")

        PushButton(actions, "Nach Updates suchen", icon="refresh", command=check).pack(side="left")
        status.pack(side="left", padx=12)

        links = tk.Frame(body, bg=T.WINDOW)
        links.pack(fill="x", pady=(20, 0))
        for text, path in (("Log-Datei öffnen", core.LOG_FILE), ("Projektordner öffnen", core.APP_DIR)):
            lnk = tk.Label(links, text=text, font=F(13), fg=T.ACCENT, bg=T.WINDOW, cursor="hand2")
            lnk.pack(side="left", padx=(0, 20))
            lnk.bind("<Button-1>", lambda e, p=path: open_path(p) if os.path.exists(p) else None)


# ----------------------------- Tray-Flyout ----------------------------------

class Flyout:
    """Mini-Mixer nach ui_kits/soundcontrol/tray.html: Kopfzeile, App-Zeilen
    (Name ueber Slider), Trennlinie, Ausgabegeraet-Wechsler."""

    W = 360

    def __init__(self, root, scale=1.0):
        self.root = root
        self.k = scale
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=T.STROKE)
        self.inner = tk.Frame(self.win, bg=T.CARD)
        self.inner.pack(fill="both", expand=True, padx=1, pady=1)
        self._visible = False
        self._watch_job = None
        self._last_outside_hide = 0.0
        self._rounded = False

    def px(self, v):
        return round(v * self.k)

    def _build(self):
        for c in self.inner.winfo_children():
            c.destroy()

        pad = self.px(12)
        head = tk.Frame(self.inner, bg=T.CARD)
        head.pack(fill="x", padx=pad, pady=(self.px(8), self.px(4)))
        tk.Label(head, text="Mixer", bg=T.CARD, fg=T.TEXT, font=F(14, semibold=True)).pack(side="left")
        IconButton(head, "settings", size=28, bg=T.CARD,
                   command=lambda: (self.hide(), open_settings(self.root, "mixer"))).pack(side="right")

        # System-Master + Mikrofon (macht das Flyout zum vollen Sound-Zentrum)
        try:
            ep = core._default_endpoint(0, 1)
            self._ep_row("System", "speaker-2", ep)
        except Exception:
            logging.exception("System-Regler im Flyout nicht verfuegbar")
        try:
            mep = core.mic_endpoint()
            self._ep_row("Mikrofon", "mic", mep)
        except Exception:
            pass
        tk.Frame(self.inner, bg=T.STROKE, height=1).pack(fill="x", padx=self.px(12), pady=self.px(4))

        hidden = set(core.CONFIG.get("ausgeblendete_apps", []))
        apps = {k: v for k, v in core.collect_audio_apps().items() if k not in hidden}
        for key in sorted(apps, key=lambda x: apps[x]["name"].lower()):
            self._app_row(key, apps[key])
        if not apps:
            tk.Label(self.inner, text="Gerade spielt nichts Audio ab.", bg=T.CARD, fg=T.SEC,
                     font=F(12)).pack(pady=self.px(12))

        devices = self._render_devices()
        tk.Frame(self.inner, bg=T.CARD, height=self.px(6)).pack(fill="x")
        return devices

    def _ep_row(self, label, icon, ep):
        """Zeile fuer ein Endpunkt-Geraet (System-Master oder Mikrofon)."""
        pad = self.px(12)

        def safe(fn, default=None):
            try:
                return fn()
            except Exception:
                return default

        row = tk.Frame(self.inner, bg=T.CARD)
        row.pack(fill="x", padx=pad, pady=self.px(5))
        tk.Label(row, text=ICONS[icon], font=IF(16), fg=T.TEXT, bg=T.CARD,
                 width=2).pack(side="left", padx=(self.px(2), self.px(10)))
        btn = IconButton(row, "speaker-2", size=self.px(32), bg=T.CARD, icon_size=15)
        btn.pack(side="right", padx=(self.px(6), 0))
        mid = tk.Frame(row, bg=T.CARD)
        mid.pack(side="left", fill="x", expand=True)
        tk.Label(mid, text=label, bg=T.CARD, fg=T.SEC, font=F(12), anchor="w").pack(fill="x")
        srow = tk.Frame(mid, bg=T.CARD)
        srow.pack(fill="x")
        val = tk.Label(srow, bg=T.CARD, fg=T.TEXT, font=F(13), width=4, anchor="e")

        def set_vol(f):
            safe(lambda: ep.SetMasterVolumeLevelScalar(f, None))
            val.config(text=f"{round(f*100)}%")

        slider = Slider(srow, lambda: safe(lambda: ep.GetMasterVolumeLevelScalar(), 0.0) or 0.0,
                        set_vol, width=self.px(200), bg=T.CARD)
        slider.pack(side="left")
        val.pack(side="left", padx=(self.px(6), 0))

        mic_icon = icon == "mic"

        def sync():
            muted = safe(lambda: bool(ep.GetMute()), False)
            v = safe(lambda: ep.GetMasterVolumeLevelScalar(), 0.0) or 0.0
            val.config(text=f"{round(v*100)}%", fg=T.DIS if muted else T.TEXT)
            slider.disabled = muted
            slider.refresh()
            off = "mute" if not mic_icon else "mic"
            btn.set_icon("mute" if muted else ("mic" if mic_icon else "speaker-2"), active=muted)

        btn.command = lambda: (safe(lambda: ep.SetMute(not safe(lambda: bool(ep.GetMute()), False), None)), sync())
        sync()

    def _app_row(self, key, e):
        pad = self.px(12)
        vols = [s.SimpleAudioVolume for s in e["sessions"]]

        def safe(fn, default=None):
            try:
                return fn()
            except Exception:
                return default

        row = tk.Frame(self.inner, bg=T.CARD)
        row.pack(fill="x", padx=pad, pady=self.px(5))
        icon_img = core.get_app_icon(e["exe"], self.px(32))
        AppGlyph(row, e["name"][0], size=self.px(32), image=icon_img, bg=T.CARD).pack(side="left", padx=(0, self.px(10)))

        btn = IconButton(row, "speaker-2", size=self.px(32), bg=T.CARD, icon_size=15)
        btn.pack(side="right", padx=(self.px(6), 0))
        mid = tk.Frame(row, bg=T.CARD)
        mid.pack(side="left", fill="x", expand=True)
        tk.Label(mid, text=e["name"], bg=T.CARD, fg=T.SEC, font=F(12), anchor="w").pack(fill="x")
        srow = tk.Frame(mid, bg=T.CARD)
        srow.pack(fill="x")
        val = tk.Label(srow, bg=T.CARD, fg=T.TEXT, font=F(13), width=4, anchor="e")

        def set_vol(f):
            for v in vols:
                safe(lambda v=v: v.SetMasterVolume(f, None))
            val.config(text=f"{round(f*100)}%")

        slider = Slider(srow, lambda: safe(lambda: vols[0].GetMasterVolume(), 0.0) or 0.0,
                        set_vol, width=self.px(200), bg=T.CARD)
        slider.pack(side="left")
        val.pack(side="left", padx=(self.px(6), 0))

        def sync():
            muted = safe(lambda: bool(vols[0].GetMute()), False)
            v = safe(lambda: vols[0].GetMasterVolume(), 0.0) or 0.0
            val.config(text=f"{round(v*100)}%", fg=T.DIS if muted else T.TEXT)
            slider.disabled = muted
            slider.refresh()
            btn.set_icon("mute" if muted else "speaker-2", active=muted)

        btn.command = lambda: ([safe(lambda v=v: v.SetMute(not safe(lambda: bool(vols[0].GetMute()), False), None))
                                for v in vols], sync())
        sync()

        def hide_app():
            lst = core.CONFIG.setdefault("ausgeblendete_apps", [])
            if key not in lst:
                lst.append(key)
            core.save_config()
            self._build()
            self._place()

        for w in _descendants(row):
            w.bind("<Button-3>", lambda ev: context_menu(
                self.win, ev.x_root, ev.y_root, [("App ausblenden", hide_app)]))

    def _render_devices(self):
        try:
            devices, current = core.list_output_devices()
        except Exception:
            return False
        hidden_ids = {d.get("id") for d in core.CONFIG.get("ausgeblendete_geraete", [])}
        devices = [(i, n) for i, n in devices if i not in hidden_ids]
        if not devices:
            return False
        pad = self.px(12)
        tk.Frame(self.inner, bg=T.STROKE, height=1).pack(fill="x", padx=pad, pady=(self.px(6), self.px(4)))
        tk.Label(self.inner, text="Ausgabegerät", bg=T.CARD, fg=T.SEC, font=F(12),
                 anchor="w").pack(fill="x", padx=pad + self.px(8))

        def dev_icon(name):
            n = name.lower()
            if any(k in n for k in ("kopfhörer", "headphone", "headset", "buds", "arctis")):
                return "headphones"
            if any(k in n for k in ("monitor", "display", "tv", "hdmi", "bildschirm")):
                return "monitor"
            return "speaker-2"

        for dev_id, name in devices:
            row = tk.Frame(self.inner, bg=T.CARD, cursor="hand2")
            row.pack(fill="x", padx=pad, pady=1)
            ic = tk.Label(row, text=ICONS[dev_icon(name)], font=IF(13), fg=T.SEC, bg=T.CARD)
            ic.pack(side="left", padx=(self.px(8), self.px(8)), pady=self.px(6))
            lbl = tk.Label(row, text=name, bg=T.CARD, fg=T.TEXT, font=F(13), anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            widgets = [row, ic, lbl]
            if dev_id == current:
                chk = tk.Label(row, text=ICONS["check"], font=IF(13), fg=T.ACCENT, bg=T.CARD)
                chk.pack(side="right", padx=self.px(8))
                widgets.append(chk)
            def hide_dev(d=dev_id, nm=name):
                lst = core.CONFIG.setdefault("ausgeblendete_geraete", [])
                if not any(x.get("id") == d for x in lst):
                    lst.append({"id": d, "name": nm})
                core.save_config()
                self._build()
                self._place()

            for w in widgets:
                w.bind("<Button-1>", lambda e, d=dev_id: self._switch_device(d))
                w.bind("<Button-3>", lambda e, h=hide_dev: context_menu(
                    self.win, e.x_root, e.y_root, [("Gerät ausblenden", h)]))
                w.bind("<Enter>", lambda e, r=row: [c.configure(bg=T.HOVER) for c in (r, *r.winfo_children())])
                w.bind("<Leave>", lambda e, r=row: [c.configure(bg=T.CARD) for c in (r, *r.winfo_children())])
        return True

    def _switch_device(self, dev_id):
        try:
            core.set_default_output_device(dev_id)
        except Exception:
            logging.exception("Geraetewechsel fehlgeschlagen")
        self.win.after(150, lambda: (self._build(), self._place()))

    # ---- Anzeigen / Verstecken ----

    def _place(self):
        self.win.update_idletasks()
        w = self.px(self.W)
        h = self.inner.winfo_reqheight() + 2
        if IS_WINDOWS:
            work = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work), 0)
            right, bottom = work.right, work.bottom
        else:
            import linux_input
            import linux_osd
            wx, wy, ww, wh = linux_input.get_workarea()
            px_, py_, pw_, ph_ = linux_osd.primary_geometry(self.root)
            right = min(wx + ww, px_ + pw_)
            bottom = min(wy + wh, py_ + ph_)
        x = right - w - self.px(12)
        y = bottom - h - self.px(12)
        self.win.geometry(f"{w}x{h}+{x}+{y}")

    def show(self):
        self._build()
        self._place()
        self.win.deiconify()
        self.win.lift()
        if not self._rounded:
            round_corners(self.win)
            self._rounded = True
        self._visible = True
        if not self._watch_job:
            self._watch_job = self.root.after(120, self._watch)

    def hide(self, by_outside_click=False):
        self._visible = False
        if by_outside_click:
            self._last_outside_hide = time.monotonic()
        self.win.withdraw()

    def toggle(self):
        if self._visible:
            self.hide()
        elif time.monotonic() - self._last_outside_hide > 0.35:
            self.show()

    def _watch(self):
        self._watch_job = None
        if not self._visible:
            return
        if IS_WINDOWS:
            u = ctypes.windll.user32
            esc = bool(u.GetAsyncKeyState(0x1B) & 0x8000)
            if u.GetAsyncKeyState(0x01) & 0x8000:
                pt = wintypes.POINT()
                u.GetCursorPos(ctypes.byref(pt))
                click = (pt.x, pt.y)
            else:
                click = None
        else:
            import linux_input
            esc = linux_input.escape_down()
            mx, my, down = linux_input.pointer_info()
            click = (mx, my) if down else None
        if esc:
            self.hide()
            return
        if click is not None:
            x0, y0 = self.win.winfo_rootx(), self.win.winfo_rooty()
            inside = (x0 <= click[0] <= x0 + self.win.winfo_width()
                      and y0 <= click[1] <= y0 + self.win.winfo_height())
            popup = any(isinstance(w, tk.Toplevel) and w is not self.win and w.winfo_viewable()
                        for w in self.win.winfo_children())
            if not inside and not popup:
                self.hide(by_outside_click=True)
                return
        self._watch_job = self.root.after(120, self._watch)


# ----------------------------- Onboarding -----------------------------------

class OnboardingWindow(tk.Toplevel):
    W, H = 420, 360

    def __init__(self, root, on_done=None):
        super().__init__(root)
        self.on_done = on_done
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=T.STROKE)
        self.outer = tk.Frame(self, bg=T.WINDOW)
        self.outer.pack(fill="both", expand=True, padx=1, pady=1)
        sx, sy, sw, sh = screen_geometry(self)
        self.geometry(f"{self.W}x{self.H}+{sx + (sw - self.W) // 2}+{sy + (sh - self.H) // 2 - 40}")
        round_corners(self)
        self.step = 0
        self._render()

    def _render(self):
        for c in self.outer.winfo_children():
            c.destroy()
        content = tk.Frame(self.outer, bg=T.WINDOW)
        content.pack(fill="both", expand=True)
        holder = tk.Frame(content, bg=T.WINDOW)
        holder.place(relx=0.5, rely=0.47, anchor="center")
        [self._step0, self._step1, self._step2][self.step](holder)

        foot = tk.Frame(self.outer, bg=T.WINDOW)
        foot.pack(fill="x", side="bottom", padx=16, pady=12)
        if self.step > 0:
            PushButton(foot, "Zurück", command=lambda: self._go(self.step - 1)).pack(side="left")
        dots = tk.Frame(foot, bg=T.WINDOW)
        dots.place(relx=0.5, rely=0.5, anchor="center")
        for i in range(3):
            cv = tk.Canvas(dots, width=12, height=12, bg=T.WINDOW, highlightthickness=0, cursor="hand2")
            cv.create_oval(2, 2, 10, 10, fill=T.ACCENT if i == self.step else T.TRACK, outline="")
            cv.pack(side="left", padx=2)
            cv.bind("<Button-1>", lambda e, i=i: self._go(i))
        if self.step < 2:
            PushButton(foot, "Weiter", variant="primary", command=lambda: self._go(self.step + 1)).pack(side="right")

    def _go(self, step):
        self.step = step
        self._render()

    def _step0(self, p):
        tk.Label(p, image=app_icon_image(64), bg=T.WINDOW).pack(pady=(0, 16))
        tk.Label(p, text="Willkommen bei Fluneit", bg=T.WINDOW, fg=T.TEXT,
                 font=F(20, semibold=True, display=True)).pack()
        tk.Label(p, text="Fluneit läuft ab jetzt im Infobereich und regelt\ndie Lautstärke einzelner Programme.",
                 bg=T.WINDOW, fg=T.SEC, font=F(13), justify="center").pack(pady=(12, 0))

    def _step1(self, p):
        tk.Label(p, text="So funktioniert's", bg=T.WINDOW, fg=T.TEXT,
                 font=F(14, semibold=True)).pack(pady=(0, 16))
        mod = {"shift": "Shift", "strg": "Strg", "ctrl": "Strg", "alt": "Alt"}.get(
            str(core.CONFIG["modifier"]).lower(), "Shift")
        KeyCombo(p, [mod, "Rad"], "App-Lautstärke", bg=T.WINDOW).pack(pady=(0, 16))
        # Mini-Vorschau des Overlays
        card = tk.Frame(p, bg=T.STROKE)
        card.pack()
        inner = tk.Frame(card, bg=T.CARD)
        inner.pack(padx=1, pady=1)
        pill = tk.Label(inner, text=" Musik-Player ", bg=T.HOVER, fg=T.TEXT, font=F(11))
        pill.pack(anchor="w", padx=12, pady=(10, 6))
        srow = tk.Frame(inner, bg=T.CARD)
        srow.pack(padx=14, pady=(0, 12))
        tk.Label(srow, text=ICONS["speaker-2"], font=IF(14), fg=T.TEXT, bg=T.CARD).pack(side="left", padx=(0, 8))
        bar = tk.Canvas(srow, width=120, height=6, bg=T.CARD, highlightthickness=0)
        bar.create_line(0, 3, 120, 3, fill=T.TRACK, width=4, capstyle="round")
        bar.create_line(0, 3, 78, 3, fill=T.ACCENT, width=4, capstyle="round")
        bar.pack(side="left")
        tk.Label(srow, text="65", font=F(12), fg=T.TEXT, bg=T.CARD).pack(side="left", padx=(8, 0))
        tk.Label(p, text="Halte die Taste und drehe das Lautstärkerad —\ngeregelt wird die App im Vordergrund.",
                 bg=T.WINDOW, fg=T.SEC, font=F(12), justify="center").pack(pady=(14, 0))

    def _step2(self, p):
        tk.Label(p, text="Fast geschafft", bg=T.WINDOW, fg=T.TEXT,
                 font=F(14, semibold=True)).pack(pady=(0, 18))
        card = tk.Frame(p, bg=T.STROKE)
        card.pack()
        inner = tk.Frame(card, bg=T.CARD)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=core.AUTOSTART_LABEL, bg=T.CARD, fg=T.TEXT, font=F(13)).pack(
            side="left", padx=(16, 12), pady=12)
        Toggle(inner, core.autostart_enabled,
               lambda v: core.set_autostart(v), bg=T.CARD).pack(side="right", padx=(0, 16))
        PushButton(p, "Los geht's", variant="primary", command=self._finish).pack(pady=(20, 0))

    def _finish(self):
        if self.on_done:
            self.on_done()
        self.destroy()


def init(core_module, root):
    """Vom Hauptmodul aufgerufen: verdrahtet ui mit fluneit."""
    global core
    core = core_module
    _init_fonts()
