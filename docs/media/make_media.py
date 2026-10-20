"""Renders the README media from FluneIt's own drawing code.

    python docs/media/make_media.py

Windows only (the overlay uses Segoe UI and Segoe Fluent Icons). Needs ffmpeg
on PATH or in the FFMPEG environment variable.

Everything runs in a sandbox: user folders point to a temporary directory and
the user name is "Alex". All apps, devices and the track are invented. The
script stops if FluneIt would read or write its settings outside the sandbox.
Nothing here touches audio devices, Task Scheduler or the registry.

Outputs (next to this script):
  hero.en.gif / hero.de.gif   overlay in four situations, rendered at 2x
  effects.png                 settings, "Effekte" page, effects running (mocked)
  mixer.png                   tray mixer with invented apps
"""
import ctypes
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# --------------------------------------------------------------- sandbox
SANDBOX = pathlib.Path(tempfile.mkdtemp(prefix="fluneit_media_"))
for var in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME", "XDG_STATE_HOME",
            "XDG_CONFIG_HOME"):
    os.environ[var] = str(SANDBOX / var)
    os.makedirs(os.environ[var], exist_ok=True)
for var in ("LOGNAME", "USER", "LNAME", "USERNAME"):
    os.environ[var] = "Alex"
os.environ["FLUNEIT_HOME"] = str(SANDBOX / "home")
import getpass  # noqa: E402

getpass.getuser = lambda: "Alex"
sys.path.insert(0, str(ROOT))

if sys.platform != "win32":
    sys.exit("make_media.py renders with Windows fonts and runs on Windows only")
ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from fluneit import app  # noqa: E402

if not str(app.CONFIG_FILE).startswith(str(SANDBOX)):
    sys.exit(f"abort: settings path outside the sandbox: {app.CONFIG_FILE}")

FPS = 15


# ----------------------------------------------------------- invented data
class FakeVolume:
    def __init__(self, v, muted=False):
        self.v, self.m = v, muted

    def GetMasterVolume(self):
        return self.v

    def SetMasterVolume(self, v, _ctx):
        self.v = v

    def GetMute(self):
        return self.m

    def SetMute(self, m, _ctx):
        self.m = m


class FakeEndpoint(FakeVolume):
    def GetMasterVolumeLevelScalar(self):
        return self.v

    def SetMasterVolumeLevelScalar(self, v, _ctx):
        self.v = v


class FakeSession:
    def __init__(self, v):
        self.SimpleAudioVolume = FakeVolume(v)


APPS = {
    "game": {"name": "Game", "exe": None, "sessions": [FakeSession(0.60)]},
    "music": {"name": "Music", "exe": None, "sessions": [FakeSession(0.35)]},
    "voicechat": {"name": "Voice Chat", "exe": None, "sessions": [FakeSession(0.80)]},
    "browser": {"name": "Browser", "exe": None, "sessions": [FakeSession(0.25)]},
}
DEVICES = [("{dev-1}", "Headphones (USB Audio)"),
           ("{dev-2}", "Speakers (Onboard Audio)"),
           ("{dev-3}", "Digital Output (Onboard Audio)")]


def install_fakes():
    app.collect_audio_apps = lambda: APPS
    app.list_output_devices = lambda: (DEVICES, "{dev-1}")
    app._default_endpoint = lambda *_a, **_k: FakeEndpoint(0.42)
    app.mic_endpoint = lambda *_a, **_k: FakeEndpoint(0.70)
    app.get_app_icon = lambda *_a, **_k: None
    app.set_default_output_device = lambda *_a: sys.exit("abort: device switch")
    app.fx_start = lambda: (False, "demo")
    app.fx_stop = lambda: None
    app.fx_running = lambda: True
    app.fx_bypassed = lambda: False
    app.fx_configured = lambda: True
    app.fx_status = lambda: {"laeuft": True, "quelle": DEVICES[2][1], "ziel": DEVICES[0][1],
                             "latenz_ms": 22.0, "last": 6.0, "aussetzer": 0,
                             "pegel_out": 0.42, "abtastrate": 48000}
    app.fx_mic_status = lambda: {"laeuft": False}
    app.fx_mic_running = lambda: False
    app.autostart_enabled = lambda: True
    app.autostart_status = lambda: (True, "Als Anmelde-Aufgabe eingerichtet, startet 20 s "
                                          "nach dem Anmelden")
    from fluneit import fx_dsp
    p = fx_dsp.preset_params("schritte")
    p["baender"] = fx_dsp.bands_to_ui(p.get("baender"))
    app.CONFIG.update({
        "effekte": p, "effekte_ausgabe": DEVICES[0][1], "effekte_bruecke": DEVICES[2][1],
        "effekte_latenz": "niedrig", "ausgeblendete_apps": [], "ausgeblendete_geraete": [],
    })


# ------------------------------------------------------------ hero (2x)
def make_osd(scale=2.0):
    """An OSD that only draws: same class and drawing code as the app, but
    without creating windows."""
    osd = app.OSD.__new__(app.OSD)
    k = osd.scale = scale
    osd.w, osd.h = round(osd.W * k), round(osd.H * k)
    osd.bottom_margin = round(osd.BOTTOM_MARGIN * k)
    osd.pill_h = round(osd.PILL_H * k)
    osd.pill_gap = round(osd.PILL_GAP * k)
    s = osd.SS
    osd.font_num = app._load_font(["segoeui.ttf"], round(15 * k) * s)
    osd.font_icon = app._load_font(["SegoeIcons.ttf", "segmdl2.ttf"], round(19 * k) * s)
    osd.font_pill = app._load_font(["seguisb.ttf", "segoeui.ttf"], round(13 * k) * s)
    return osd


def cover_art(size=128):
    """Invented album cover: flat colours, so the GIF palette keeps them."""
    img = Image.new("RGB", (size, size), (76, 111, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([size * 0.18, size * 0.18, size * 0.82, size * 0.82], fill=(255, 196, 92))
    d.ellipse([size * 0.42, size * 0.42, size * 0.58, size * 0.58], fill=(76, 111, 255))
    return img


W, H = 1520, 600          # displayed at 760 x 300
TASKBAR = 96


def backdrop():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(28 - 10 * t), int(38 - 12 * t), int(52 - 16 * t)))
    d.rectangle([0, H - TASKBAR, W, H], fill=(32, 32, 32))
    for i in range(5):        # neutral placeholder buttons, no real icons
        x = W // 2 - 2 * 76 + i * 76 - 26
        d.rounded_rectangle([x, H - TASKBAR + 22, x + 52, H - TASKBAR + 74], 10,
                            fill=(58, 58, 58) if i != 2 else (72, 72, 72))
    return img


def font(size, bold=False):
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name),
                              size)


def keycaps(img, keys, label):
    """Demo element (not part of FluneIt): which keys are held."""
    d = ImageDraw.Draw(img)
    f, fl = font(34, bold=True), font(32)
    parts = []
    for i, key in enumerate(keys):
        if i:
            parts.append(("+", None))
        parts.append((key, "cap"))
    widths = [d.textlength(t, font=f) + (44 if kind else 26) for t, kind in parts]
    total = sum(widths) + 40 + d.textlength(label, font=fl)
    x, y = (W - total) // 2, 60
    for (text, kind), w in zip(parts, widths):
        if kind:
            d.rounded_rectangle([x, y, x + w, y + 72], 14, fill=(240, 240, 240),
                                outline=(170, 170, 170), width=3)
            d.text((x + w / 2, y + 36), text, font=f, fill=(25, 25, 25), anchor="mm")
        else:
            d.text((x + w / 2, y + 36), text, font=f, fill=(200, 200, 200), anchor="mm")
        x += w
    d.text((x + 40, y + 36), label, font=fl, fill=(220, 225, 232), anchor="lm")


def compose(osd, keys, label, pill, volume=None, kind="app", extras=(), media=None,
            cover=None, muted=False):
    img = backdrop()
    keycaps(img, keys, label)
    if media:
        box = osd._render_box(None, False, False, "media", media[0], media[1])
    else:
        box = osd._render_box(volume, muted, False, kind)
    pill_img = osd._render_pill(pill, cover)
    bx = (W - box.width) // 2
    by = H - osd.bottom_margin - box.height
    img.paste(box, (bx, by), box)
    py = by - osd.pill_gap - pill_img.height
    img.paste(pill_img, ((W - pill_img.width) // 2, py), pill_img)
    for i, text in enumerate(extras):
        e = osd._render_pill(text, dim=True)
        img.paste(e, ((W - e.width) // 2, py - (i + 1) * (osd.pill_h + osd.pill_gap)), e)
    return img


def scenes(lang):
    t = {"en": {"app": "volume of the app in front", "mic": "microphone",
                "music": "the music app, from any window", "media": "next track",
                "ctrl": "Ctrl", "wheel": "wheel", "shift": "Shift", "alt": "Alt"},
         "de": {"app": "Lautstärke der App im Vordergrund", "mic": "Mikrofon",
                "music": "die Musik-App, aus jedem Fenster", "media": "nächster Titel",
                "ctrl": "Strg", "wheel": "Rad", "shift": "Shift", "alt": "Alt"}}[lang]
    wheel = t["wheel"] + " \u25B2"
    osd = make_osd()
    frames = []

    def ramp(values, hold, **kw):
        for v in values:
            frames.extend([compose(osd, volume=v / 100, **kw)] * 3)
        frames.extend([frames[-1]] * hold)

    # 1) the core idea; its first frame is the poster
    ramp([40, 45, 50, 55, 60], 20, keys=[t["ctrl"], wheel], label=t["app"], pill="Game")
    # 2) microphone
    ramp([80, 75, 70, 65], 18, keys=[t["ctrl"], t["shift"], t["wheel"] + " \u25BC"],
         label=t["mic"], pill="Mikrofon", kind="mic")
    # 3) one music app, others dimmed
    ramp([25, 30, 35, 40], 20, keys=[t["alt"], wheel], label=t["music"], pill="Music",
         extras=["Browser", "\u2190 \u2192  wechseln"])
    # 4) media keys
    frames.extend([compose(osd, keys=[t["shift"], wheel], label=t["media"],
                           pill="Night Drive \u2013 Example Artist",
                           media=("next", "N\u00e4chster Titel"), cover=cover_art())] * 30)
    return frames


def ffmpeg():
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        sys.exit("ffmpeg not found (PATH or FFMPEG)")
    return exe


def write_gif(frames, out):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fluneit_frames_"))
    for i, f in enumerate(frames):
        f.save(tmp / f"f_{i:05d}.png")
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-framerate", str(FPS),
                    "-i", str(tmp / "f_%05d.png"), "-vf",
                    "split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];"
                    "[b][p]paletteuse=dither=none:diff_mode=rectangle",
                    "-loop", "0", str(out)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------- screenshots (Tk)
def grab(widget, path, crop_height=None):
    from ctypes import wintypes
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowDC.restype = wintypes.HDC
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    for _ in range(10):
        widget.update()
        time.sleep(0.03)
    hwnd = user32.GetAncestor(wintypes.HWND(widget.winfo_id()), 2)
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 2)
    bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    if crop_height:
        img = img.crop((0, 0, w, min(h, crop_height)))
    img.save(path, optimize=True)


def screenshots():
    import tkinter as tk

    from fluneit import ui
    install_fakes()
    root = tk.Tk()
    root.withdraw()
    ui.init(app, root)
    app.fx_modules()

    win = ui.SettingsWindow(root, "effekte")
    win.geometry("760x900+3000+0")             # off screen
    grab(win, HERE / "effects.png", crop_height=852)   # ends below the equalizer
    win.destroy()

    fl = ui.Flyout(root, 1.0)
    fl._build()
    fl._place()
    fl.win.geometry(f"+3000+0")                # off screen instead of above the tray
    fl.win.deiconify()
    grab(fl.inner, HERE / "mixer.png")
    root.destroy()


def main():
    for lang in ("en", "de"):
        write_gif(scenes(lang), HERE / f"hero.{lang}.gif")
    screenshots()
    for name in ("hero.en.gif", "hero.de.gif", "effects.png", "mixer.png"):
        p = HERE / name
        print(f"{name:12} {p.stat().st_size / 1024:7.0f} KB")
    shutil.rmtree(SANDBOX, ignore_errors=True)


if __name__ == "__main__":
    main()
