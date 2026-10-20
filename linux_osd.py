"""Linux-Overlay (OSD): Tk-Toplevels statt Win32-Layered-Windows.

Gleiche Optik und gleiches Verhalten wie der Windows-OSD-Nachbau in
fluneit.py (Box mit Slider + Pille mit App-Name, unten mittig), aber:

- Fenster sind randlose Tk-Toplevels (override-redirect, topmost).
- Runde Ecken + Klick-Durchlaessigkeit ueber die X11-Shape-Extension
  (Rechteck-Baender aus der Alpha-Maske; Input-Shape leer -> Klicks gehen
  durch). Schlaegt Shape fehl, bleibt das Overlay eckig - rein kosmetisch.
- Ausblenden ueber Fenster-Alpha (_NET_WM_WINDOW_OPACITY, von KWin
  komponiert), gleiche Stufen wie unter Windows.
- Icons werden mit PIL gezeichnet (Segoe-Fluent-Glyphen existieren unter
  Linux nicht): Lautsprecher mit Schallwellen, Mikrofon, Medien-Symbole.

Positioniert wird auf dem Primaermonitor (RandR), nicht auf der virtuellen
Gesamtflaeche - sonst laege das OSD bei zwei Monitoren auf der Nahtstelle.
"""

import logging
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

import linux_input

_FONT_CANDIDATES = ["NotoSans-Regular.ttf", "Ubuntu-R.ttf", "DejaVuSans.ttf"]
_FONT_BOLD_CANDIDATES = ["NotoSans-Bold.ttf", "Ubuntu-B.ttf", "DejaVuSans-Bold.ttf"]


def _load_font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def primary_geometry(root):
    """(x, y, breite, hoehe) des Primaermonitors; Fallback: ganzer Bildschirm."""
    try:
        from Xlib.ext import randr
        d = linux_input._query_display()
        xroot = d.screen().root
        prim = randr.get_output_primary(xroot).output
        if prim:
            info = randr.get_output_info(d, prim, 0)
            if info.crtc:
                c = randr.get_crtc_info(d, info.crtc, 0)
                if c.width and c.height:
                    return c.x, c.y, c.width, c.height
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class _Layer:
    """Ein randloses Overlay-Fenster mit Bildinhalt + Shape-Maske."""

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        try:
            self.win.attributes("-type", "notification")
        except tk.TclError:
            pass
        self.win.attributes("-topmost", True)
        self.label = tk.Label(self.win, bd=0, highlightthickness=0)
        self.label.pack()
        self._photo = None
        self._shape_key = None
        self.visible = False

    def push(self, img, x, y, alpha=1.0):
        """RGBA-Bild anzeigen (auf Hintergrund abgeflacht, Form per Shape)."""
        flat = Image.new("RGB", img.size, "#2d2d2c")
        flat.paste(img, mask=img.split()[3])
        self._photo = ImageTk.PhotoImage(flat)
        self.label.configure(image=self._photo)
        self.win.geometry(f"{img.width}x{img.height}+{x}+{y}")
        try:
            self.win.attributes("-alpha", max(0.0, min(1.0, alpha)))
        except tk.TclError:
            pass
        if not self.visible:
            self.win.deiconify()
            self.win.lift()
            self.visible = True
        self._apply_shape(img)

    def set_alpha(self, alpha):
        try:
            self.win.attributes("-alpha", max(0.0, min(1.0, alpha)))
        except tk.TclError:
            pass

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def _apply_shape(self, img):
        """Runde Ecken + leere Input-Region (Klicks gehen durchs Overlay)."""
        key = (img.width, img.height)
        try:
            from Xlib.ext import shape
            self.win.update_idletasks()
            d = linux_input._query_display()
            xwin = d.create_resource_object("window", self.win.winfo_id())
            if key != self._shape_key:
                mask = img.split()[3].point(lambda v: 255 if v >= 96 else 0)
                w, h = mask.size
                px = mask.load()
                rects, start_row, cur = [], 0, None
                for y in range(h + 1):
                    if y < h:
                        x0 = x1 = None
                        for x in range(w):
                            if px[x, y]:
                                x0 = x
                                break
                        if x0 is not None:
                            for x in range(w - 1, -1, -1):
                                if px[x, y]:
                                    x1 = x
                                    break
                        run = (x0, x1) if x0 is not None else None
                    else:
                        run = None
                    if run != cur:
                        if cur is not None:
                            rects.append((cur[0], start_row,
                                          cur[1] - cur[0] + 1, y - start_row))
                        start_row, cur = y, run
                xwin.shape_rectangles(shape.SO.Set, shape.SK.Bounding, 0, 0, 0, rects)
                self._shape_key = key
            xwin.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
            d.flush()
        except Exception:
            self._shape_key = None  # Shape nicht verfuegbar -> eckig anzeigen


class OSD:
    """Linux-Gegenstueck zur OSD-Klasse in fluneit.py (gleiche Schnittstelle)."""

    W, H = 194, 55
    BOTTOM_MARGIN = 55
    RADIUS = 9
    BG = "#2d2d2c"
    BORDER = "#3f3f3e"
    ACCENT = "#4cc2ff"
    TRACK = "#8a8a8a"
    TEXT = "#ffffff"
    SLIDER_X0, SLIDER_X1 = 46, 150
    SLIDER_H = 4
    NUM_CENTER_X = 171
    ICON_X = 14
    PILL_H = 30
    PILL_GAP = 8
    PILL_PAD = 28

    SS = 2
    FADE_ALPHAS = (200, 140, 80, 30)
    FADE_STEP_MS = 30

    def __init__(self, root):
        self.root = root
        try:
            self.scale = max(0.75, root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self.scale = 1.0
        k = self.scale
        self.w, self.h = round(self.W * k), round(self.H * k)
        self.bottom_margin = round(self.BOTTOM_MARGIN * k)
        self.pill_h = round(self.PILL_H * k)
        self.pill_gap = round(self.PILL_GAP * k)

        s = self.SS
        self.font_num = _load_font(_FONT_CANDIDATES, round(15 * k) * s)
        self.font_pill = _load_font(_FONT_BOLD_CANDIDATES, round(13 * k) * s)

        self.box = _Layer(root)
        self.pill = _Layer(root)
        self.hint = _Layer(root)
        self.extras = []
        self._hint_text = None
        self._hide_job = None
        self._fade_job = None
        self._visible = False
        self._last_layers = []
        self._box_cache = {}
        self._pill_cache = {}

    # ---- gezeichnete Icons (Ersatz fuer Segoe-Fluent-Glyphen) ----

    def _draw_speaker(self, d, cx, cy, u, color, waves=0, muted=False):
        """u = Grundeinheit (Icon passt in ~10u x 10u), Mittelpunkt (cx, cy)."""
        d.polygon([(cx - 5 * u, cy - 2 * u), (cx - 2.5 * u, cy - 2 * u),
                   (cx - 0.2 * u, cy - 4.4 * u), (cx - 0.2 * u, cy + 4.4 * u),
                   (cx - 2.5 * u, cy + 2 * u), (cx - 5 * u, cy + 2 * u)], fill=color)
        lw = max(1, round(0.9 * u))
        for i in range(waves):
            r = (2.2 + i * 1.7) * u
            d.arc([cx - r + 1.2 * u, cy - r, cx + r + 1.2 * u, cy + r],
                  start=-45, end=45, fill=color, width=lw)
        if muted:
            d.line([(cx + 1.2 * u, cy - 2.2 * u), (cx + 4.6 * u, cy + 2.2 * u)],
                   fill=color, width=lw)
            d.line([(cx + 4.6 * u, cy - 2.2 * u), (cx + 1.2 * u, cy + 2.2 * u)],
                   fill=color, width=lw)

    def _draw_mic(self, d, cx, cy, u, color, muted=False):
        lw = max(1, round(0.9 * u))
        d.rounded_rectangle([cx - 1.4 * u, cy - 4.6 * u, cx + 1.4 * u, cy + 0.8 * u],
                            radius=1.4 * u, fill=color)
        d.arc([cx - 3 * u, cy - 2.6 * u, cx + 3 * u, cy + 2.6 * u],
              start=0, end=180, fill=color, width=lw)
        d.line([(cx, cy + 2.6 * u), (cx, cy + 4.4 * u)], fill=color, width=lw)
        if muted:
            d.line([(cx - 4 * u, cy - 4.6 * u), (cx + 4 * u, cy + 4.6 * u)],
                   fill="#2d2d2c", width=lw * 3)
            d.line([(cx - 4 * u, cy - 4.6 * u), (cx + 4 * u, cy + 4.6 * u)],
                   fill=color, width=lw)

    def _draw_media(self, d, name, cx, cy, u, color):
        t = 4 * u  # halbe Hoehe der Symbole
        if name in ("next", "fwd"):
            d.polygon([(cx - 4.5 * u, cy - t), (cx - 0.5 * u, cy), (cx - 4.5 * u, cy + t)], fill=color)
            d.polygon([(cx - 0.2 * u, cy - t), (cx + 3.8 * u, cy), (cx - 0.2 * u, cy + t)], fill=color)
            if name == "next":
                d.rectangle([cx + 4.1 * u, cy - t, cx + 5.1 * u, cy + t], fill=color)
        elif name in ("prev", "rew"):
            d.polygon([(cx + 4.5 * u, cy - t), (cx + 0.5 * u, cy), (cx + 4.5 * u, cy + t)], fill=color)
            d.polygon([(cx + 0.2 * u, cy - t), (cx - 3.8 * u, cy), (cx + 0.2 * u, cy + t)], fill=color)
            if name == "prev":
                d.rectangle([cx - 5.1 * u, cy - t, cx - 4.1 * u, cy + t], fill=color)
        elif name == "play":
            d.polygon([(cx - 2.8 * u, cy - t), (cx + 3.6 * u, cy), (cx - 2.8 * u, cy + t)], fill=color)
        elif name == "pause":
            d.rectangle([cx - 3 * u, cy - t, cx - 0.8 * u, cy + t], fill=color)
            d.rectangle([cx + 0.8 * u, cy - t, cx + 3 * u, cy + t], fill=color)

    # ---- Rendern (Logik wie in fluneit.OSD, Icons gezeichnet) ----

    def _rounded_base(self, w, h, radius):
        s = self.SS
        img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius * s,
                            fill=self.BG, outline=self.BORDER, width=s)
        return img, d

    def _render_box(self, volume, muted, no_session, kind, media_icon=None, media_text=None):
        s, k = self.SS, self.scale
        img, d = self._rounded_base(self.w, self.h, round(self.RADIUS * k))
        cy = self.h * s // 2
        u = k * s  # Zeichen-Grundeinheit der Icons
        icon_cx = round((self.ICON_X + 9) * k) * s

        if kind == "media":
            self._draw_media(d, media_icon, icon_cx, cy, u, self.TEXT)
            d.text((round((self.ICON_X + 32) * k) * s, cy), media_text or "",
                   font=self.font_num, fill=self.TEXT, anchor="lm")
            return img.resize((self.w, self.h), Image.LANCZOS)

        if kind == "mic":
            self._draw_mic(d, icon_cx, cy, u, self.TEXT, muted=(muted or no_session))
            num = "–" if no_session else str(round(volume * 100))
        elif no_session:
            self._draw_speaker(d, icon_cx, cy, u, self.TEXT, waves=0, muted=True)
            num = "–"
        elif muted:
            self._draw_speaker(d, icon_cx, cy, u, self.TEXT, waves=0, muted=True)
            num = str(round(volume * 100))
        else:
            level = 0 if volume <= 0.005 else 1 + min(2, int(volume * 3))
            self._draw_speaker(d, icon_cx, cy, u, self.TEXT, waves=level)
            num = str(round(volume * 100))

        x0, x1 = round(self.SLIDER_X0 * k) * s, round(self.SLIDER_X1 * k) * s
        sh = round(self.SLIDER_H * k) * s
        y0, y1 = cy - sh // 2, cy + sh // 2
        d.rounded_rectangle([x0, y0, x1, y1], (y1 - y0) // 2, fill=self.TRACK)
        if not no_session and volume and volume > 0:
            fill_end = x0 + max((y1 - y0), int((x1 - x0) * volume))
            d.rounded_rectangle([x0, y0, fill_end, y1], (y1 - y0) // 2,
                                fill=self.TRACK if muted else self.ACCENT)

        d.text((round(self.NUM_CENTER_X * k) * s, cy), num, font=self.font_num,
               fill=self.TEXT, anchor="mm")
        return img.resize((self.w, self.h), Image.LANCZOS)

    def _render_pill(self, text, cover=None, dim=False):
        s, k = self.SS, self.scale
        tw = self.font_pill.getbbox(text)[2] // s
        if cover is not None:
            th = self.pill_h - round(8 * k)
            pad_l = round(5 * k)
            w = pad_l + th + round(8 * k) + tw + round(14 * k)
            img, d = self._rounded_base(w, self.pill_h, self.pill_h // 2)
            thumb = cover.resize((th * s, th * s), Image.LANCZOS).convert("RGBA")
            mask = Image.new("L", (th * s, th * s), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, th * s - 1, th * s - 1],
                                                   round(4 * k) * s, fill=255)
            img.paste(thumb, (pad_l * s, (self.pill_h - th) // 2 * s + s), mask)
            d.text(((pad_l + th + round(8 * k)) * s, self.pill_h * s // 2), text,
                   font=self.font_pill, fill="#a6a6a6" if dim else self.TEXT, anchor="lm")
        else:
            w = max(self.pill_h, tw + round(self.PILL_PAD * k))
            img, d = self._rounded_base(w, self.pill_h, self.pill_h // 2)
            d.text((w * s // 2, self.pill_h * s // 2), text, font=self.font_pill,
                   fill="#a6a6a6" if dim else self.TEXT, anchor="mm")
        return img.resize((w, self.pill_h), Image.LANCZOS)

    # ---- Anzeigen / Verstecken (Schnittstelle wie fluneit.OSD) ----

    def show(self, app_name, volume=None, muted=False, no_session=False, kind="app", note=None,
             media_icon=None, media_text=None, media_cover=None, extra_pills=None,
             extra_dim=False):
        import fluneit as core
        self.hide_hint()
        if not core.CONFIG.get("overlay_anzeigen", True):
            return
        if self._fade_job:
            self.root.after_cancel(self._fade_job)
            self._fade_job = None

        if note:
            pill_text = f"{app_name} – {note}"
        elif no_session:
            pill_text = f"{app_name} – kein Audio"
        else:
            pill_text = app_name
        box_key = (None if no_session else round((volume or 0) * 100), muted, no_session, kind,
                   media_icon, media_text)
        box_img = self._box_cache.get(box_key)
        if box_img is None:
            box_img = self._box_cache[box_key] = self._render_box(
                volume, muted, no_session, kind, media_icon, media_text)
        pill_key = (pill_text, media_cover is not None)
        pill_img = self._pill_cache.get(pill_key)
        if pill_img is None:
            pill_img = self._pill_cache[pill_key] = self._render_pill(pill_text, media_cover)
        if len(self._pill_cache) > 64:
            self._pill_cache.clear()

        mx, my, mw, mh = primary_geometry(self.root)
        box_x = mx + (mw - self.w) // 2
        box_y = my + mh - self.bottom_margin - self.h
        pill_x = mx + (mw - pill_img.width) // 2
        pill_y = box_y - self.pill_gap - self.pill_h

        self._last_layers = [(self.box, box_img, box_x, box_y),
                             (self.pill, pill_img, pill_x, pill_y)]

        extras = list(extra_pills or [])
        while len(self.extras) < len(extras):
            self.extras.append(_Layer(self.root))
        for i, text in enumerate(extras):
            key = (text, False, extra_dim)
            img_e = self._pill_cache.get(key)
            if img_e is None:
                img_e = self._pill_cache[key] = self._render_pill(text, dim=extra_dim)
            self._last_layers.append((self.extras[i], img_e,
                                      mx + (mw - img_e.width) // 2,
                                      pill_y - (i + 1) * (self.pill_h + self.pill_gap)))
        for layer in self.extras[len(extras):]:
            layer.hide()

        for layer, img, x, y in self._last_layers:
            layer.push(img, x, y)
        self._visible = True

        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = self.root.after(core.OSD_TIMEOUT_MS, self._hide)

    def show_hint(self, text):
        if text == self._hint_text and self.hint.visible:
            return
        self._hint_text = text
        key = ("hint:" + text, False)
        img = self._pill_cache.get(key)
        if img is None:
            img = self._pill_cache[key] = self._render_pill(text)
        mx, my, mw, mh = primary_geometry(self.root)
        x = mx + (mw - img.width) // 2
        y = my + mh - self.bottom_margin - self.pill_h
        self.hint.push(img, x, y, alpha=200 / 255)

    def hide_hint(self):
        self._hint_text = None
        self.hint.hide()

    def _hide_all_windows(self):
        self.box.hide()
        self.pill.hide()
        for layer in self.extras:
            layer.hide()

    def _hide(self, fade=True):
        self._hide_job = None
        self._visible = False
        if fade and self._last_layers:
            self._fade_step(0)
        else:
            self._hide_all_windows()

    def _fade_step(self, i):
        self._fade_job = None
        if self._visible:
            return
        if i >= len(self.FADE_ALPHAS):
            self._hide_all_windows()
            for layer, _, _, _ in self._last_layers:
                layer.set_alpha(1.0)
            return
        for layer, _, _, _ in self._last_layers:
            layer.set_alpha(self.FADE_ALPHAS[i] / 255)
        self._fade_job = self.root.after(self.FADE_STEP_MS, self._fade_step, i + 1)
