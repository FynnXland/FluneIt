"""Fluneit - Per-App-Lautstaerke ueber das Lautstaerkerad der Tastatur.

Laeuft unter Windows (Low-Level-Hook, WASAPI/pycaw) und Linux (X11-Grabs,
PulseAudio/PipeWire). Plattformspezifisches steckt hinter IS_WINDOWS bzw. in
den linux_*-Modulen; alles darueber ist gemeinsamer Code.

Standardbelegung (frei konfigurierbar, s. DEFAULT_CONFIG):
  Rad normal drehen      -> System-Lautstaerke
  Strg + Rad             -> App im Vordergrund, mit eigenem Overlay
  Strg + Shift + Rad     -> Mikrofon
  Shift + Rad            -> Medien: Titel vor/zurueck (Stumm-Taste = Play/Pause)
  Shift + Alt + Rad      -> im Titel spulen
  Alt + Rad              -> die ausgewaehlte Musik-App (Pfeiltasten wechseln)
  Strg + Alt + Rad       -> Kommunikations-Apps (Discord, TeamSpeak, ...)
  Strg + Numpad-Ziffer   -> frei belegbare Hotkeys
  Klick auf Tray-Symbol  -> Mixer (alle Apps mit Audio, Slider + Stumm)

Das Overlay ist ein pixelgenauer Nachbau der Windows-11-Lautstaerkeanzeige und
erscheint an exakt derselben Position. Ist die echte Windows-Anzeige gerade noch
sichtbar, wird sie ausgeblendet; aendert man danach die System-Lautstaerke,
verschwindet unser Overlay (die jeweils neueste Aktion gewinnt).

Einstellungen und App-Regeln in config.json (neben dem Programm, sonst im
Benutzerordner), Steuerung ueber das Symbol im Infobereich (Tray).
"""

import ctypes
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk

import psutil
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
else:
    import linux_audio
    import linux_icons
    import linux_input
    import linux_media

__version__ = "1.17.0"

# ----------------------------- Pfade & Konfiguration ------------------------

def app_dir():
    if getattr(sys, "frozen", False):          # als PyInstaller-Exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """Beschreibbarer Ordner pro Benutzer - Rueckfallebene, wenn der
    Programmordner nicht beschrieben werden kann (Program Files, defektes
    Dateisystem, schreibgeschuetzter Stick)."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "Fluneit")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        d = os.path.join(base, "fluneit")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return d


APP_DIR = app_dir()
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
LOG_FILE = os.path.join(APP_DIR, "fluneit.log")


def _log_path_usable(path):
    """Laesst sich dort wirklich schreiben UND wieder lesen?

    Ein blosser Oeffnen-Versuch reicht nicht: die Datei im Programmordner
    ist hier auf NTFS-Ebene beschaedigt, und je nach aufrufendem Prozess
    gelingt das Oeffnen trotzdem - geschriebene Zeilen sind danach aber
    nicht mehr auffindbar. Genau so verschwand ein Startprotokoll spurlos.
    """
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("")
            f.flush()
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.read(1)
        return True
    except Exception:
        return False


def setup_logging():
    """Datei-Log einrichten. Schlaegt jeder Pfad fehl (z. B. weil die Datei auf
    NTFS-Ebene beschaedigt ist), laeuft Fluneit ohne Datei-Log weiter - der
    Start darf daran niemals scheitern."""
    fmt = "%(asctime)s %(levelname)s %(message)s"
    # Benutzerordner zuerst, Programmordner nur als Rueckfall. Umgekehrt ist
    # es anfaellig: eine beschaedigte Datei im Programmordner laesst sich je
    # nach startendem Prozess mal oeffnen und mal nicht - dann landen
    # Startmeldungen mal hier, mal dort, mal nirgends. Genau daran war nicht
    # nachvollziehbar, ob Fluneit beim Anmelden hochkam.
    candidates = []
    d = data_dir()
    if d:
        candidates.append(os.path.join(d, "fluneit.log"))
    candidates.append(LOG_FILE)
    for path in candidates:
        if not _log_path_usable(path):
            continue
        try:
            handler = logging.FileHandler(path, encoding="utf-8", delay=False)
        except Exception:
            continue
        handler.setFormatter(logging.Formatter(fmt))
        root = logging.getLogger()
        # INFO statt WARNING: pro Start eine Zeile ist die einzige Spur, an
        # der sich spaeter ablesen laesst, ob Fluneit beim Anmelden ueberhaupt
        # hochkam. Ohne die tappt man bei "Autostart geht nicht" im Dunkeln.
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        if path == LOG_FILE and d:
            root.warning("Benutzerordner nicht nutzbar, schreibe nach %s", path)
        return path
    logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stderr)
    return None


def started_by_autostart():
    """Wurde Fluneit von der Anmelde-Aufgabe gestartet? Die uebergibt
    --autostart, damit im Log steht, wie der Start zustande kam."""
    return "--autostart" in sys.argv[1:]

DEFAULT_CONFIG = {
    "modifier": "strg",            # App-Lautstaerke: einzeln oder Kombi (z. B. "strg")
    "mikrofon_modifier": "strg+shift",  # Mikrofon (z. B. "strg+shift"; "" = aus)
    "schrittweite_prozent": 5,     # Aenderung pro Rad-Tick
    "anzeige_dauer_ms": 1500,      # wie lange das Overlay stehen bleibt
    "overlay_anzeigen": True,      # Overlay beim Regeln einblenden
    "system_overlay": True,        # Windows-Lautstaerkeanzeige unterdruecken, eigene "System"-Pille zeigen
    "runden_auf": 5,               # nach dem Regeln auf Vielfaches runden (0 = aus)
    "medien_steuerung": True,      # Medien-Steuerung an/aus
    "medien_modifier": "shift",    # Medien: Rad = Titel, Stumm = Play/Pause; + Alt + Rad = spulen
    "hintergrund_modifier": "alt", # regelt die Musik-App(s) mit aktiver Wiedergabe ("" = aus)
    "spulen_sekunden": 10,         # Spul-Schritt (Medien-Taste + Alt + Rad)
    "modus_hinweis": True,         # beim Halten einer Taste kurz zeigen, was das Rad regelt
    "ausgeblendete_apps": [],      # Prozessnamen, die der Mixer nicht anzeigt
    "ausgeblendete_geraete": [],   # Ausgabegeraete ({"id", "name"}), die der Mixer nicht anzeigt
    "onboarding_gezeigt": False,   # Erststart-Fenster schon gezeigt?
    # Beispiel-Regeln (app = Prozessname):
    #   {"app": "discord.exe", "typ": "startlautstaerke", "wert": 40}
    #   {"app": "spotify.exe", "typ": "stumm"}
    #   {"app": "game.exe",    "typ": "ausschliessen"}
    "regeln": [],
    # Strg + Numpad -> frei belegbare Aktionen. Jede Bindung:
    #   {"taste": "1", "typ": "programm"|"website"|"ordner"|"befehl"|"setup",
    #    "ziel": "<pfad/url/befehl>" oder (bei setup) [ {"typ","ziel"}, ... ],
    #    "name": "Anzeigename"}
    "hotkeys_modifier": "strg",
    "hotkeys": [],
    # Kommunikations-Apps (Discord, TeamSpeak, ...) gemeinsam regeln
    "kommunikation_modifier": "strg+alt",
    "kommunikations_apps": ["discord.exe", "vesktop.exe", "ts3client_win64.exe",
                            "ts5client.exe", "teamspeak.exe", "teamspeak3.exe",
                            "slack.exe", "zoom.exe", "ms-teams.exe", "teams.exe",
                            "mumble.exe", "skype.exe", "element.exe", "whatsapp.exe",
                            # Linux-Prozessnamen (Vergleich ohne ".exe", s. _norm)
                            "ts3client_linux_amd64", "signal-desktop", "webcord"],
    # Alt + Rad regelt genau EINE Musik-App; Auswahl wird gemerkt
    "musik_app_auswahl": "",
    # --- Audio-Effekte (EQ, Rauschunterdrueckung, ...) ---
    # Standardmaessig komplett aus: wer das nicht braucht, merkt nichts davon.
    "effekte_aktiv": False,
    "effekte_bruecke": "",          # Geraet, auf das Windows spielt (unhoerbar)
    "effekte_ausgabe": "",          # echtes Ausgabegeraet (Kopfhoerer)
    "effekte_latenz": "mittel",     # niedrig | mittel | sicher
    "effekte": {},                  # Parametersatz, s. fx_dsp.FxChain
    "effekte_wiederherstellen": "", # Geraet, das nach dem Stopp zurueck muss
    "effekte_mikrofon_aktiv": False,
    "effekte_mikrofon_quelle": "",
    "effekte_mikrofon_ausgabe": "",
    "effekte_mikrofon": {},
}

_MODIFIER_VKS = {"shift": 0x10, "strg": 0x11, "ctrl": 0x11, "alt": 0x12}


def _norm(name):
    """Prozessname fuer Vergleiche: kleingeschrieben, ohne ".exe". Dadurch
    matchen Config-Eintraege wie "spotify.exe" auf beiden Plattformen."""
    n = str(name).lower()
    return n[:-4] if n.endswith(".exe") else n


def _parse_mods(spec):
    """'strg+shift' -> frozenset({0x11, 0x10}); '' / 'aus' -> None."""
    if not spec:
        return None
    vks = set()
    for part in str(spec).lower().replace(" ", "").split("+"):
        if part in ("", "aus"):
            return None
        vk = _MODIFIER_VKS.get(part)
        if vk is None:
            return None
        vks.add(vk)
    return frozenset(vks) if vks else None


def _write_config(cfg):
    """Config schreiben; klappt der Programmordner nicht, in den
    Benutzerordner ausweichen (und ab dann dort bleiben)."""
    global CONFIG_FILE
    paths = [CONFIG_FILE]
    d = data_dir()
    if d:
        alt = os.path.join(d, "config.json")
        if alt not in paths:
            paths.append(alt)
    for path in paths:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except OSError:
            continue
        CONFIG_FILE = path
        return True
    return False


def load_config():
    global CONFIG_FILE
    cfg = dict(DEFAULT_CONFIG)
    # Zuerst neben dem Programm, sonst im Benutzerordner suchen
    d = data_dir()
    if not os.path.exists(CONFIG_FILE) and d:
        alt = os.path.join(d, "config.json")
        if os.path.exists(alt):
            CONFIG_FILE = alt
    loaded = None
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        cfg.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError):
        logging.warning("config.json unlesbar, Standardwerte werden benutzt")
        return cfg
    # Ausgeblendete Apps auf die plattformneutrale Schreibweise bringen
    # ("spotify.exe" -> "spotify"), damit dieselbe config.json unter Windows
    # und Linux greift. Reihenfolge bleibt, Duplikate fallen weg.
    old_hidden = cfg.get("ausgeblendete_apps") or []
    new_hidden, seen = [], set()
    for a in old_hidden:
        n = _norm(a)
        if n and n not in seen:
            seen.add(n)
            new_hidden.append(n)
    cfg["ausgeblendete_apps"] = new_hidden

    # Datei um neu hinzugekommene Optionen ergaenzen (Werte bleiben erhalten)
    if loaded is None or new_hidden != list(old_hidden) \
            or any(k not in loaded for k in DEFAULT_CONFIG):
        _write_config(cfg)
    return cfg


CONFIG = load_config()
RULES_BY_APP = {}
EXCLUDED_APPS = set()


def apply_config():
    """Uebernimmt CONFIG-Werte in die laufenden Einstellungen (auch zur Laufzeit)."""
    global APP_VOL_STEP, OSD_TIMEOUT_MS, MODIFIER_VK, MIC_MODIFIER_VK, ROUND_TO
    APP_VOL_STEP = max(1, int(CONFIG["schrittweite_prozent"])) / 100
    OSD_TIMEOUT_MS = max(300, int(CONFIG["anzeige_dauer_ms"]))
    ROUND_TO = max(0, int(CONFIG.get("runden_auf", 0)))
    global HOOK_FUNCS, VK_ALT
    VK_ALT = 0x12
    app_vks = _parse_mods(CONFIG.get("modifier", "strg")) or frozenset({0x11})
    mic_vks = _parse_mods(CONFIG.get("mikrofon_modifier", ""))
    media_on = bool(CONFIG.get("medien_steuerung", False))
    media_vks = _parse_mods(CONFIG.get("medien_modifier", "")) if media_on else None
    bg_vks = _parse_mods(CONFIG.get("hintergrund_modifier", ""))
    global COMM_APPS
    COMM_APPS = {_norm(x) for x in CONFIG.get("kommunikations_apps", [])}
    comm_vks = _parse_mods(CONFIG.get("kommunikation_modifier", ""))
    # Fuer den Musik-App-Wechsel per Pfeiltasten (Windows-Hook prueft die
    # Taste einzeln, Linux grabbt die volle Kombination)
    global BG_MODIFIER_VK, BG_MOD_VKS
    BG_MOD_VKS = bg_vks or frozenset()
    BG_MODIFIER_VK = next(iter(bg_vks)) if bg_vks else 0
    seek_vks = frozenset(media_vks | {VK_ALT}) if media_vks else None  # Medien + Alt = spulen

    # Jede Funktion mit ihrer Tastenkombination; im Hook wird die
    # spezifischste (meiste Tasten) zuerst geprueft, damit z. B. Strg+Shift
    # (Mikrofon) vor Strg (App) und Shift (Medien) gewinnt.
    funcs = []
    if seek_vks:
        funcs.append((seek_vks, "seek"))
    if mic_vks:
        funcs.append((mic_vks, "mic"))
    if comm_vks and COMM_APPS:
        funcs.append((comm_vks, "comm"))
    if media_vks:
        funcs.append((media_vks, "media"))
    funcs.append((app_vks, "app"))
    if bg_vks:
        funcs.append((bg_vks, "bg"))
    # doppelte Tastenkombis vermeiden (erste Definition gewinnt)
    seen, unique = set(), []
    for vkset, kind in funcs:
        if vkset in seen:
            continue
        seen.add(vkset)
        unique.append((vkset, kind))
    unique.sort(key=lambda f: len(f[0]), reverse=True)
    HOOK_FUNCS = unique
    global HOTKEYS_MODIFIER_VK, HOTKEYS_BY_DIGIT
    HOTKEYS_MODIFIER_VK = _MODIFIER_VKS.get(str(CONFIG.get("hotkeys_modifier", "strg")).lower(), 0x11)
    HOTKEYS_BY_DIGIT = {}
    for h in CONFIG.get("hotkeys", []):
        if isinstance(h, dict) and str(h.get("taste", "")) in "0123456789" and h.get("taste") != "":
            HOTKEYS_BY_DIGIT[str(h["taste"])] = h
    rebuild_rules()
    if not IS_WINDOWS:
        # X11-Grabs an die neue Belegung anpassen (no-op, solange der
        # Grab-Thread noch nicht laeuft; main() ruft danach erneut auf)
        try:
            linux_input.update_bindings(HOOK_FUNCS, HOTKEYS_MODIFIER_VK,
                                        set(HOTKEYS_BY_DIGIT))
        except Exception:
            logging.exception("Tasten-Grabs konnten nicht aktualisiert werden")


def rebuild_rules():
    global RULES_BY_APP, EXCLUDED_APPS
    rules = {}
    for r in CONFIG.get("regeln", []):
        if isinstance(r, dict) and r.get("app"):
            rules.setdefault(_norm(r["app"]), []).append(r)
    RULES_BY_APP = rules
    EXCLUDED_APPS = {a for a, rs in rules.items()
                     if any(x.get("typ") == "ausschliessen" for x in rs)}


def save_config():
    if not _write_config(CONFIG):
        logging.error("config.json konnte nirgends gespeichert werden")


apply_config()

# ----------------------------- Ereignis-Queue -------------------------------

event_queue: "queue.Queue" = queue.Queue()


def _post_to_ui(fn):
    """Aus Worker-Threads: Funktion im Tk-Thread ausfuehren (via Event-Queue)."""
    event_queue.put(fn)


# Zeitfenster nach einer Lautstaerketaste, in dem das dann erscheinende
# Windows-OSD unterdrueckt werden soll (nur Windows relevant; Linux laesst
# die System-Lautstaerketasten komplett bei KDE).
_expect_osd_until = 0.0
_osd_last_caught = 0.0


if IS_WINDOWS:
    # ----------------------------- Windows-Konstanten ---------------------------

    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104
    WM_KEYUP = 0x0101
    WM_SYSKEYUP = 0x0105
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    VK_LBUTTON = 0x01
    VK_ESCAPE = 0x1B

    WS_POPUP = 0x80000000
    GWL_EXSTYLE = -20
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TRANSPARENT = 0x00000020   # Mausklicks gehen durch das Overlay hindurch
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000
    ULW_ALPHA = 2
    SW_HIDE = 0
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    SWP_SHOWWINDOW = 0x0040
    GA_ROOT = 2
    ERROR_ALREADY_EXISTS = 183
    SPI_GETWORKAREA = 48
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUND = 2
    DI_NORMAL = 3
    SHGFI_ICON = 0x100
    SHGFI_LARGEICON = 0x0

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        dwmapi = None

    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    # Feature 3: das native Lautstaerke-OSD abfangen (wie HideVolumeOSD, aber
    # ereignisgesteuert statt per Polling - kein zusaetzlicher CPU-Verbrauch).
    EVENT_OBJECT_SHOW = 0x8002
    WINEVENT_OUTOFCONTEXT = 0x0000
    WINEVENT_SKIPOWNPROCESS = 0x0002
    _OSD_CLASSES = ("XamlExplorerHostIslandWindow", "NativeHWNDHost")
    WINEVENTPROC = ctypes.WINFUNCTYPE(
        None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
        wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    user32.SetWinEventHook.restype = wintypes.HANDLE
    user32.SetWinEventHook.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
                                       WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)

    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
    user32.CallNextHookEx.restype = LRESULT
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.UpdateLayeredWindow.argtypes = (
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
        wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.COLORREF, ctypes.c_void_p, wintypes.DWORD,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.DrawIconEx.restype = wintypes.BOOL
    user32.DrawIconEx.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HANDLE, wintypes.UINT)
    user32.DestroyIcon.argtypes = (wintypes.HANDLE,)
    user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    user32.DefWindowProcW.restype = LRESULT
    user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    )


    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]


    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", ctypes.c_ubyte),
            ("BlendFlags", ctypes.c_ubyte),
            ("SourceConstantAlpha", ctypes.c_ubyte),
            ("AlphaFormat", ctypes.c_ubyte),
        ]


    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]


    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [
            ("hIcon", wintypes.HANDLE),
            ("iIcon", ctypes.c_int),
            ("dwAttributes", wintypes.DWORD),
            ("szDisplayName", ctypes.c_wchar * 260),
            ("szTypeName", ctypes.c_wchar * 80),
        ]


    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]


    # Trampolin auf DefWindowProc; Referenz global halten (sonst GC)
    _osd_wndproc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
    _OSD_CLASS_NAME = "FluneitOSD"
    _osd_class_registered = False


    def _register_osd_window_class():
        global _osd_class_registered
        if _osd_class_registered:
            return
        wc = WNDCLASSW()
        wc.lpfnWndProc = _osd_wndproc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = _OSD_CLASS_NAME
        user32.RegisterClassW(ctypes.byref(wc))
        _osd_class_registered = True


    # ----------------------------- Tastatur-Hook --------------------------------
    _VK_TO_EVENT = {VK_VOLUME_UP: "up", VK_VOLUME_DOWN: "down", VK_VOLUME_MUTE: "mute"}
    # Numpad-Ziffern per Scancode (unabhaengig von NumLock; Nav-Cluster ist "extended")
    _NUMPAD_SCAN = {0x52: "0", 0x4F: "1", 0x50: "2", 0x51: "3", 0x4B: "4",
                    0x4C: "5", 0x4D: "6", 0x47: "7", 0x48: "8", 0x49: "9"}


    def _all_down(vkset):
        return all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in vkset)


    def _hook_proc(n_code, w_param, l_param):
        if n_code == 0 and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode
            # Pfeiltasten wechseln die Musik-App - aber NUR solange das
            # Musik-Overlay sichtbar ist (sonst bliebe z. B. Alt+Links im
            # Browser die normale Zurueck-Navigation)
            if vk in (0x25, 0x27) and BG_MOD_VKS \
                    and time.monotonic() < _bg_ui_until \
                    and all(user32.GetAsyncKeyState(v) & 0x8000 for v in BG_MOD_VKS):
                event_queue.put("bg_prev" if vk == 0x25 else "bg_next")
                return 1
            # Strg + Numpad-Ziffer -> belegte Aktion (Scancode + nicht-extended)
            if HOTKEYS_MODIFIER_VK and not (kb.flags & 0x01):
                digit = _NUMPAD_SCAN.get(kb.scanCode)
                if digit is not None and digit in HOTKEYS_BY_DIGIT \
                        and (user32.GetAsyncKeyState(HOTKEYS_MODIFIER_VK) & 0x8000):
                    event_queue.put("hotkey_" + digit)
                    return 1  # Zifferneingabe schlucken
            if vk in _VK_TO_EVENT:
                ev = _VK_TO_EVENT[vk]
                # spezifischste Kombi zuerst (HOOK_FUNCS ist danach sortiert)
                for vkset, kind in HOOK_FUNCS:
                    if not _all_down(vkset):
                        continue
                    if kind == "app":
                        event_queue.put(ev)
                    elif kind == "mic":
                        event_queue.put("mic_" + ev)
                    elif kind == "bg":
                        event_queue.put("bg_" + ev)
                    elif kind == "comm":
                        event_queue.put("comm_" + ev)
                    elif kind == "media":
                        event_queue.put("media_" + ev)
                    elif kind == "seek":
                        if vk == VK_VOLUME_MUTE:
                            event_queue.put("media_mute")  # Stumm bleibt Play/Pause
                        else:
                            event_queue.put("media_seek_up" if vk == VK_VOLUME_UP else "media_seek_down")
                    return 1  # Taste schlucken, Windows soll nichts zusaetzlich tun
                if vk != VK_VOLUME_MUTE:
                    # normale Lautstaerketaste: an Windows durchreichen, aber das
                    # native OSD unterdruecken und unsere System-Anzeige planen
                    global _expect_osd_until
                    if CONFIG.get("system_overlay", True):
                        _expect_osd_until = time.monotonic() + 0.5
                    event_queue.put("sys_tick")
        return user32.CallNextHookEx(None, n_code, w_param, l_param)


    # Referenz behalten, sonst raeumt der Garbage Collector den Callback weg
    _hook_proc_ref = HOOKPROC(_hook_proc)



    def _winevent_proc(hHook, event, hwnd, idObj, idChild, thread, time_):
        if idObj != 0 or not CONFIG.get("system_overlay", True):
            return
        if time.monotonic() >= _expect_osd_until:
            return  # keine Lautstaerketaste kurz zuvor -> nicht eingreifen
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buf, 64)
        if buf.value not in _OSD_CLASSES:
            return
        # Geometrie-Sicherung: nur die kleine, unten-mittige OSD-Kachel verstecken
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        w = r.right - r.left
        if w and w < 500 and r.top > sh * 0.55 and abs((r.left + r.right) // 2 - sw // 2) < sw * 0.25:
            user32.ShowWindow(hwnd, SW_HIDE)
            global _osd_last_caught
            _osd_last_caught = time.monotonic()


    _winevent_proc_ref = WINEVENTPROC(_winevent_proc)


    def hook_thread():
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _hook_proc_ref, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            raise ctypes.WinError(ctypes.get_last_error())
        # OSD-Suppression im selben Thread (dessen GetMessage-Schleife pumpt die
        # WinEvents); haengt der Aufruf mal fehl, laeuft der Tasten-Hook weiter.
        try:
            user32.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, None, _winevent_proc_ref,
                                   0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        except Exception:
            logging.exception("OSD-Suppression konnte nicht eingerichtet werden")
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))



# ----------------------------- Audio-Endpunkte ------------------------------

def _default_endpoint(dataflow, role=0):
    """Lautstaerke-Endpunkt des Standardgeraets (dataflow: 0=Wiedergabe, 1=Aufnahme).
    Windows: IAudioEndpointVolume; Linux: pulsectl-Wrapper mit gleicher API."""
    if not IS_WINDOWS:
        return linux_audio.default_endpoint(dataflow)
    devenum = AudioUtilities.GetDeviceEnumerator()
    dev = devenum.GetDefaultAudioEndpoint(dataflow, role)
    return ctypes.cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
                       ctypes.POINTER(IAudioEndpointVolume))


def get_all_audio_sessions():
    """Alle App-Audio-Sessions, plattformuebergreifend (pycaw bzw. Pulse)."""
    if IS_WINDOWS:
        return AudioUtilities.GetAllSessions()
    return linux_audio.get_all_sessions()


_mic_endpoint = None


def mic_endpoint(refresh=False):
    global _mic_endpoint
    if _mic_endpoint is None or refresh:
        _mic_endpoint = _default_endpoint(1, 0)  # eCapture, eConsole
    return _mic_endpoint


# ----------------------------- Vordergrund-App ------------------------------

if IS_WINDOWS:
    def _resolve_uwp_pid(hwnd, host_pid):
        """UWP-Apps (z. B. Media Player) laufen hinter ApplicationFrameHost.exe.
        Der echte App-Prozess steckt in einem Kindfenster mit anderer PID."""
        found = []

        @WNDENUMPROC
        def cb(child, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
            if pid.value and pid.value != host_pid:
                found.append(pid.value)
                return False
            return True

        user32.EnumChildWindows(hwnd, cb, 0)
        return found[0] if found else None


    def get_foreground_process():
        """Liefert (pid, name) des Prozesses, dessen Fenster gerade den Fokus hat."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None, None
        try:
            name = psutil.Process(pid.value).name()
            if name.lower() == "applicationframehost.exe":
                real = _resolve_uwp_pid(hwnd, pid.value)
                if real:
                    return real, psutil.Process(real).name()
            return pid.value, name
        except psutil.Error:
            return None, None
else:
    def get_foreground_process():
        """Liefert (pid, name) des fokussierten Fensters (X11, _NET_ACTIVE_WINDOW)."""
        return linux_input.get_foreground_process()


def find_audio_sessions(pid, name):
    """Alle Audio-Sitzungen der fokussierten App. Schnellpfad: PID- oder
    Namens-Treffer; nur wenn nichts passt, wird der (teure) Prozessbaum
    durchsucht (z. B. App startet Audio ueber einen Subprozess)."""
    sessions = get_all_audio_sessions()
    name_l = name.lower()
    matches = []
    for session in sessions:
        proc = session.Process
        if proc is None:
            continue
        try:
            if proc.pid == pid or proc.name().lower() == name_l:
                matches.append(session)
        except psutil.Error:
            continue
    if matches:
        return matches
    try:
        candidate_pids = {c.pid for c in psutil.Process(pid).children(recursive=True)}
    except psutil.Error:
        return []
    for session in sessions:
        proc = session.Process
        if proc is None:
            continue
        try:
            if proc.pid in candidate_pids:
                matches.append(session)
        except psutil.Error:
            continue
    return matches


# ----------------------------- App-Icons ------------------------------------

if IS_WINDOWS:
    def _hicon_to_image(hicon, size=32):
        screen_dc = user32.GetDC(None)
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        old = gdi32.SelectObject(mem_dc, hbmp)
        user32.DrawIconEx(mem_dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        buf = ctypes.create_string_buffer(size * size * 4)
        ctypes.memmove(buf, bits, len(buf))
        img = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)
        gdi32.SelectObject(mem_dc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        if img.getextrema()[3][1] == 0:  # Icon ohne Alphakanal
            alpha = img.convert("L").point(lambda v: 255 if v > 0 else 0)
            img.putalpha(alpha)
        return img


    def get_app_icon(exe_path, size=24):
        """Programm-Icon einer Exe als PIL-Bild (oder None)."""
        if not exe_path:
            return None
        try:
            fi = SHFILEINFOW()
            res = shell32.SHGetFileInfoW(exe_path, 0, ctypes.byref(fi), ctypes.sizeof(fi),
                                         SHGFI_ICON | SHGFI_LARGEICON)
            if not res or not fi.hIcon:
                return None
            img = _hicon_to_image(fi.hIcon, 32)
            user32.DestroyIcon(fi.hIcon)
            return img.resize((size, size), Image.LANCZOS)
        except Exception:
            return None
else:
    def get_app_icon(exe_path, size=24):
        """Programm-Icon als PIL-Bild (oder None) - Linux: Desktop-Dateien/Themes."""
        try:
            return linux_icons.get_app_icon(exe_path, size)
        except Exception:
            return None


def fallback_app_icon(letter, size=24, color="#4cc2ff"):
    ss = 4
    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size * ss - 1, size * ss - 1], fill=color)
    f = _load_font(["seguisb.ttf", "segoeui.ttf",
                    "NotoSans-Bold.ttf", "Ubuntu-B.ttf", "DejaVuSans-Bold.ttf"],
                   int(size * ss * 0.55))
    d.text((size * ss // 2, size * ss // 2), letter.upper(), font=f, fill="#1a1a1a", anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


# ----------------------------- Overlay (OSD) --------------------------------

def _load_font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


if IS_WINDOWS:
    class OSD:
        """Nachbau der Windows-11-Lautstaerkeanzeige (Position und Optik pixelgenau
        vermessen), plus eine Pille darueber mit dem Namen der App.

        Gezeichnet wird per Layered Window mit Per-Pixel-Alpha, dadurch sind die
        runden Ecken sauber (kein schwarzer Rand) und Klicks gehen hindurch."""

        # Am echten Windows-OSD vermessen (bei 100 % Skalierung; skaliert mit DPI):
        W, H = 194, 55            # Groesse der Box
        BOTTOM_MARGIN = 55        # Abstand Unterkante Box -> unterer Bildschirmrand
        RADIUS = 9
        BG = "#2d2d2c"
        BORDER = "#3f3f3e"
        ACCENT = "#4cc2ff"        # Windows-Akzentblau des Sliders
        TRACK = "#8a8a8a"
        TEXT = "#ffffff"
        SLIDER_X0, SLIDER_X1 = 46, 150   # Track endet frueher, damit auch "100" Luft hat
        SLIDER_H = 4
        NUM_CENTER_X = 171               # Prozentzahl mittig in der Zone rechts vom Track
        ICON_X = 14
        PILL_H = 30
        PILL_GAP = 8              # Abstand zwischen Pille und Box
        PILL_PAD = 28

        SS = 2                    # Supersampling fuer glatte Kanten
        FADE_ALPHAS = (200, 140, 80, 30)  # sanftes Ausblenden
        FADE_STEP_MS = 30

        # Segoe-Fluent-Icons: Lautsprecher mit 0-3 Schallwellen, stumm, Mikrofon
        ICON_VOL = ["", "", "", ""]
        ICON_MUTE = ""
        ICON_MIC = ""
        ICON_MIC_MUTE = ""
        ICON_MEDIA = {"next": "", "prev": "", "play": "", "pause": "",
                      "fwd": "", "rew": ""}

        WINDOWS_OSD_CLASS = "XamlExplorerHostIslandWindow"

        def __init__(self, root: tk.Tk):
            self.root = root
            try:
                self.scale = user32.GetDpiForSystem() / 96.0
            except Exception:
                self.scale = 1.0
            k = self.scale
            self.w, self.h = round(self.W * k), round(self.H * k)
            self.bottom_margin = round(self.BOTTOM_MARGIN * k)
            self.pill_h = round(self.PILL_H * k)
            self.pill_gap = round(self.PILL_GAP * k)

            s = self.SS
            self.font_num = _load_font(["segoeui.ttf"], round(15 * k) * s)
            self.font_icon = _load_font(["SegoeIcons.ttf", "segmdl2.ttf"], round(19 * k) * s)
            self.font_pill = _load_font(["seguisb.ttf", "segoeui.ttf"], round(13 * k) * s)

            self.box_hwnd = self._make_layered_window()
            self.pill_hwnd = self._make_layered_window()
            self.extra_hwnds = []  # weitere Pillen (Multi-App-Regelung), bei Bedarf erzeugt
            self.hint_hwnd = self._make_layered_window()  # dezenter Modus-Hinweis
            self._hint_text = None
            self._hide_job = None
            self._watch_job = None
            self._fade_job = None
            self._visible = False
            self._windows_osd_hwnd = None
            self._last_pushes = []
            # Fertig gerenderte Bilder wiederverwenden: beim schnellen Drehen am Rad
            # wird jede Lautstaerkestufe nur einmal gezeichnet
            self._box_cache = {}
            self._pill_cache = {}

        # ---- Layered-Window-Verwaltung ----

        def _make_layered_window(self):
            # Bewusst ein natives Win32-Fenster statt eines Tk-Toplevels: Tk setzt
            # seine Fensterstile bei jedem Anzeigen neu und bricht damit den
            # UpdateLayeredWindow-Modus (Per-Pixel-Alpha).
            _register_osd_window_class()
            hwnd = user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                | WS_EX_TRANSPARENT | WS_EX_TOPMOST,
                _OSD_CLASS_NAME, "", WS_POPUP,
                0, 0, 10, 10, None, None, kernel32.GetModuleHandleW(None), None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            return hwnd

        def _push_image(self, hwnd, img, x, y, alpha=255):
            """Zeichnet ein RGBA-Bild mit echter Transparenz in das Layered Window."""
            w, h = img.size
            r, g, b, a = img.split()  # UpdateLayeredWindow erwartet vormultipliziertes Alpha
            pre = Image.merge("RGBA", (ImageChops.multiply(r, a),
                                       ImageChops.multiply(g, a),
                                       ImageChops.multiply(b, a), a))
            data = pre.tobytes("raw", "BGRA")

            screen_dc = user32.GetDC(None)
            mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(mem_dc, hbmp)

            blend = BLENDFUNCTION(0, 0, alpha, 1)  # AC_SRC_OVER, per-pixel AC_SRC_ALPHA
            pos = wintypes.POINT(x, y)
            size = wintypes.SIZE(w, h)
            src = wintypes.POINT(0, 0)
            user32.UpdateLayeredWindow(hwnd, screen_dc, ctypes.byref(pos), ctypes.byref(size),
                                       mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)

            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(None, screen_dc)

        # ---- Umgang mit der echten Windows-Anzeige ----

        def _find_windows_osd(self):
            """Sucht das Fenster der echten Windows-Lautstaerkeanzeige (nur auffindbar,
            wenn es gerade sichtbar ist) und merkt sich das Handle."""
            h = self._windows_osd_hwnd
            if h and user32.IsWindow(h):
                return h
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            pt = wintypes.POINT(sw // 2, sh - self.bottom_margin - self.h // 2)
            probe = user32.WindowFromPoint(pt)
            if probe:
                top = user32.GetAncestor(probe, GA_ROOT)
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(top, cls, 64)
                if cls.value == self.WINDOWS_OSD_CLASS:
                    self._windows_osd_hwnd = top
                    return top
            return None

        def _windows_osd_visible(self):
            h = self._find_windows_osd()
            return bool(h and user32.IsWindowVisible(h))

        def _watch_windows_osd(self):
            """Solange unser Overlay steht: Taucht die Windows-Anzeige auf (weil die
            System-Lautstaerke geaendert wurde), zieht sich unser Overlay zurueck."""
            self._watch_job = None
            if not self._visible:
                return
            if self._windows_osd_visible():
                self._hide(fade=False)  # sofort weg, die Windows-Anzeige uebernimmt
            else:
                self._watch_job = self.root.after(150, self._watch_windows_osd)

        # ---- Rendern ----

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

            if kind == "media":
                # Aktions-Icon + Text statt Slider (z. B. "Naechster Titel")
                d.text((round(self.ICON_X * k) * s, cy), self.ICON_MEDIA.get(media_icon, ""),
                       font=self.font_icon, fill=self.TEXT, anchor="lm")
                d.text((round((self.ICON_X + 32) * k) * s, cy), media_text or "",
                       font=self.font_num, fill=self.TEXT, anchor="lm")
                return img.resize((self.w, self.h), Image.LANCZOS)

            if kind == "mic":
                icon = self.ICON_MIC_MUTE if (muted or no_session) else self.ICON_MIC
                num = "–" if no_session else str(round(volume * 100))
            elif no_session:
                icon, num = self.ICON_MUTE, "–"
            elif muted:
                icon, num = self.ICON_MUTE, str(round(volume * 100))
            else:
                level = 0 if volume <= 0.005 else 1 + min(2, int(volume * 3))
                icon, num = self.ICON_VOL[level], str(round(volume * 100))

            d.text((round(self.ICON_X * k) * s, cy), icon, font=self.font_icon, fill=self.TEXT, anchor="lm")

            # Slider: grauer Track, davor die blaue Fuellung
            x0, x1 = round(self.SLIDER_X0 * k) * s, round(self.SLIDER_X1 * k) * s
            sh = round(self.SLIDER_H * k) * s
            y0, y1 = cy - sh // 2, cy + sh // 2
            d.rounded_rectangle([x0, y0, x1, y1], (y1 - y0) // 2, fill=self.TRACK)
            if not no_session and volume > 0:
                fill_end = x0 + max((y1 - y0), int((x1 - x0) * volume))
                d.rounded_rectangle([x0, y0, fill_end, y1], (y1 - y0) // 2,
                                    fill=self.TRACK if muted else self.ACCENT)

            d.text((round(self.NUM_CENTER_X * k) * s, cy), num, font=self.font_num, fill=self.TEXT, anchor="mm")
            return img.resize((self.w, self.h), Image.LANCZOS)

        def _render_pill(self, text, cover=None, dim=False):
            s, k = self.SS, self.scale
            tw = self.font_pill.getbbox(text)[2] // s
            if cover is not None:
                th = self.pill_h - round(8 * k)          # Cover-Kantenlaenge
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

        # ---- Anzeigen / Verstecken ----

        def show(self, app_name, volume=None, muted=False, no_session=False, kind="app", note=None,
                 media_icon=None, media_text=None, media_cover=None, extra_pills=None,
                 extra_dim=False):
            self.hide_hint()
            if not CONFIG.get("overlay_anzeigen", True):
                return
            # Falls die echte Windows-Anzeige noch steht: ausblenden, wir sind neuer.
            # (Beim naechsten System-Lautstaerke-Aendern zeigt Windows sie wieder an.)
            h = self._find_windows_osd()
            if h and user32.IsWindowVisible(h):
                user32.ShowWindow(h, SW_HIDE)

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

            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            box_x = (sw - self.w) // 2
            box_y = sh - self.bottom_margin - self.h
            pill_x = (sw - pill_img.width) // 2
            pill_y = box_y - self.pill_gap - self.pill_h

            self._last_pushes = [(self.box_hwnd, box_img, box_x, box_y),
                                 (self.pill_hwnd, pill_img, pill_x, pill_y)]

            # weitere Pillen (Multi-App): uebereinander stapeln
            extras = list(extra_pills or [])
            while len(self.extra_hwnds) < len(extras):
                self.extra_hwnds.append(self._make_layered_window())
            for i, text in enumerate(extras):
                key = (text, False, extra_dim)
                img_e = self._pill_cache.get(key)
                if img_e is None:
                    img_e = self._pill_cache[key] = self._render_pill(text, dim=extra_dim)
                self._last_pushes.append((self.extra_hwnds[i], img_e,
                                          (sw - img_e.width) // 2,
                                          pill_y - (i + 1) * (self.pill_h + self.pill_gap)))
            for h in self.extra_hwnds[len(extras):]:
                user32.ShowWindow(h, SW_HIDE)

            for hwnd, img, x, y in self._last_pushes:
                self._push_image(hwnd, img, x, y)
                if not user32.IsWindowVisible(hwnd):
                    user32.SetWindowPos(hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            self._visible = True

            if self._hide_job:
                self.root.after_cancel(self._hide_job)
            self._hide_job = self.root.after(OSD_TIMEOUT_MS, self._hide)
            if not self._watch_job:
                self._watch_job = self.root.after(150, self._watch_windows_osd)

        def show_hint(self, text):
            """Kleine halbtransparente Pille unten mittig: welcher Modus gerade
            aktiv waere (beim Halten einer Modifier-Taste ohne Rad-Bewegung)."""
            if text == self._hint_text and user32.IsWindowVisible(self.hint_hwnd):
                return
            self._hint_text = text
            key = ("hint:" + text, False)
            img = self._pill_cache.get(key)
            if img is None:
                img = self._pill_cache[key] = self._render_pill(text)
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            x = (sw - img.width) // 2
            y = sh - self.bottom_margin - self.pill_h
            self._push_image(self.hint_hwnd, img, x, y, alpha=200)
            user32.SetWindowPos(self.hint_hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

        def hide_hint(self):
            self._hint_text = None
            user32.ShowWindow(self.hint_hwnd, SW_HIDE)

        def _hide_all_windows(self):
            user32.ShowWindow(self.box_hwnd, SW_HIDE)
            user32.ShowWindow(self.pill_hwnd, SW_HIDE)
            for h in self.extra_hwnds:
                user32.ShowWindow(h, SW_HIDE)

        def _hide(self, fade=True):
            self._visible = False
            if fade and self._last_pushes:
                self._fade_step(0)
            else:
                self._hide_all_windows()

        def _fade_step(self, i):
            self._fade_job = None
            if self._visible:  # neues show() kam dazwischen
                return
            if i >= len(self.FADE_ALPHAS):
                self._hide_all_windows()
                return
            for hwnd, img, x, y in self._last_pushes:
                self._push_image(hwnd, img, x, y, alpha=self.FADE_ALPHAS[i])
            self._fade_job = self.root.after(self.FADE_STEP_MS, self._fade_step, i + 1)
else:
    from linux_osd import OSD  # gleiche Schnittstelle, Tk/X11-basiert



# ----------------------------- Audio-Helfer fuer die UI ---------------------

def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", None) or APP_DIR
    return os.path.join(base, *parts)


def audible_apps():
    """Apps, die GERADE hoerbar Ton ausgeben (Pegel > 0), pro Prozess gebuendelt.
    Fuer die OBS-'Rest'-Funktion: nur echte Tonquellen, kein Hintergrundrauschen.
    Linux: Pegel sind ueber Pulse nicht ohne eigenen Stream abfragbar - dort
    zaehlen alle nicht stummen Streams als hoerbar."""
    apps = {}
    try:
        for s in get_all_audio_sessions():
            if s.Process is None:
                continue
            try:
                name = s.Process.name()
            except psutil.Error:
                continue
            key = _norm(name)
            e = apps.setdefault(key, {"name": pretty_name(name), "pid": s.Process.pid, "peak": 0.0})
            if not IS_WINDOWS:
                try:
                    if not s.SimpleAudioVolume.GetMute():
                        e["peak"] = 1.0
                except Exception:
                    pass
                continue
            try:
                meter = s._ctl.QueryInterface(IAudioMeterInformation)
                e["peak"] = max(e["peak"], meter.GetPeakValue())
            except Exception:
                continue
    except Exception:
        logging.exception("Pegel-Abfrage fehlgeschlagen")
    return {k: v for k, v in apps.items() if v["peak"] > 0.0005}


def collect_audio_apps():
    """Alle Apps mit aktiven Audio-Sessions, gebuendelt pro Prozessname."""
    apps = {}
    try:
        for s in get_all_audio_sessions():
            if s.Process is None:
                continue
            try:
                nm = s.Process.name()
            except psutil.Error:
                continue
            # Schluessel ohne ".exe" (s. _norm), damit eine config.json auf
            # Windows und Linux dieselben Eintraege trifft
            e = apps.setdefault(_norm(nm), {"name": pretty_name(nm), "sessions": [], "exe": None})
            e["sessions"].append(s)
            if e["exe"] is None:
                try:
                    e["exe"] = s.Process.exe()
                except psutil.Error:
                    pass
    except Exception:
        logging.exception("Audio-Sessions nicht lesbar")
    return apps


if not IS_WINDOWS:
    def list_output_devices():
        """(dev_id, name)-Liste aller Wiedergabegeraete + aktuelle Standard-ID."""
        return linux_audio.list_output_devices()

    def set_default_output_device(dev_id):
        linux_audio.set_default_output_device(dev_id)


# Standard-Ausgabegeraet wechseln (undokumentierte, aber etablierte
# IPolicyConfig-Schnittstelle; nutzen u. a. SoundSwitch/EarTrumpet)
#
# Pro Thread eine eigene Instanz: COM-Objekte gehoeren dem Apartment, in dem
# sie erzeugt wurden. Der Effekt-Thread stellt beim Beenden das Standardgeraet
# zurueck und wuerde sonst ein Objekt des Hauptthreads ueber Apartmentgrenzen
# hinweg aufrufen - das geht bestenfalls gut.
_policy_local = threading.local()


def _get_policy_config():
    """Nur unter Windows: IPolicyConfig zum Umschalten des Standardgeraets.
    Unter Linux uebernimmt das linux_audio.set_default_output_device."""
    if not IS_WINDOWS:
        return None
    _policy_config = getattr(_policy_local, "pc", None)
    if _policy_config is None:
        import comtypes
        from comtypes import GUID, COMMETHOD, HRESULT

        class IPolicyConfig(comtypes.IUnknown):
            _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetMixFormat",
                          (["in"], wintypes.LPCWSTR), (["out"], ctypes.POINTER(ctypes.c_void_p))),
                COMMETHOD([], HRESULT, "GetDeviceFormat",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT),
                          (["out"], ctypes.POINTER(ctypes.c_void_p))),
                COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], wintypes.LPCWSTR)),
                COMMETHOD([], HRESULT, "SetDeviceFormat",
                          (["in"], wintypes.LPCWSTR), (["in"], ctypes.c_void_p), (["in"], ctypes.c_void_p)),
                COMMETHOD([], HRESULT, "GetProcessingPeriod",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT),
                          (["out"], ctypes.POINTER(ctypes.c_longlong)),
                          (["out"], ctypes.POINTER(ctypes.c_longlong))),
                COMMETHOD([], HRESULT, "SetProcessingPeriod",
                          (["in"], wintypes.LPCWSTR), (["in"], ctypes.POINTER(ctypes.c_longlong))),
                COMMETHOD([], HRESULT, "GetShareMode",
                          (["in"], wintypes.LPCWSTR), (["out"], ctypes.POINTER(ctypes.c_void_p))),
                COMMETHOD([], HRESULT, "SetShareMode",
                          (["in"], wintypes.LPCWSTR), (["in"], ctypes.c_void_p)),
                COMMETHOD([], HRESULT, "GetPropertyValue",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT),
                          (["in"], ctypes.c_void_p), (["out"], ctypes.POINTER(ctypes.c_void_p))),
                COMMETHOD([], HRESULT, "SetPropertyValue",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT),
                          (["in"], ctypes.c_void_p), (["in"], ctypes.c_void_p)),
                COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT)),
                COMMETHOD([], HRESULT, "SetEndpointVisibility",
                          (["in"], wintypes.LPCWSTR), (["in"], wintypes.INT)),
            ]

        clsid = comtypes.GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")
        _policy_config = comtypes.CoCreateInstance(clsid, interface=IPolicyConfig,
                                                   clsctx=comtypes.CLSCTX_ALL)
        _policy_local.pc = _policy_config
    return _policy_config


if IS_WINDOWS:
    def list_output_devices():
        """(dev_id, name)-Liste aller aktiven Wiedergabegeraete + aktuelle Standard-ID."""
        devenum = AudioUtilities.GetDeviceEnumerator()
        current = devenum.GetDefaultAudioEndpoint(0, 1).GetId()
        coll = devenum.EnumAudioEndpoints(0, 1)  # eRender, DEVICE_STATE_ACTIVE
        devices = []
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            try:
                name = AudioUtilities.CreateDevice(dev).FriendlyName
            except Exception:
                name = "Audiogeraet"
            devices.append((dev.GetId(), name))
        return devices, current


    def set_default_output_device(dev_id):
        pc = _get_policy_config()
        if pc is None:
            return
        for role in (0, 1, 2):  # Console, Multimedia, Communications
            pc.SetDefaultEndpoint(dev_id, role)


# ----------------------------- Audio-Effekte --------------------------------
# Optionaler Teil: standardmaessig aus (CONFIG["effekte_aktiv"]). Erst wenn
# eingeschaltet, werden numpy/scipy/sounddevice geladen - das kostet ~300 ms
# und soll den Start derjenigen nicht bremsen, die keine Effekte wollen.
#
# Funktionsweise ("Bruecke"): Windows spielt auf ein Geraet, das niemand
# hoert; Fluneit nimmt das per Loopback auf, legt die Effekte darauf und gibt
# es auf den echten Kopfhoerern aus. Kein Treiber, keine Registry.

_fx_engine = None
_fx_lock = threading.Lock()
_fx_error = None


def fx_modules():
    """fx_dsp und fx_engine bei Bedarf laden. (None, None) wenn die
    Abhaengigkeiten fehlen."""
    try:
        import fx_dsp
        import fx_engine
        return fx_dsp, fx_engine
    except Exception as e:
        global _fx_error
        _fx_error = f"Effekt-Bibliotheken fehlen: {e}"
        logging.warning("Effekte nicht verfuegbar: %s", e)
        return None, None


def fx_available():
    return fx_modules()[0] is not None


def _fx_device_by_name(name):
    """Ausgabegeraet-Name -> Endpoint-ID (Windows) bzw. Name (Linux)."""
    if not name:
        return None
    try:
        devices, _cur = list_output_devices()
    except Exception:
        return None
    want = name.lower()
    for dev_id, dev_name in devices:
        n = (dev_name or "").lower()
        if n == want or want in n or n in want:
            return dev_id
    return None


def _fx_current_default():
    try:
        _devices, cur = list_output_devices()
        return cur
    except Exception:
        return None


def fx_restore_device(reason=""):
    """Standard-Ausgabegeraet zurueckstellen. Wird nach jedem Stopp und beim
    Start aufgerufen - Letzteres faengt den Fall ab, dass Fluneit im
    Brueckenbetrieb abgeschossen wurde und der Nutzer sonst ohne Ton dasteht."""
    dev_id = CONFIG.get("effekte_wiederherstellen") or ""
    if not dev_id:
        return False
    try:
        set_default_output_device(dev_id)
        logging.info("Standardgeraet zurueckgestellt (%s)", reason or "Stopp")
    except Exception:
        logging.exception("Standardgeraet konnte nicht zurueckgestellt werden")
        return False
    finally:
        CONFIG["effekte_wiederherstellen"] = ""
        save_config()
    return True


def fx_params(mic=False):
    """Effektwerte aus der Konfiguration, mit Baendern als Rueckfall."""
    fx_dsp, _ = fx_modules()
    key = "effekte_mikrofon" if mic else "effekte"
    p = dict(CONFIG.get(key) or {})
    if fx_dsp is not None and not p.get("baender"):
        p["baender"] = fx_dsp.default_bands()
    return p


def fx_start():
    """Effektkette starten. Gibt (True, "") oder (False, Grund) zurueck."""
    global _fx_engine, _fx_error
    fx_dsp, fx_engine = fx_modules()
    if fx_engine is None:
        return False, _fx_error or "Effekte nicht verfuegbar"

    with _fx_lock:
        if _fx_engine is not None and _fx_engine.running:
            return True, ""

        sink = CONFIG.get("effekte_ausgabe") or ""
        bridge = CONFIG.get("effekte_bruecke") or ""
        if not sink or not bridge:
            return False, ("Bitte zuerst Brueckengeraet und Ausgabegeraet "
                           "in den Einstellungen waehlen")
        if sink.strip().lower() == bridge.strip().lower():
            return False, "Bruecke und Ausgabe duerfen nicht dasselbe Geraet sein"

        bridge_id = _fx_device_by_name(bridge) if IS_WINDOWS else None
        if IS_WINDOWS and not bridge_id:
            return False, f"Brueckengeraet \"{bridge}\" nicht gefunden"

        # Aktuelles Standardgeraet merken, BEVOR wir umschalten - und zwar in
        # der Datei, damit auch ein Absturz es nicht verschluckt.
        previous = _fx_current_default()
        if previous:
            CONFIG["effekte_wiederherstellen"] = previous
            save_config()

        def on_stop():
            fx_restore_device("Engine beendet")

        def on_error(msg):
            global _fx_error
            _fx_error = msg

        engine = fx_engine.FxEngine(on_stop=on_stop, on_error=on_error)
        _fx_engine = engine
        _fx_error = None

        # Erst die Bruecke zum Standardgeraet machen, dann aufnehmen: sonst
        # nimmt die Engine ein Geraet auf, auf dem gleich nichts mehr laeuft.
        if IS_WINDOWS:
            try:
                set_default_output_device(bridge_id)
            except Exception as e:
                fx_restore_device("Umschalten fehlgeschlagen")
                return False, f"Umschalten auf die Bruecke fehlgeschlagen: {e}"

        ok = engine.start(source=bridge_id if IS_WINDOWS else None,
                          sink=sink, params=fx_params(),
                          latency=CONFIG.get("effekte_latenz", "mittel"))
        if not ok:
            # on_stop hat das Geraet schon zurueckgestellt
            return False, engine.error or _fx_error or "Start fehlgeschlagen"
        CONFIG["effekte_aktiv"] = True
        save_config()
        return True, ""


def fx_stop():
    """Effektkette beenden und Standardgeraet zurueckstellen."""
    global _fx_engine
    with _fx_lock:
        engine = _fx_engine
        _fx_engine = None
    if engine is not None:
        engine.stop()          # on_stop stellt das Geraet zurueck
    fx_restore_device("Stopp")  # zur Sicherheit auch, wenn on_stop ausfiel
    CONFIG["effekte_aktiv"] = False
    save_config()


def fx_running():
    e = _fx_engine
    return bool(e is not None and e.running)


def fx_toggle():
    if fx_running():
        fx_stop()
        return False, ""
    return fx_start()


def fx_apply_params():
    """Geaenderte Werte an die laufende Kette geben (ohne Neustart)."""
    e = _fx_engine
    if e is not None and e.running:
        e.set_params(fx_params())


def fx_status():
    """Statuswerte fuer die UI."""
    e = _fx_engine
    if e is None or not e.running:
        return {"laeuft": False, "fehler": _fx_error or ""}
    return {"laeuft": True, "fehler": e.error or "",
            "latenz_ms": e.latency_ms, "last": e.load_percent,
            "aussetzer": e.dropouts, "pegel_in": e.peak_in,
            "pegel_out": e.peak_out, "abtastrate": e.samplerate,
            "kanaele": e.channels, "reduktion_db": e.gain_reduction_db,
            "quelle": e.source_name, "ziel": e.sink_name}


# --- Mikrofon-Kette (eigene Engine, unabhaengig von der Wiedergabe) ---
_fx_mic_engine = None


def fx_mic_running():
    e = _fx_mic_engine
    return bool(e is not None and e.running)


def fx_mic_start():
    global _fx_mic_engine
    _fx_dsp, fx_engine = fx_modules()
    if fx_engine is None:
        return False, _fx_error or "Effekte nicht verfuegbar"
    if fx_mic_running():
        return True, ""
    sink = CONFIG.get("effekte_mikrofon_ausgabe") or ""
    if not sink:
        return False, ("Bitte waehlen, wohin das bearbeitete Mikrofonsignal "
                       "gehen soll (Mithoeren oder virtuelles Kabel)")
    engine = fx_engine.FxEngine()
    _fx_mic_engine = engine
    ok = engine.start(source=CONFIG.get("effekte_mikrofon_quelle") or None,
                      sink=sink, params=fx_params(mic=True),
                      latency=CONFIG.get("effekte_latenz", "mittel"), mic=True)
    if not ok:
        return False, engine.error or "Start fehlgeschlagen"
    CONFIG["effekte_mikrofon_aktiv"] = True
    save_config()
    return True, ""


def fx_mic_stop():
    global _fx_mic_engine
    e, _fx_mic_engine = _fx_mic_engine, None
    if e is not None:
        e.stop()
    CONFIG["effekte_mikrofon_aktiv"] = False
    save_config()


def fx_mic_toggle():
    if fx_mic_running():
        fx_mic_stop()
        return False, ""
    return fx_mic_start()


def fx_mic_apply_params():
    e = _fx_mic_engine
    if e is not None and e.running:
        e.set_params(fx_params(mic=True))


def fx_mic_status():
    e = _fx_mic_engine
    if e is None or not e.running:
        return {"laeuft": False, "fehler": ""}
    return {"laeuft": True, "fehler": e.error or "", "latenz_ms": e.latency_ms,
            "last": e.load_percent, "aussetzer": e.dropouts,
            "pegel_in": e.peak_in, "pegel_out": e.peak_out}


def fx_shutdown():
    """Beim Beenden von Fluneit aufrufen - laesst niemanden ohne Ton zurueck."""
    try:
        fx_mic_stop()
    except Exception:
        pass
    try:
        if fx_running():
            fx_stop()
        else:
            fx_restore_device("Programmende")
    except Exception:
        logging.exception("Effekte konnten nicht saeuber beendet werden")


# ----------------------------- Ereignis-Verarbeitung ------------------------

def pretty_name(exe_name):
    base = exe_name[:-4] if exe_name.lower().endswith(".exe") else exe_name
    return base[:1].upper() + base[1:]


def process_events(root: tk.Tk, osd: OSD):
    # Alle aufgelaufenen Rad-Ticks einsammeln und zusammenfassen
    hotkey_digits = []
    delta = mic_delta = bg_delta = media_skip = media_seek = comm_delta = bg_switch = 0
    mute_toggle = mic_mute_toggle = bg_mute_toggle = media_play_toggle = sys_tick = False
    comm_mute_toggle = False
    fx_requested = fx_mic_requested = autostart_failed = False
    ui_calls = []
    try:
        while True:
            ev = event_queue.get_nowait()
            if callable(ev):
                ui_calls.append(ev)
            elif ev == "up":
                delta += 1
            elif ev == "down":
                delta -= 1
            elif ev == "mute":
                mute_toggle = True
            elif ev == "mic_up":
                mic_delta += 1
            elif ev == "mic_down":
                mic_delta -= 1
            elif ev == "mic_mute":
                mic_mute_toggle = True
            elif ev == "bg_up":
                bg_delta += 1
            elif ev == "bg_down":
                bg_delta -= 1
            elif ev == "bg_mute":
                bg_mute_toggle = True
            elif ev == "comm_up":
                comm_delta += 1
            elif ev == "comm_down":
                comm_delta -= 1
            elif ev == "comm_mute":
                comm_mute_toggle = True
            elif ev == "bg_next":
                bg_switch += 1
            elif ev == "bg_prev":
                bg_switch -= 1
            elif ev == "media_up":
                media_skip += 1
            elif ev == "media_down":
                media_skip -= 1
            elif ev == "media_mute":
                media_play_toggle = not media_play_toggle
            elif ev == "media_seek_up":
                media_seek += 1
            elif ev == "media_seek_down":
                media_seek -= 1
            elif ev == "sys_tick":
                sys_tick = True
            elif ev == "autostart_fehler":
                autostart_failed = True
            elif ev == "fx_toggle":
                fx_requested = True
            elif ev == "fx_mic_toggle":
                fx_mic_requested = True
            elif isinstance(ev, str) and ev.startswith("hotkey_"):
                hotkey_digits.append(ev[7:])
    except queue.Empty:
        pass

    if autostart_failed:
        osd.show_hint("Autostart konnte nicht eingerichtet werden")

    if fx_requested:
        was_on = fx_running()
        ok, why = fx_toggle()
        if not was_on and not ok:
            osd.show_hint(f"Effekte: {why}"[:70])
        elif CONFIG.get("modus_hinweis", True):
            osd.show_hint("Effekte an" if ok else "Effekte aus")
    if fx_mic_requested:
        was_on = fx_mic_running()
        ok, why = fx_mic_toggle()
        if not was_on and not ok:
            osd.show_hint(f"Mikrofon-Effekte: {why}"[:70])
        elif CONFIG.get("modus_hinweis", True):
            osd.show_hint("Mikrofon-Effekte an" if ok else "Mikrofon-Effekte aus")

    for d in hotkey_digits:
        try:
            run_hotkey(d, root, osd)
        except Exception:
            logging.exception("Hotkey %s fehlgeschlagen", d)

    for fn in ui_calls:
        try:
            fn()
        except Exception:
            logging.exception("UI-Callback fehlgeschlagen")

    global _idle_ticks
    had_work = bool(ui_calls or delta or mic_delta or bg_delta or media_skip
                    or media_seek or sys_tick or mute_toggle or mic_mute_toggle
                    or bg_mute_toggle or media_play_toggle or comm_delta
                    or comm_mute_toggle or bg_switch or hotkey_digits)
    _idle_ticks = 0 if had_work else min(_idle_ticks + 1, 60)

    try:
        if delta or mute_toggle:
            handle_change(osd, delta, mute_toggle)
        if mic_delta or mic_mute_toggle:
            handle_mic_change(osd, mic_delta, mic_mute_toggle)
        if bg_delta or bg_mute_toggle:
            handle_bg_change(osd, bg_delta, bg_mute_toggle)
        if comm_delta or comm_mute_toggle:
            handle_comm_change(osd, comm_delta, comm_mute_toggle)
        if bg_switch:
            handle_bg_switch(osd, bg_switch)
        if media_skip or media_play_toggle:
            handle_media(root, osd, media_skip, media_play_toggle)
        if media_seek:
            handle_media_seek(osd, media_seek)
        if sys_tick and not (delta or mic_delta or bg_delta or comm_delta):
            _mark_system_adjust()
            _show_system_overlay(osd)
        if delta or mic_delta or bg_delta or comm_delta or sys_tick:
            _schedule_round(root, osd)
    except Exception:
        logging.exception("Fehler bei Lautstaerke-Aenderung")

    # nach ~1 s ohne Ereignis entspannter pollen (spart Aufwachzyklen im Leerlauf)
    root.after(30 if _idle_ticks < 33 else 75, process_events, root, osd)


_idle_ticks = 0


# ----------------------------- Einrasten (Rundungsregel) --------------------
# Kurz nachdem der Nutzer aufhoert zu drehen, wird die Lautstaerke auf das
# naechste Vielfache von CONFIG["runden_auf"] gerundet (12 % -> 10 %). Das
# Overlay taucht dabei mit dem korrigierten Wert als Feedback wieder auf.
# Gilt fuer App- (Shift+Rad), Mikrofon- (Strg+Rad) UND System-Lautstaerke
# (Rad ohne Modifier - die Taste laeuft normal an Windows durch, wir runden
# nur hinterher nach).

_round_job = None
_last_adjust = None

_system_ep = None


def system_endpoint(refresh=False):
    global _system_ep
    if _system_ep is None or refresh:
        _system_ep = _default_endpoint(0, 1)  # eRender, eMultimedia
    return _system_ep


def _mark_system_adjust():
    global _last_adjust
    _last_adjust = {"kind": "system"}


def _show_system_overlay(osd):
    """Eigene "System"-Pille bei System-Lautstaerke - aber NUR, wenn wir das
    Windows-OSD gerade unterdrueckt haben. Griff die Unterdrueckung nicht
    (z. B. nach einem Windows-Update mit anderem Fensternamen), zeigen wir
    bewusst nichts, damit es NIE zur Doppelanzeige kommt (Feature-Vorgabe)."""
    if not CONFIG.get("system_overlay", True):
        return
    if time.monotonic() - _osd_last_caught > 0.6:
        return  # nicht bestaetigt unterdrueckt -> Windows zeigt sein OSD, wir schweigen
    for attempt in (1, 2):
        try:
            ep = system_endpoint(refresh=(attempt == 2))
            osd.show("System", volume=ep.GetMasterVolumeLevelScalar(), muted=bool(ep.GetMute()))
            return
        except Exception:
            if attempt == 2:
                return


def _schedule_round(root: tk.Tk, osd):
    global _round_job
    if not ROUND_TO:
        return
    if _round_job:
        root.after_cancel(_round_job)
    # kurz bevor das Overlay verschwindet, faellt die Korrektur
    delay = max(700, OSD_TIMEOUT_MS - 300)
    _round_job = root.after(delay, _round_settled, osd)


def _round_settled(osd):
    global _round_job
    _round_job = None
    n = ROUND_TO
    if not n or not _last_adjust:
        return
    kind = _last_adjust["kind"]
    for attempt in (1, 2):
        try:
            if kind == "multi":
                shown = []
                any_change = False
                for display, vols in _last_adjust["groups"]:
                    cur = vols[0].GetMasterVolume()
                    snapped = min(1.0, max(0.0, round(cur * 100 / n) * n / 100))
                    if abs(snapped - cur) > 0.001:
                        for v in vols:
                            v.SetMasterVolume(snapped, None)
                        any_change = True
                        cur = snapped
                    shown.append((display, cur, bool(vols[0].GetMute())))
                if any_change and shown:
                    d0, c0, m0 = shown[0]
                    osd.show(d0, volume=c0, muted=m0, note=f"auf {round(c0 * 100)} % gerundet",
                             extra_pills=[f"{d} – {round(c * 100)} %" for d, c, m in shown[1:]])
                return
            if kind == "app":
                vols = _last_adjust["volumes"]
                cur = vols[0].GetMasterVolume()
            elif kind == "mic":
                ep = mic_endpoint(refresh=(attempt == 2))
                cur = ep.GetMasterVolumeLevelScalar()
            else:
                ep = system_endpoint(refresh=(attempt == 2))
                cur = ep.GetMasterVolumeLevelScalar()

            snapped = min(1.0, max(0.0, round(cur * 100 / n) * n / 100))
            if abs(snapped - cur) <= 0.001:
                return  # schon sauber -> kein Feedback noetig
            note = f"auf {round(snapped * 100)} % gerundet"

            if kind == "app":
                for v in vols:
                    v.SetMasterVolume(snapped, None)
                osd.show(_last_adjust["display"], volume=snapped,
                         muted=bool(vols[0].GetMute()), note=note)
            elif kind == "mic":
                ep.SetMasterVolumeLevelScalar(snapped, None)
                osd.show("Mikrofon", volume=snapped, muted=bool(ep.GetMute()),
                         kind="mic", note=note)
            else:
                ep.SetMasterVolumeLevelScalar(snapped, None)
                osd.show("System", volume=snapped, muted=bool(ep.GetMute()), note=note)
            return
        except Exception:
            if kind in ("app", "multi") or attempt == 2:
                return  # Session/Geraet inzwischen weg -> nichts runden


# ----------------------------- Modus-Hinweis --------------------------------
# Haelt der Nutzer eine Modifier-Taste laenger ohne Rad-Bewegung, zeigt eine
# kleine Pille, welche Funktion das Rad in diesem Moment haette.

_MOD_NAMES = {0x11: "Strg", 0x10: "Shift", 0x12: "Alt"}
_MOD_ORDER = {0x11: 0, 0x10: 1, 0x12: 2}
_HINT_LABELS = {"app": "App-Lautst\u00e4rke", "mic": "Mikrofon",
                "media": "Medien-Steuerung", "seek": "Im Titel spulen",
                "bg": "Musik-App regeln", "comm": "Kommunikations-Apps"}
_mod_watch = {"set": frozenset(), "since": 0.0, "done": False}


def watch_modifiers(root: tk.Tk, osd: OSD):
    try:
        if IS_WINDOWS:
            pressed = frozenset(vk for vk in (0x10, 0x11, 0x12)
                                if user32.GetAsyncKeyState(vk) & 0x8000)
        else:
            pressed = linux_input.pressed_modifiers()
        now = time.monotonic()
        st = _mod_watch
        if pressed != st["set"]:
            st.update(set=pressed, since=now, done=False)
            osd.hide_hint()
        elif pressed and not st["done"] and CONFIG.get("modus_hinweis", True):
            if osd._visible:
                st["done"] = True  # Nutzer regelt bereits -> kein Hinweis mehr bis zum Loslassen
            elif now - st["since"] >= 0.7:
                for vkset, kind in HOOK_FUNCS:
                    if vkset <= pressed:
                        keys = "+".join(_MOD_NAMES[v] for v in sorted(vkset, key=_MOD_ORDER.get))
                        osd.show_hint(f"{keys} \u00b7 {_HINT_LABELS.get(kind, kind)}")
                        break
                st["done"] = True
    except Exception:
        logging.exception("Modus-Hinweis fehlgeschlagen")
        pressed = None
    root.after(100 if pressed else 200, watch_modifiers, root, osd)


# Die COM-Abfrage aller Audio-Sitzungen ist der teuerste Schritt pro Rad-Tick.
# Beim schnellen Drehen wird das Ergebnis deshalb kurz wiederverwendet.
SESSION_CACHE_TTL = 1.0
_session_cache = {"pid": None, "time": 0.0, "sessions": []}


def get_sessions_cached(pid, name):
    now = time.monotonic()
    if _session_cache["pid"] == pid and now - _session_cache["time"] < SESSION_CACHE_TTL:
        return _session_cache["sessions"]
    sessions = find_audio_sessions(pid, name)
    _session_cache.update(pid=pid, time=now, sessions=sessions)
    return sessions


def handle_change(osd: OSD, delta, mute_toggle):
    pid, name = get_foreground_process()
    if not pid:
        return

    display = pretty_name(name)

    if _norm(name) in EXCLUDED_APPS:
        osd.show(display, no_session=True, note="ausgeschlossen")
        return

    # Zweiter Versuch mit frischen Sessions, falls eine gecachte Session
    # ungueltig geworden ist (z. B. App zwischenzeitlich geschlossen)
    for attempt in (1, 2):
        sessions = get_sessions_cached(pid, name)
        if not sessions:
            osd.show(display, no_session=True)
            return
        try:
            volumes = [s.SimpleAudioVolume for s in sessions]
            current = volumes[0].GetMasterVolume()
            muted = bool(volumes[0].GetMute())

            if mute_toggle:
                muted = not muted
                for v in volumes:
                    v.SetMute(muted, None)
            if delta:
                current = min(1.0, max(0.0, current + delta * APP_VOL_STEP))
                for v in volumes:
                    v.SetMasterVolume(current, None)
                if muted and delta > 0:  # Lauter drehen hebt Stummschaltung auf (wie bei Windows)
                    muted = False
                    for v in volumes:
                        v.SetMute(False, None)
            break
        except Exception:
            _session_cache["pid"] = None
            if attempt == 2:
                return

    if delta:
        global _last_adjust
        _last_adjust = {"kind": "app", "display": display, "volumes": volumes}

    osd.show(display, volume=current, muted=muted)


def handle_mic_change(osd: OSD, delta, mute_toggle):
    for attempt in (1, 2):
        try:
            ep = mic_endpoint(refresh=(attempt == 2))
            current = ep.GetMasterVolumeLevelScalar()
            muted = bool(ep.GetMute())

            if mute_toggle:
                muted = not muted
                ep.SetMute(muted, None)
            if delta:
                current = min(1.0, max(0.0, current + delta * APP_VOL_STEP))
                ep.SetMasterVolumeLevelScalar(current, None)
                if muted and delta > 0:
                    muted = False
                    ep.SetMute(False, None)

            if delta:
                global _last_adjust
                _last_adjust = {"kind": "mic", "ep": ep}

            osd.show("Mikrofon", volume=current, muted=muted, kind="mic")
            return
        except Exception:
            if attempt == 2:
                osd.show("Mikrofon", no_session=True, kind="mic")
                return


# ----------------------------- Medien-Steuerung -----------------------------


def _fmt_time(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

# Versehentlich geskippt? Beim Zurueckgehen zur gemerkten Sekunde springen.
_skip_restore = None
SKIP_RESTORE_WINDOW_S = 60


if IS_WINDOWS:
    VK_MEDIA_NEXT = 0xB0
    VK_MEDIA_PREV = 0xB1
    VK_MEDIA_PLAY_PAUSE = 0xB3


    _cover_cache = {}


    def _run_winrt(coro_factory, timeout=2.0):
        """Fuehrt eine WinRT-Async-Operation in einem eigenen Thread aus.
        Noetig, weil comtypes den Hauptthread als STA initialisiert und
        WinRT-Awaits dort deadlocken koennen; im frischen Thread gilt MTA."""
        result = {}

        def worker():
            try:
                import asyncio
                result["value"] = asyncio.run(coro_factory())
            except Exception:
                result["value"] = None

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout)
        return result.get("value")


    async def _cover_from_props(props):
        """Album-Cover der Medien-Session als PIL-Bild (gecacht pro Titel)."""
        key = (props.title, props.artist)
        if key in _cover_cache:
            return _cover_cache[key]
        cover = None
        try:
            ref = props.thumbnail
            if ref is not None:
                import io
                from winrt.windows.storage.streams import DataReader
                stream = await ref.open_read_async()
                size = stream.size
                reader = DataReader(stream)
                await reader.load_async(size)
                data = bytes(memoryview(reader.read_buffer(size)))
                cover = Image.open(io.BytesIO(data)).convert("RGB")
                cover.thumbnail((96, 96), Image.LANCZOS)
        except Exception:
            cover = None
        if len(_cover_cache) > 24:
            _cover_cache.clear()
        _cover_cache[key] = cover
        return cover


    def get_media_info():
        """Titel/Interpret/Status/Cover der aktuellen Medien-Session (Windows SMTC).
        Liefert None, wenn nichts spielt oder die WinRT-Pakete fehlen."""
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as _Mgr)

            async def go():
                mgr = await _Mgr.request_async()
                s = mgr.get_current_session()
                if not s:
                    return None
                props = await s.try_get_media_properties_async()
                return {"title": props.title or "", "artist": props.artist or "",
                        "playing": s.get_playback_info().playback_status == 4,
                        "cover": await _cover_from_props(props)}
            return _run_winrt(go)
        except Exception:
            return None


    def handle_media_seek(osd: OSD, ticks):
        """Medien-Taste + Alt + Rad: im Titel spulen (laeuft im Worker-Thread,
        damit der Tk-Thread und der Tastatur-Hook nie blockieren)."""
        secs = ticks * max(1, int(CONFIG.get("spulen_sekunden", 10)))

        def work():
            try:
                from winrt.windows.media.control import (
                    GlobalSystemMediaTransportControlsSessionManager as _Mgr)

                async def go():
                    s = (await _Mgr.request_async()).get_current_session()
                    if not s:
                        return None
                    tl = s.get_timeline_properties()
                    end = tl.end_time.total_seconds()
                    new = min(max(tl.position.total_seconds() + secs, 0), max(end - 1, 0))
                    await s.try_change_playback_position_async(int(new * 10_000_000))
                    props = await s.try_get_media_properties_async()
                    title = props.title or "Medien"
                    if props.artist:
                        title += " \u2013 " + props.artist
                    return new, end, title, await _cover_from_props(props)
                res = _run_winrt(go)
            except Exception:
                res = None
            if not res:
                _post_to_ui(lambda: osd.show("Medien", no_session=True))
                return
            new, end, title, cover = res
            if len(title) > 48:
                title = title[:47] + "\u2026"
            _post_to_ui(lambda: osd.show(
                title, kind="media", media_icon="fwd" if secs > 0 else "rew",
                media_text=f"{_fmt_time(new)} / {_fmt_time(end)}", media_cover=cover))

        threading.Thread(target=work, daemon=True).start()

    def _get_media_snapshot():
        """Schneller Blick auf die aktuelle Wiedergabe (Titel + Position, ohne Cover)."""
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as _Mgr)

            async def go():
                s = (await _Mgr.request_async()).get_current_session()
                if not s:
                    return None
                props = await s.try_get_media_properties_async()
                tl = s.get_timeline_properties()
                return {"title": props.title or "", "pos": tl.position.total_seconds()}
            return _run_winrt(go)
        except Exception:
            return None


    def _restore_after_prev(osd: OSD):
        """Nach 'vorheriger Titel': falls der Skip ein Versehen war, zur gemerkten
        Sekunde springen (laeuft bereits im Worker-Thread)."""
        global _skip_restore
        mem = _skip_restore
        if not mem:
            return
        if time.monotonic() - mem["time"] > SKIP_RESTORE_WINDOW_S:
            _skip_restore = None
            return
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as _Mgr)

            async def go():
                s = (await _Mgr.request_async()).get_current_session()
                if not s:
                    return None
                props = await s.try_get_media_properties_async()
                if (props.title or "") != mem["title"]:
                    return None  # anderer Titel -> nicht eingreifen
                await s.try_change_playback_position_async(int(mem["pos"] * 10_000_000))
                title = props.title or "Medien"
                if props.artist:
                    title += " \u2013 " + props.artist
                return title, await _cover_from_props(props)
            res = _run_winrt(go)
        except Exception:
            res = None
        if not res:
            return
        _skip_restore = None
        title, cover = res
        if len(title) > 48:
            title = title[:47] + "\u2026"
        _post_to_ui(lambda: osd.show(
            title, kind="media", media_icon="rew",
            media_text=f"Weiter bei {_fmt_time(mem['pos'])}", media_cover=cover))


    def handle_media(root: tk.Tk, osd: OSD, skip, play_toggle):
        """Medien-Taste + Rad: Titel wechseln; + Stumm: Play/Pause. Die komplette
        Arbeit (Snapshot, Media-API, Cover) laeuft im Worker-Thread - der Tk-Thread
        bleibt frei und es gibt keine spuerbaren Haenger."""

        def work():
            global _skip_restore
            if skip > 0:
                # Position des laufenden Titels merken - falls der Skip ein Versehen war
                snap = _get_media_snapshot()
                if snap and snap["title"] and snap["pos"] > 10:
                    _skip_restore = {"title": snap["title"], "pos": snap["pos"],
                                     "time": time.monotonic()}
                for _ in range(skip):
                    user32.keybd_event(VK_MEDIA_NEXT, 0, 0, 0)
                    user32.keybd_event(VK_MEDIA_NEXT, 0, 2, 0)
                icon, text = "next", "N\u00e4chster Titel"
            elif skip < 0:
                for _ in range(-skip):
                    user32.keybd_event(VK_MEDIA_PREV, 0, 0, 0)
                    user32.keybd_event(VK_MEDIA_PREV, 0, 2, 0)
                icon, text = "prev", "Vorheriger Titel"
            else:
                icon, text = None, None
            if play_toggle:
                user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
                user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 2, 0)

            time.sleep(0.45)  # Player Zeit geben, Titel/Status zu aktualisieren
            info = get_media_info()
            if play_toggle and skip == 0:
                playing = bool(info and info["playing"])
                ic = "play" if playing else "pause"
                tx = "Wiedergabe" if playing else "Pause"
            else:
                ic, tx = icon, text
            pill = "Medien"
            if info and info.get("title"):
                pill = info["title"]
                if info.get("artist"):
                    pill += " \u2013 " + info["artist"]
                if len(pill) > 48:
                    pill = pill[:47] + "\u2026"
            cover = info.get("cover") if info else None
            _post_to_ui(lambda: osd.show(pill, kind="media", media_icon=ic,
                                         media_text=tx, media_cover=cover))

            if skip < 0 and _skip_restore:
                time.sleep(0.45)  # insgesamt ~0,9 s nach dem Zurueckspringen
                _restore_after_prev(osd)

        threading.Thread(target=work, daemon=True).start()
else:

    def get_media_info():
        """Titel/Interpret/Status/Cover des aktuellen MPRIS-Players (oder None)."""
        return linux_media.get_media_info()


    def _get_media_snapshot():
        return linux_media.get_snapshot()


    def handle_media_seek(osd: OSD, ticks):
        """Medien-Taste + Alt + Rad: im Titel spulen (Worker-Thread, via MPRIS)."""
        secs = ticks * max(1, int(CONFIG.get("spulen_sekunden", 10)))

        def work():
            res = linux_media.seek_by(secs)
            if not res:
                _post_to_ui(lambda: osd.show("Medien", no_session=True))
                return
            new, end, title, cover = res
            if len(title) > 48:
                title = title[:47] + "\u2026"
            _post_to_ui(lambda: osd.show(
                title, kind="media", media_icon="fwd" if secs > 0 else "rew",
                media_text=f"{_fmt_time(new)} / {_fmt_time(end)}", media_cover=cover))

        threading.Thread(target=work, daemon=True).start()


    def _restore_after_prev(osd: OSD):
        """Nach 'vorheriger Titel': falls der Skip ein Versehen war, zur
        gemerkten Sekunde springen (laeuft bereits im Worker-Thread)."""
        global _skip_restore
        mem = _skip_restore
        if not mem:
            return
        if time.monotonic() - mem["time"] > SKIP_RESTORE_WINDOW_S:
            _skip_restore = None
            return
        res = linux_media.restore_position(mem["title"], mem["pos"])
        if not res:
            return
        _skip_restore = None
        title, cover = res
        if len(title) > 48:
            title = title[:47] + "\u2026"
        _post_to_ui(lambda: osd.show(
            title, kind="media", media_icon="rew",
            media_text=f"Weiter bei {_fmt_time(mem['pos'])}", media_cover=cover))


    def handle_media(root: tk.Tk, osd: OSD, skip, play_toggle):
        """Medien-Taste + Rad: Titel wechseln; + Stumm: Play/Pause (MPRIS)."""

        def work():
            global _skip_restore
            if skip > 0:
                snap = _get_media_snapshot()
                if snap and snap["title"] and snap["pos"] > 10:
                    _skip_restore = {"title": snap["title"], "pos": snap["pos"],
                                     "time": time.monotonic()}
                linux_media.next_track(skip)
                icon, text = "next", "N\u00e4chster Titel"
            elif skip < 0:
                linux_media.prev_track(-skip)
                icon, text = "prev", "Vorheriger Titel"
            else:
                icon, text = None, None
            if play_toggle:
                linux_media.play_pause()

            time.sleep(0.45)  # Player Zeit geben, Titel/Status zu aktualisieren
            info = get_media_info()
            if play_toggle and skip == 0:
                playing = bool(info and info["playing"])
                ic = "play" if playing else "pause"
                tx = "Wiedergabe" if playing else "Pause"
            else:
                ic, tx = icon, text
            pill = "Medien"
            if info and info.get("title"):
                pill = info["title"]
                if info.get("artist"):
                    pill += " \u2013 " + info["artist"]
                if len(pill) > 48:
                    pill = pill[:47] + "\u2026"
            cover = info.get("cover") if info else None
            _post_to_ui(lambda: osd.show(pill, kind="media", media_icon=ic,
                                         media_text=tx, media_cover=cover))

            if skip < 0 and _skip_restore:
                time.sleep(0.45)
                _restore_after_prev(osd)

        threading.Thread(target=work, daemon=True).start()


# --------------------- Hoerbare App (Hintergrund-Modifier) ------------------

_bg_cache = {"time": 0.0, "groups": None}


if IS_WINDOWS:
    def _get_music_aumids():
        """AUMIDs der laufenden Medien-Sessions (Windows SMTC). Spielt mindestens
        eine App gerade ab, werden nur die abspielenden zurueckgegeben - sonst alle.
        Spiele u. Ae. haben keine Media-Session und tauchen hier nie auf."""
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _Mgr)

        async def go():
            mgr = await _Mgr.request_async()
            playing, all_ids = set(), set()
            for s in mgr.get_sessions():
                aumid = str(s.source_app_user_model_id or "")
                if not aumid:
                    continue
                all_ids.add(aumid)
                if s.get_playback_info().playback_status == 4:  # spielt
                    playing.add(aumid)
            return playing or all_ids
        return _run_winrt(go)


    def _aumid_matches_proc(aumid, proc_name):
        """Verknuepft eine Media-Session (AUMID) mit einem Prozessnamen.
        Deckt Desktop-Apps ("Spotify.exe", "Comet.V6UIN…") und UWP-Pakete
        ("SpotifyAB.SpotifyMusic_…!Spotify") ab."""
        import re
        a = aumid.lower()
        p = proc_name.lower()
        pbase = p[:-4] if p.endswith(".exe") else p
        if not pbase:
            return False
        if a in (p, pbase):
            return True
        # erster Teil vor dem Punkt, z. B. "comet.v6uin…" -> "comet"
        tail = a.split("!")[-1].replace("/", "\\").split("\\")[-1]
        if tail.split(".")[0] == pbase:
            return True
        # UWP: Prozessname als eigenes Token im AUMID (…!Spotify)
        return pbase in re.split(r"[.!_\\/ ]", a)


    def find_music_apps():
        """Apps, die gerade Musik/Medien wiedergeben (ueber die Windows-Media-
        Session ermittelt), mit ihren Audio-Sessions. Ein laufendes Spiel gibt
        zwar Ton aus, hat aber keine Media-Session -> wird bewusst ignoriert."""
        now = time.monotonic()
        if _bg_cache["groups"] is not None and now - _bg_cache["time"] < 1.5:
            return _bg_cache["groups"]
        aumids = _get_music_aumids()
        groups = []
        if aumids:
            apps = {}
            for s in get_all_audio_sessions():
                if s.Process is None:
                    continue
                try:
                    name = s.Process.name()
                except psutil.Error:
                    continue
                key = _norm(name)
                if key in EXCLUDED_APPS:
                    continue
                if any(_aumid_matches_proc(a, name) for a in aumids):
                    apps.setdefault(key, {"name": name, "sessions": []})["sessions"].append(s)
            groups = sorted(((k, pretty_name(e["name"]), e["sessions"])
                             for k, e in apps.items()), key=lambda g: g[1].lower())
        _bg_cache.update(time=now, groups=groups)
        return groups
else:

    def find_music_apps():
        """Apps mit laufender Musik/Medien-Wiedergabe: MPRIS-Player werden
        ueber ihre PID (bzw. Prozessnamen) den Pulse-Streams zugeordnet.
        Spiele ohne MPRIS-Session werden - wie unter Windows - ignoriert."""
        now = time.monotonic()
        if _bg_cache["groups"] is not None and now - _bg_cache["time"] < 1.5:
            return _bg_cache["groups"]
        players = linux_media.players_info()
        playing = [p for p in players if p.get("playing")] or players
        groups = []
        if playing:
            # Prozessbaeume der Player einsammeln (Browser spielen den Ton
            # oft in einem Kindprozess ab)
            fams = []
            for p in playing:
                fam = set()
                if p.get("pid"):
                    fam.add(p["pid"])
                    try:
                        fam.update(c.pid for c in psutil.Process(p["pid"]).children(recursive=True))
                    except psutil.Error:
                        pass
                words = {w for w in (str(p.get("identity", "")).lower(),
                                     str(p.get("desktop", "")).lower()) if w}
                fams.append((fam, words))
            apps = {}
            for s in get_all_audio_sessions():
                if s.Process is None:
                    continue
                try:
                    name = s.Process.name()
                except psutil.Error:
                    continue
                key = _norm(name)
                if key in EXCLUDED_APPS:
                    continue
                hit = False
                for fam, words in fams:
                    if s.pid and s.pid in fam:
                        hit = True
                        break
                    if any(key in w or w in key for w in words):
                        hit = True
                        break
                if hit:
                    apps.setdefault(key, {"name": name, "sessions": []})["sessions"].append(s)
            groups = sorted(((k, pretty_name(e["name"]), e["sessions"])
                             for k, e in apps.items()), key=lambda g: g[1].lower())
        _bg_cache.update(time=now, groups=groups)
        return groups


# Solange das Musik-Overlay steht, wechseln die Pfeiltasten die App
_bg_ui_until = 0.0


def _selected_music_index(groups):
    sel = _norm(CONFIG.get("musik_app_auswahl", ""))
    return next((i for i, g in enumerate(groups) if g[0] == sel), 0)


_arrow_release_job = None


def _show_music_overlay(osd, groups, idx, current, muted):
    global _bg_ui_until, _arrow_release_job
    _bg_ui_until = time.monotonic() + max(1.0, OSD_TIMEOUT_MS / 1000)
    if not IS_WINDOWS and BG_MOD_VKS:
        # Pfeiltasten nur greifen, solange das Overlay steht (sonst bliebe
        # z. B. Alt+Links im Browser die normale Zurueck-Navigation)
        linux_input.set_arrow_grab(True, BG_MOD_VKS)
        if _arrow_release_job:
            osd.root.after_cancel(_arrow_release_job)
        _arrow_release_job = osd.root.after(
            int(max(1.0, OSD_TIMEOUT_MS / 1000) * 1000) + 50,
            lambda: linux_input.set_arrow_grab(False, ()))
    key, display, _ = groups[idx]
    extras = [d for k, d, s in groups if k != key]
    if len(groups) > 1:
        extras.append("← →  wechseln")
    osd.show(display, volume=current, muted=muted, extra_pills=extras, extra_dim=True)


def handle_bg_change(osd: OSD, delta, mute_toggle):
    """Musik-Modifier: regelt genau EINE Musik-App (die ausgewaehlte).
    Andere laufende Player erscheinen gedimmt darueber; Pfeiltasten wechseln."""
    global _last_adjust
    groups = find_music_apps()
    if not groups:
        osd.show("Musik", no_session=True, note="keine Wiedergabe")
        return
    idx = _selected_music_index(groups)
    key, display, sessions = groups[idx]
    try:
        volumes = [s.SimpleAudioVolume for s in sessions]
        current = volumes[0].GetMasterVolume()
        muted = bool(volumes[0].GetMute())
        if mute_toggle:
            muted = not muted
            for v in volumes:
                v.SetMute(muted, None)
        if delta:
            current = min(1.0, max(0.0, current + delta * APP_VOL_STEP))
            for v in volumes:
                v.SetMasterVolume(current, None)
            if muted and delta > 0:
                muted = False
                for v in volumes:
                    v.SetMute(False, None)
    except Exception:
        _bg_cache["groups"] = None
        return
    if delta:
        _last_adjust = {"kind": "app", "display": display, "volumes": volumes}
    _show_music_overlay(osd, groups, idx, current, muted)


def handle_bg_switch(osd: OSD, steps):
    """Pfeiltasten (bei sichtbarem Musik-Overlay): naechste/vorherige Musik-App."""
    groups = find_music_apps()
    if not groups:
        return
    idx = (_selected_music_index(groups) + steps) % len(groups)
    CONFIG["musik_app_auswahl"] = groups[idx][0]
    save_config()
    try:
        v = groups[idx][2][0].SimpleAudioVolume
        current, muted = v.GetMasterVolume(), bool(v.GetMute())
    except Exception:
        current, muted = 0.0, False
    _show_music_overlay(osd, groups, idx, current, muted)


# --------------- Kommunikations-Apps (Discord, TeamSpeak, ...) --------------

def find_comm_apps():
    """Laufende Kommunikations-Apps (aus CONFIG) mit Audio-Sessions."""
    apps = {}
    for s in get_all_audio_sessions():
        if s.Process is None:
            continue
        try:
            name = s.Process.name()
        except psutil.Error:
            continue
        key = _norm(name)
        if key in COMM_APPS and key not in EXCLUDED_APPS:
            apps.setdefault(key, {"name": pretty_name(name), "sessions": []})["sessions"].append(s)
    return sorted(((k, e["name"], e["sessions"]) for k, e in apps.items()),
                  key=lambda g: g[1].lower())


def handle_comm_change(osd: OSD, delta, mute_toggle):
    """Kommunikations-Modifier: regelt alle laufenden Comm-Apps gemeinsam
    (Discord + TeamSpeak je um denselben Schritt, eigene Pille pro App)."""
    global _last_adjust
    groups = find_comm_apps()
    if not groups:
        osd.show("Kommunikation", no_session=True, note="keine App aktiv")
        return
    results, adjusted = [], []
    for key, display, sessions in groups:
        try:
            volumes = [s.SimpleAudioVolume for s in sessions]
            current = volumes[0].GetMasterVolume()
            muted = bool(volumes[0].GetMute())
            if mute_toggle:
                muted = not muted
                for v in volumes:
                    v.SetMute(muted, None)
            if delta:
                current = min(1.0, max(0.0, current + delta * APP_VOL_STEP))
                for v in volumes:
                    v.SetMasterVolume(current, None)
                if muted and delta > 0:
                    muted = False
                    for v in volumes:
                        v.SetMute(False, None)
        except Exception:
            continue
        results.append((display, current, muted))
        adjusted.append((display, volumes))
    if not results:
        return
    if delta:
        _last_adjust = {"kind": "multi", "groups": adjusted}
    d0, c0, m0 = results[0]
    osd.show(d0, volume=c0, muted=m0,
             extra_pills=[f"{d} \u2013 {round(c * 100)} %" for d, c, m in results[1:]])


# ----------------------------- App-Regeln -----------------------------------

_rules_seen = None


def rules_tick(root: tk.Tk):
    """Wendet Regeln (Startlautstaerke, Stumm) auf neu auftauchende
    Audio-Sitzungen an. Laeuft nur, wenn solche Regeln existieren."""
    global _rules_seen
    try:
        if not any(x.get("typ") in ("startlautstaerke", "stumm")
                   for rs in RULES_BY_APP.values() for x in rs):
            _rules_seen = None
            root.after(4000, rules_tick, root)
            return
        current = {}
        for s in get_all_audio_sessions():
            if s.Process is None:
                continue
            try:
                current[(s.Process.pid, _norm(s.Process.name()))] = s
            except psutil.Error:
                continue

        if _rules_seen is None:
            _rules_seen = set(current)  # Bestand beim Start nicht anfassen
        else:
            for key, session in current.items():
                if key in _rules_seen:
                    continue
                for rule in RULES_BY_APP.get(key[1], []):
                    try:
                        if rule.get("typ") == "startlautstaerke":
                            wert = min(100, max(0, int(rule.get("wert", 100))))
                            session.SimpleAudioVolume.SetMasterVolume(wert / 100, None)
                        elif rule.get("typ") == "stumm":
                            session.SimpleAudioVolume.SetMute(True, None)
                    except Exception:
                        logging.exception("Regel konnte nicht angewendet werden: %s", rule)
            _rules_seen = set(current)
    except Exception:
        logging.exception("Fehler beim Anwenden der App-Regeln")

    root.after(4000, rules_tick, root)


# ----------------------------- Numpad-Hotkeys -------------------------------

def _run_action(typ, ziel):
    """Fuehrt eine einzelne Aktion aus (im Worker-Thread aufgerufen)."""
    typ = (typ or "").lower()
    target = os.path.expandvars(str(ziel))
    if typ in ("programm", "website", "ordner", "datei"):
        if IS_WINDOWS:
            os.startfile(target)  # Windows waehlt die passende App
        elif typ == "programm" and not target.startswith(("http://", "https://")):
            subprocess.Popen(target, shell=True, start_new_session=True)
        else:
            subprocess.Popen(["xdg-open", os.path.expanduser(target)],
                             start_new_session=True)
    elif typ == "befehl":
        if IS_WINDOWS:
            # ohne CREATE_NO_WINDOW blitzt bei jedem Befehls-Hotkey ein
            # cmd-Fenster auf
            subprocess.Popen(str(ziel), shell=True,
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                             | subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(str(ziel), shell=True, start_new_session=True)


def run_hotkey(digit, root, osd):
    h = HOTKEYS_BY_DIGIT.get(digit)
    if not h:
        return
    name = h.get("name") or h.get("ziel") or f"Aktion {digit}"

    def work():
        try:
            if (h.get("typ") or "").lower() == "setup":
                for step in h.get("ziel") or []:
                    if isinstance(step, dict):
                        _run_action(step.get("typ"), step.get("ziel"))
                        time.sleep(0.15)
            else:
                _run_action(h.get("typ"), h.get("ziel"))
            _post_to_ui(lambda: _hotkey_feedback(root, osd, "\u25B6 " + str(name)))
        except Exception:
            logging.exception("Hotkey-Aktion fehlgeschlagen: %s", h)
            _post_to_ui(lambda: _hotkey_feedback(root, osd, "Fehler: " + str(name)))

    threading.Thread(target=work, daemon=True).start()


def _hotkey_feedback(root, osd, text):
    try:
        osd.show_hint(text)
        root.after(1400, osd.hide_hint)
    except Exception:
        pass


# ----------------------------- Autostart ------------------------------------

AUTOSTART_LABEL = "Mit Windows starten" if IS_WINDOWS else "Beim Anmelden starten"


def autostart_target():
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(__file__)


if IS_WINDOWS:
    # Autostart laeuft ueber eine Anmelde-Aufgabe der Aufgabenplanung, nicht
    # mehr ueber den Autostart-Ordner. Gruende:
    #   * Eine Verknuepfung im Autostart-Ordner kann Windows still uebergehen
    #     (Schalter im Task-Manager, Timing beim Anmelden). Der Nutzer sieht
    #     dann einen aktivierten Haken, und trotzdem startet nichts - genau
    #     dieser Fall trat hier auf.
    #   * Eine Aufgabe laesst sich abfragen: ob es sie gibt und ob sie aktiv
    #     ist. Damit kann autostart_enabled() die Wahrheit sagen, statt nur
    #     zu pruefen, ob irgendeine Datei existiert.
    #   * Die Startverzoegerung gibt Audiogeraeten und der Taskleiste Zeit,
    #     bereit zu sein.
    # Adminrechte braucht das nicht - die Aufgabe laeuft im eigenen Konto.
    TASK_NAME = "Fluneit"
    _STARTUP_APPROVED = (r"Software\Microsoft\Windows\CurrentVersion"
                         r"\Explorer\StartupApproved\StartupFolder")

    def _startup_lnk_path():
        return os.path.join(os.environ["APPDATA"],
                            "Microsoft", "Windows", "Start Menu", "Programs",
                            "Startup", "Fluneit.lnk")

    def _schtasks(*args):
        """schtasks aufrufen -> (returncode, Ausgabe)."""
        try:
            p = subprocess.run(["schtasks.exe", *args], capture_output=True,
                               text=True, encoding="cp850", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW,
                               timeout=25)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.SubprocessError) as e:
            logging.warning("schtasks nicht aufrufbar: %s", e)
            return -1, str(e)

    def _task_state():
        """None = keine Aufgabe, sonst "aktiv" oder "deaktiviert"."""
        rc, out = _schtasks("/query", "/TN", TASK_NAME, "/FO", "LIST")
        if rc != 0:
            return None
        for line in out.splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            if key.strip().lower().startswith("status"):
                v = value.strip().lower()
                return "deaktiviert" if v.startswith(("deaktiviert", "disabled")) \
                    else "aktiv"
        return "aktiv"

    def _xml_escape(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    def _task_xml():
        """Aufgabendefinition. Als XML statt ueber schtasks-Schalter, weil
        sich nur so das Zeitlimit abschalten laesst (s. ExecutionTimeLimit)."""
        target = autostart_target()
        user = "{}\\{}".format(os.environ.get("USERDOMAIN", ""),
                               os.environ.get("USERNAME", ""))
        if getattr(sys, "frozen", False):
            command, arguments = target, "--autostart"
        else:
            # Aus dem Quellcode ueber pythonw starten, sonst haengt beim
            # Anmelden ein Konsolenfenster daran
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            command = pyw if os.path.exists(pyw) else sys.executable
            arguments = '"{}" --autostart'.format(target)
        e = _xml_escape
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" '
            'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            "    <Description>Startet Fluneit beim Anmelden.</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <LogonTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            "      <UserId>" + e(user) + "</UserId>\n"
            # Kurz warten: beim Anmelden sind Audiogeraete und Taskleiste
            # oft noch nicht bereit
            "      <Delay>PT20S</Delay>\n"
            "    </LogonTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            "      <UserId>" + e(user) + "</UserId>\n"
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>LeastPrivilege</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            # Auf Notebooks nicht am Akku scheitern und nicht beendet werden,
            # wenn der Strom ausgeht
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <AllowHardTerminate>false</AllowHardTerminate>\n"
            "    <StartWhenAvailable>false</StartWhenAvailable>\n"
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
            "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
            "    <Enabled>true</Enabled>\n"
            "    <Hidden>false</Hidden>\n"
            "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
            "    <IdleSettings>\n"
            "      <StopOnIdleEnd>false</StopOnIdleEnd>\n"
            "      <RestartOnIdle>false</RestartOnIdle>\n"
            "    </IdleSettings>\n"
            # PT0S = kein Zeitlimit. Ohne das wuerde Windows die Aufgabe -
            # und damit Fluneit - nach drei Tagen Laufzeit beenden.
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "    <Priority>7</Priority>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            "      <Command>" + e(command) + "</Command>\n"
            "      <Arguments>" + e(arguments) + "</Arguments>\n"
            "      <WorkingDirectory>" + e(APP_DIR) + "</WorkingDirectory>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n")

    def _create_task():
        """Anmelde-Aufgabe anlegen bzw. ersetzen. True bei Erfolg."""
        path = os.path.join(tempfile.gettempdir(), "fluneit_autostart.xml")
        try:
            # schtasks liest die Datei ausschliesslich als UTF-16
            with open(path, "w", encoding="utf-16") as f:
                f.write(_task_xml())
        except OSError:
            logging.exception("Aufgaben-XML nicht schreibbar")
            return False
        rc, out = _schtasks("/create", "/TN", TASK_NAME, "/XML", path, "/F")
        try:
            os.unlink(path)
        except OSError:
            pass
        if rc != 0:
            logging.warning("Anmelde-Aufgabe nicht angelegt (rc=%s): %s",
                            rc, out.strip()[:200])
            return False
        return _task_state() == "aktiv"

    def _lnk_blocked():
        """Hat Windows die Verknuepfung im Autostart-Ordner abgeschaltet?
        Der Zustand steht in StartupApproved: erstes Byte 3 = deaktiviert
        (dahinter steht der Zeitpunkt), 2 = erlaubt."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_APPROVED) as k:
                value, _typ = winreg.QueryValueEx(k, "Fluneit.lnk")
        except OSError:
            return False              # kein Eintrag = erlaubt
        return bool(value) and value[0] == 3

    def _write_lnk():
        """Rueckfallebene, falls die Aufgabenplanung nicht mitspielt."""
        lnk = _startup_lnk_path()
        target = autostart_target()
        if getattr(sys, "frozen", False):
            args = ""
        else:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            target = pyw if os.path.exists(pyw) else sys.executable
            args = "$s.Arguments='\"{}\"';".format(autostart_target())
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
              "$s.TargetPath='{}';{}$s.WorkingDirectory='{}';"
              "$s.Description='Fluneit';$s.Save()").format(lnk, target, args, APP_DIR)
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           creationflags=subprocess.CREATE_NO_WINDOW,
                           capture_output=True, timeout=25)
        except (OSError, subprocess.SubprocessError):
            logging.exception("Verknuepfung nicht anlegbar")
            return False
        return os.path.exists(lnk)

    def _remove_lnk():
        try:
            os.remove(_startup_lnk_path())
        except FileNotFoundError:
            pass
        except OSError:
            logging.exception("Verknuepfung nicht loeschbar")
            return False
        return True

    def autostart_enabled():
        """Startet Fluneit wirklich beim Anmelden? Prueft den Zustand und
        nicht bloss, ob eine Datei existiert - sonst zeigt die Oberflaeche
        einen aktivierten Schalter, obwohl Windows nichts startet."""
        state = _task_state()
        if state is not None:
            return state == "aktiv"
        return os.path.exists(_startup_lnk_path()) and not _lnk_blocked()

    def autostart_status():
        """(aktiv, Klartext) - was genau eingerichtet ist."""
        state = _task_state()
        if state == "aktiv":
            return True, "Als Anmelde-Aufgabe eingerichtet, startet 20 s nach dem Anmelden"
        if state == "deaktiviert":
            return False, "Die Anmelde-Aufgabe ist in der Aufgabenplanung deaktiviert"
        if os.path.exists(_startup_lnk_path()):
            if _lnk_blocked():
                return False, ("Verknüpfung im Autostart-Ordner vorhanden, aber von "
                               "Windows deaktiviert (Task-Manager → Autostart)")
            return True, "Verknüpfung im Autostart-Ordner"
        return False, "Nicht eingerichtet"

    def set_autostart(enabled):
        """Autostart ein-/ausschalten. Gibt zurueck, ob es geklappt hat -
        frueher schlug das still fehl und der Schalter sprang zurueck."""
        if not enabled:
            rc, _out = _schtasks("/delete", "/TN", TASK_NAME, "/F")
            _remove_lnk()
            ok = not autostart_enabled()
            if not ok:
                logging.warning("Autostart liess sich nicht abschalten (rc=%s)", rc)
            return ok

        if _create_task():
            # Die Aufgabe uebernimmt - alte Verknuepfung weg, sonst startet
            # Fluneit beim Anmelden zweimal
            _remove_lnk()
            return True

        logging.warning("Anmelde-Aufgabe fehlgeschlagen, weiche auf den "
                        "Autostart-Ordner aus")
        if not _write_lnk():
            return False
        if _lnk_blocked():
            logging.warning("Verknuepfung ist in Windows deaktiviert")
            return False
        return True


else:
    def _autostart_desktop_path():
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(base, "autostart", "fluneit.desktop")


    def autostart_enabled():
        return os.path.exists(_autostart_desktop_path())


    def autostart_status():
        """(aktiv, Klartext) - gleiche Schnittstelle wie unter Windows."""
        path = _autostart_desktop_path()
        if os.path.exists(path):
            return True, "Autostart-Eintrag unter " + path
        return False, "Nicht eingerichtet"

    def set_autostart(enabled):
        """Gibt zurueck, ob es geklappt hat (wie die Windows-Fassung)."""
        path = _autostart_desktop_path()
        if not enabled:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                logging.exception("Autostart-Eintrag nicht loeschbar")
                return False
            return True
        target = autostart_target()
        if getattr(sys, "frozen", False):
            exec_line = '"{}" --autostart'.format(target)
        else:
            exec_line = '"{}" "{}" --autostart'.format(sys.executable, target)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("[Desktop Entry]\n"
                        "Type=Application\n"
                        "Name=Fluneit\n"
                        "Exec=" + exec_line + "\n"
                        "Path=" + APP_DIR + "\n"
                        "X-GNOME-Autostart-enabled=true\n"
                        # kurz warten, damit Audiodienst und Leiste bereit sind
                        "X-GNOME-Autostart-Delay=15\n"
                        "Comment=Per-App-Lautstaerke ueber das Lautstaerkerad\n")
        except OSError:
            logging.exception("Autostart-Eintrag konnte nicht geschrieben werden")
            return False
        return os.path.exists(path)


# ----------------------------- Tray-Symbol ----------------------------------

def make_icon_image(size=64):
    """Lautsprecher-Icon, wird fuer Tray und .ico-Datei benutzt."""
    ss = 4
    n = size * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 64
    d.rounded_rectangle([2 * u, 2 * u, 62 * u, 62 * u], 14 * u, fill="#2d2d2c")
    d.polygon([(13 * u, 25 * u), (24 * u, 25 * u), (36 * u, 14 * u),
               (36 * u, 50 * u), (24 * u, 39 * u), (13 * u, 39 * u)], fill="#ffffff")
    d.arc([37 * u, 22 * u, 51 * u, 42 * u], start=-60, end=60, fill="#4cc2ff", width=int(3.5 * u))
    d.arc([41 * u, 16 * u, 61 * u, 48 * u], start=-55, end=55, fill="#4cc2ff", width=int(3.5 * u))
    return img.resize((size, size), Image.LANCZOS)


def make_tray_image():
    """Tray-Icon nach assets/tray-default.svg des Design-Systems (weiss, monochrom).
    Linux: das farbige App-Icon mit dunkler Kachel - das monochrome PNG mit
    Transparenz wird vom xorg-Tray-Backend als schwarzes Quadrat gerendert."""
    if not IS_WINDOWS:
        return make_icon_image(32)
    try:
        return Image.open(resource_path("assets", "tray-default-32.png"))
    except Exception:
        return make_icon_image(32)


def _select_pystray_backend():
    """Linux: bestes verfuegbares pystray-Backend waehlen, BEVOR pystray
    importiert wird (die automatische Wahl stolpert ueber fehlende
    AppIndicator-Typelibs, statt weiterzuprobieren)."""
    if IS_WINDOWS or "PYSTRAY_BACKEND" in os.environ:
        return
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if "KDE" in desktop:
        # Plasma bringt xembedsniproxy mit - der xorg-Weg ist dort zuverlaessig,
        # waehrend AppIndicator je nach Typelib-Stand still scheitern kann
        os.environ["PYSTRAY_BACKEND"] = "xorg"
        return
    try:
        import gi
        for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(ns, "0.1")
                os.environ["PYSTRAY_BACKEND"] = "appindicator"
                return
            except ValueError:
                continue
        gi.require_version("Gtk", "3.0")
        os.environ["PYSTRAY_BACKEND"] = "gtk"
        return
    except Exception:
        pass
    os.environ["PYSTRAY_BACKEND"] = "xorg"


def _patch_tray_middle_click():
    """pystray kennt keinen Mittelklick - wir haengen uns in dessen
    Tray-Nachrichten: mittlere Maustaste = Play/Pause. (Nur Windows;
    unter Linux haengt das vom Tray-Backend ab.)"""
    if not IS_WINDOWS:
        return
    try:
        import pystray._win32 as _pw
        if getattr(_pw.Icon, "_fluneit_patched", False):
            return
        orig = _pw.Icon._on_notify

        def patched(self, wparam, lparam):
            if lparam == 0x0208:  # WM_MBUTTONUP
                event_queue.put("media_mute")
            return orig(self, wparam, lparam)

        _pw.Icon._on_notify = patched
        _pw.Icon._fluneit_patched = True
    except Exception:
        logging.exception("Mittelklick am Tray nicht verfuegbar")


def make_tray_icon(on_quit, on_restart, on_mixer, on_settings):
    if not IS_WINDOWS:
        # Bevorzugt: natives StatusNotifierItem via D-Bus (Plasma rendert
        # xembed-Icons von pystray oft als schwarzes Quadrat oder gar nicht)
        try:
            import linux_tray
            title = f"Fluneit {__version__} - Strg + Lautstärkerad = App-Lautstärke"
            tray = linux_tray.Tray(
                make_icon_image(48), title, AUTOSTART_LABEL, autostart_enabled,
                on_mixer, on_settings,
                lambda: set_autostart(not autostart_enabled()),
                on_restart, on_quit,
                lambda: event_queue.put("media_mute"))
            if tray.start():
                return tray
            logging.warning("SNI-Tray nicht verfuegbar, falle auf pystray zurueck")
        except Exception:
            logging.exception("SNI-Tray fehlgeschlagen, falle auf pystray zurueck")
    _select_pystray_backend()
    import pystray
    _patch_tray_middle_click()

    def toggle_autostart(icon, item):
        want = not autostart_enabled()
        if not set_autostart(want) and want:
            # Nicht stillschweigend scheitern - sonst wundert man sich, warum
            # der Haken beim naechsten Oeffnen wieder weg ist.
            logging.warning("Autostart liess sich nicht einrichten")
            event_queue.put("autostart_fehler")

    def toggle_fx(icon, item):
        # Ueber die Queue, damit das Umschalten im Hauptthread laeuft: die
        # COM-Objekte fuer den Geraetewechsel gehoeren dorthin.
        event_queue.put("fx_toggle")

    menu = pystray.Menu(
        pystray.MenuItem("Mixer", on_mixer, default=True),
        pystray.MenuItem("Einstellungen öffnen", on_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Effekte", toggle_fx, checked=lambda item: fx_running()),
        pystray.MenuItem(AUTOSTART_LABEL, toggle_autostart,
                         checked=lambda item: autostart_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Neu starten", on_restart),
        pystray.MenuItem("Beenden", on_quit),
    )
    # Bindestrich statt Gedankenstrich: das xorg-Backend schreibt den Titel
    # latin-1-kodiert ins WM_NAME-Property und wuerde an "–" scheitern.
    # Taste aus der Konfiguration statt fest verdrahtet.
    app_vks = _parse_mods(CONFIG.get("modifier", "strg")) or frozenset({0x11})
    keys = " + ".join(_MOD_NAMES.get(v, "?")
                      for v in sorted(app_vks, key=lambda v: _MOD_ORDER.get(v, 9)))
    title = f"Fluneit {__version__} - {keys} + Lautstärkerad = App-Lautstärke"
    icon = pystray.Icon("Fluneit", make_tray_image(), title, menu)
    icon.run_detached()
    return icon


# ----------------------------- Start -----------------------------------------

def acquire_single_instance():
    """Nur eine Instanz zulassen. Beim Neustart kann die alte Instanz noch kurz
    leben, deshalb ein paar Sekunden warten, bevor aufgegeben wird."""
    if IS_WINDOWS:
        for _ in range(15):
            ctypes.set_last_error(0)
            handle = kernel32.CreateMutexW(None, True, "Fluneit_SingleInstance")
            if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
                return handle  # Referenz halten, bis der Prozess endet
            kernel32.CloseHandle(handle)
            time.sleep(0.4)
        return None
    import fcntl
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(base, "fluneit.lock")
    for _ in range(15):
        f = None
        try:
            # "a" statt "w": nicht die PID der noch laufenden Instanz
            # ueberschreiben, bevor der flock ueberhaupt geprueft wurde
            f = open(path, "a+")
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.seek(0)
            f.truncate()
            f.write(str(os.getpid()))
            f.flush()
            return f  # Datei-Handle halten, bis der Prozess endet
        except OSError:
            if f is not None:
                try:
                    f.close()
                except Exception:
                    pass
            time.sleep(0.4)
    return None


def main():
    setup_logging()
    logging.info("Fluneit %s gestartet (%s, %s)", __version__,
                 "Anmeldung" if started_by_autostart() else "manuell",
                 "Exe" if getattr(sys, "frozen", False) else "Quellcode")

    mutex = acquire_single_instance()
    if mutex is None:
        sys.exit(0)  # laeuft bereits

    # Steht hier noch ein Geraet zum Zurueckstellen, wurde Fluneit im
    # Brueckenbetrieb hart beendet. Zuerst aufraeumen, sonst hat der Nutzer
    # keinen Ton und weiss nicht, warum.
    if CONFIG.get("effekte_wiederherstellen"):
        fx_restore_device("Aufraeumen nach unsauberem Ende")

    if IS_WINDOWS:
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_ssize_t(-4))  # Per-Monitor v2
        except Exception:
            pass
        threading.Thread(target=hook_thread, daemon=True).start()
    else:
        if not linux_input.is_x11():
            logging.warning("Keine X11-Sitzung erkannt - globale Tastenkombinationen "
                            "funktionieren unter Wayland nicht.")
        linux_input.start(event_queue)
        # Grabs mit der geladenen Konfiguration setzen (der Aufruf in
        # apply_config lief noch vor dem Thread-Start ins Leere)
        linux_input.update_bindings(HOOK_FUNCS, HOTKEYS_MODIFIER_VK,
                                    set(HOTKEYS_BY_DIGIT))

    root = tk.Tk()
    root.withdraw()
    osd = OSD(root)

    import ui
    ui.init(sys.modules[__name__], root)
    flyout = ui.Flyout(root, osd.scale)

    icon = None

    def quit_app(icon_=None, item=None):
        try:
            icon.stop()
        except Exception:
            pass
        root.after(0, root.destroy)

    restart_requested = []

    def restart_app(icon_=None, item=None):
        restart_requested.append(True)
        quit_app()

    def open_mixer(icon_=None, item=None):
        root.after(0, flyout.toggle)

    def open_settings(icon_=None, item=None):
        root.after(0, lambda: ui.open_settings(root))

    try:
        icon = make_tray_icon(quit_app, restart_app, open_mixer, open_settings)
    except Exception:
        logging.exception("Tray-Symbol konnte nicht erstellt werden")

    if not CONFIG.get("onboarding_gezeigt"):
        def onboarding_done():
            CONFIG["onboarding_gezeigt"] = True
            save_config()
        root.after(600, lambda: ui.OnboardingWindow(root, onboarding_done))

    root.after(30, process_events, root, osd)
    root.after(200, watch_modifiers, root, osd)
    root.after(2000, rules_tick, root)
    if CONFIG.get("effekte_aktiv") and CONFIG.get("effekte_bruecke"):
        # war beim letzten Beenden an -> nach kurzer Wartezeit wieder starten
        # (die Audiogeraete sind direkt nach dem Anmelden oft noch nicht bereit)
        root.after(3000, lambda: fx_start())
    if CONFIG.get("effekte_mikrofon_aktiv"):
        root.after(3500, lambda: fx_mic_start())

    try:
        root.mainloop()
    finally:
        # Vor allem anderen: Effekte beenden und das Standardgeraet
        # zurueckstellen, damit niemand ohne Ton zurueckbleibt.
        fx_shutdown()
        if icon:
            try:
                icon.stop()
            except Exception:
                pass
        if restart_requested:
            if getattr(sys, "frozen", False):
                # unter Linux aus der sterbenden Sitzung loesen, sonst nimmt
                # das Ende des alten Prozesses den neuen mit
                subprocess.Popen([sys.executable], cwd=APP_DIR,
                                 **({} if IS_WINDOWS else {"start_new_session": True}))
            elif IS_WINDOWS:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                subprocess.Popen([pythonw, os.path.abspath(__file__)], cwd=APP_DIR)
            else:
                subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                                 cwd=APP_DIR, start_new_session=True)
        os._exit(0)  # beendet auch den Hook-Thread


if __name__ == "__main__":
    main()
