"""Linux-Input-Backend: globale Tastenkombinationen ueber X11-Grabs.

Ersetzt den Windows-Low-Level-Hook (WH_KEYBOARD_LL). Statt alle Tasten
mitzulesen, greifen wir gezielt die konfigurierten Kombinationen ab
(XGrabKey): XF86Audio-Tasten + Modifier, Strg + Numpad, und - nur solange
das Musik-Overlay sichtbar ist - Modifier + Pfeiltasten. Die Taste wird
dadurch automatisch "geschluckt" (wie im Windows-Hook), waehrend die
Lautstaerketasten OHNE Modifier unangetastet bleiben - dort regelt KDE
weiter selbst (inkl. eigenem OSD).

Der Grab-Thread schlaeft in select() auf der X-Verbindung: 0 % CPU im
Leerlauf, Ereignisse kommen ohne Polling an.

Achtung: funktioniert nur unter X11 (Kubuntu-Standard). Unter Wayland
liefert der X-Server (XWayland) keine globalen Grabs fuer native Fenster.
"""

import logging
import os
import select
import threading

from Xlib import X, display as xdisplay

# Virtuelle Tastencodes wie in fluneit (_MODIFIER_VKS): 0x10/0x11/0x12
VK_SHIFT, VK_CTRL, VK_ALT = 0x10, 0x11, 0x12
_VK_TO_MASK = {VK_SHIFT: X.ShiftMask, VK_CTRL: X.ControlMask, VK_ALT: X.Mod1Mask}
_BASE_MASK = X.ShiftMask | X.ControlMask | X.Mod1Mask

# Keysyms
_XF86_LOWER = 0x1008FF11
_XF86_MUTE = 0x1008FF12
_XF86_RAISE = 0x1008FF13
_XK_LEFT, _XK_RIGHT = 0xFF51, 0xFF53
_XK_KP = {  # KP-Ziffern (NumLock an); Grab erfolgt per Keycode, gilt also immer
    0xFFB0: "0", 0xFFB1: "1", 0xFFB2: "2", 0xFFB3: "3", 0xFFB4: "4",
    0xFFB5: "5", 0xFFB6: "6", 0xFFB7: "7", 0xFFB8: "8", 0xFFB9: "9",
}

# NumLock (Mod2), CapsLock (Lock) und AltGr-Ebenen (Mod5) duerfen zusaetzlich
# gedrueckt sein, ohne den Grab zu verfehlen -> alle Teilmengen mitgrabben.
_IGNORED = []
for a in (0, X.Mod2Mask):
    for b in (0, X.LockMask):
        for c in (0, X.Mod5Mask):
            _IGNORED.append(a | b | c)


def _vkset_to_mask(vkset):
    mask = 0
    for vk in vkset:
        m = _VK_TO_MASK.get(vk)
        if m is None:
            return None
        mask |= m
    return mask


class _GrabThread(threading.Thread):
    """Haelt die Grabs aktuell und uebersetzt KeyPress -> Event-Strings."""

    def __init__(self, event_queue):
        super().__init__(daemon=True, name="x11-grabs")
        self.queue = event_queue
        self.disp = None
        self.root = None
        self._wake_r, self._wake_w = os.pipe()
        self._lock = threading.Lock()
        self._pending = None          # gewuenschte Bindings (vom Tk-Thread gesetzt)
        self._arrow_state = None      # (aktiv, maske) fuer Pfeiltasten
        self._grabbed = []            # [(keycode, volle_maske)]
        self._by_key = {}             # (keycode, basis_maske) -> event-payload
        self._arrow_grabbed = None    # aktuelle Pfeil-Maske oder None

    # ---- vom Tk-Thread aufrufbar ----

    def update_bindings(self, funcs, hotkey_mod_vk, hotkey_digits):
        with self._lock:
            self._pending = (list(funcs), hotkey_mod_vk, set(hotkey_digits))
        self._wake()

    def set_arrow_grab(self, active, mod_vks):
        with self._lock:
            self._arrow_state = (bool(active), frozenset(mod_vks or ()))
        self._wake()

    def _wake(self):
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass

    # ---- Grab-Verwaltung (nur im Thread) ----

    def _keycodes(self, keysym):
        kc = self.disp.keysym_to_keycode(keysym)
        return [kc] if kc else []

    def _grab(self, keycode, mask, payload):
        for extra in _IGNORED:
            try:
                self.root.grab_key(keycode, mask | extra, 0,
                                   X.GrabModeAsync, X.GrabModeAsync)
                self._grabbed.append((keycode, mask | extra))
            except Exception:
                pass
        self._by_key[(keycode, mask)] = payload

    def _ungrab_all(self):
        for keycode, mask in self._grabbed:
            try:
                self.root.ungrab_key(keycode, mask)
            except Exception:
                pass
        self._grabbed = []
        self._by_key = {}
        self._arrow_grabbed = None

    def _apply_bindings(self, funcs, hotkey_mod_vk, hotkey_digits):
        self._ungrab_all()
        # Lautstaerketasten + Modifier-Kombinationen
        for vkset, kind in funcs:
            mask = _vkset_to_mask(vkset)
            if not mask:      # None oder 0 (ohne Modifier NICHT grabben)
                continue
            for keysym, direction in ((_XF86_RAISE, "up"), (_XF86_LOWER, "down"),
                                      (_XF86_MUTE, "mute")):
                for kc in self._keycodes(keysym):
                    self._grab(kc, mask, ("vol", kind, direction))
        # Strg (o. a.) + Numpad-Ziffern
        hk_mask = _VK_TO_MASK.get(hotkey_mod_vk)
        if hk_mask and hotkey_digits:
            for keysym, digit in _XK_KP.items():
                if digit not in hotkey_digits:
                    continue
                for kc in self._keycodes(keysym):
                    self._grab(kc, hk_mask, ("hotkey", digit))
        # Pfeil-Grab-Zustand neu anwenden
        self._apply_arrows()

    def _apply_arrows(self):
        with self._lock:
            state = self._arrow_state
        active, mod_vks = state if state else (False, frozenset())
        mask = _vkset_to_mask(mod_vks) if active else None
        if mask == self._arrow_grabbed:
            return
        # alte Pfeil-Grabs entfernen
        if self._arrow_grabbed is not None:
            keep, drop = [], []
            for kc, m in self._grabbed:
                base = m & _BASE_MASK
                if (kc, base) in self._by_key and self._by_key[(kc, base)][0] == "arrow":
                    drop.append((kc, m))
                else:
                    keep.append((kc, m))
            for kc, m in drop:
                try:
                    self.root.ungrab_key(kc, m)
                except Exception:
                    pass
            self._grabbed = keep
            self._by_key = {k: v for k, v in self._by_key.items() if v[0] != "arrow"}
            self._arrow_grabbed = None
        if mask:
            for keysym, ev in ((_XK_LEFT, "bg_prev"), (_XK_RIGHT, "bg_next")):
                for kc in self._keycodes(keysym):
                    self._grab(kc, mask, ("arrow", ev))
            self._arrow_grabbed = mask

    # ---- Ereignis-Uebersetzung ----

    _VOL_EVENT = {
        "app":   {"up": "up", "down": "down", "mute": "mute"},
        "mic":   {"up": "mic_up", "down": "mic_down", "mute": "mic_mute"},
        "bg":    {"up": "bg_up", "down": "bg_down", "mute": "bg_mute"},
        "comm":  {"up": "comm_up", "down": "comm_down", "mute": "comm_mute"},
        "media": {"up": "media_up", "down": "media_down", "mute": "media_mute"},
        "seek":  {"up": "media_seek_up", "down": "media_seek_down", "mute": "media_mute"},
    }

    def _on_key(self, ev):
        base = ev.state & _BASE_MASK
        payload = self._by_key.get((ev.detail, base))
        if payload is None:
            return
        tag = payload[0]
        if tag == "vol":
            _, kind, direction = payload
            name = self._VOL_EVENT.get(kind, {}).get(direction)
            if name:
                self.queue.put(name)
        elif tag == "hotkey":
            self.queue.put("hotkey_" + payload[1])
        elif tag == "arrow":
            self.queue.put(payload[1])

    # ---- Hauptschleife ----

    def run(self):
        try:
            self.disp = xdisplay.Display()
            self.root = self.disp.screen().root
        except Exception:
            logging.exception("X11-Verbindung fuer Tasten-Grabs fehlgeschlagen")
            return
        xfd = self.disp.fileno()
        while True:
            # ausstehende Binding-Aenderungen uebernehmen
            with self._lock:
                pending, self._pending = self._pending, None
            if pending is not None:
                try:
                    self._apply_bindings(*pending)
                except Exception:
                    logging.exception("Tasten-Grabs konnten nicht gesetzt werden")
            else:
                try:
                    self._apply_arrows()
                except Exception:
                    pass
            self.disp.flush()
            try:
                r, _, _ = select.select([xfd, self._wake_r], [], [])
            except OSError:
                continue
            if self._wake_r in r:
                try:
                    os.read(self._wake_r, 4096)
                except OSError:
                    pass
            if xfd in r:
                try:
                    while self.disp.pending_events():
                        ev = self.disp.next_event()
                        if ev.type == X.KeyPress:
                            self._on_key(ev)
                except Exception:
                    logging.exception("Fehler im X11-Ereignis-Thread")


_thread = None


def start(event_queue):
    """Startet den Grab-Thread (einmalig)."""
    global _thread
    if _thread is None:
        _thread = _GrabThread(event_queue)
        _thread.start()
    return _thread


def update_bindings(funcs, hotkey_mod_vk, hotkey_digits):
    if _thread is not None:
        _thread.update_bindings(funcs, hotkey_mod_vk, hotkey_digits)


def set_arrow_grab(active, mod_vks):
    if _thread is not None:
        _thread.set_arrow_grab(active, mod_vks)


# ----------------------------- Abfragen (Tk-Thread) --------------------------
# Eigene, zweite X-Verbindung: python-xlib ist nicht threadsicher, deshalb
# strikt getrennt vom Grab-Thread. Alle Abfragen laufen im Tk-Thread.

_qlock = threading.Lock()
_qdisp = None


def _query_display():
    global _qdisp
    if _qdisp is None:
        _qdisp = xdisplay.Display()
    return _qdisp


def _atom(name):
    return _query_display().intern_atom(name)


def pressed_modifiers():
    """Frozenset der gehaltenen Modifier als VK-Codes (fuer den Modus-Hinweis)."""
    try:
        with _qlock:
            d = _query_display()
            mask = d.screen().root.query_pointer().mask
        vks = set()
        if mask & X.ShiftMask:
            vks.add(VK_SHIFT)
        if mask & X.ControlMask:
            vks.add(VK_CTRL)
        if mask & X.Mod1Mask:
            vks.add(VK_ALT)
        return frozenset(vks)
    except Exception:
        return frozenset()


def get_foreground_process():
    """(pid, prozessname) des fokussierten Fensters via _NET_ACTIVE_WINDOW."""
    import psutil
    try:
        with _qlock:
            d = _query_display()
            root = d.screen().root
            prop = root.get_full_property(_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
            if not prop or not prop.value or not prop.value[0]:
                return None, None
            win = d.create_resource_object("window", int(prop.value[0]))
            pid_prop = win.get_full_property(_atom("_NET_WM_PID"), X.AnyPropertyType)
        if not pid_prop or not pid_prop.value:
            return None, None
        pid = int(pid_prop.value[0])
        return pid, psutil.Process(pid).name()
    except Exception:
        return None, None


def get_workarea():
    """(x, y, breite, hoehe) des nutzbaren Bildschirmbereichs (ohne Panels)."""
    try:
        with _qlock:
            d = _query_display()
            root = d.screen().root
            prop = root.get_full_property(_atom("_NET_WORKAREA"), X.AnyPropertyType)
            if prop and len(prop.value) >= 4:
                x, y, w, h = (int(v) for v in prop.value[:4])
                return x, y, w, h
            geo = root.get_geometry()
            return 0, 0, geo.width, geo.height
    except Exception:
        return 0, 0, 1920, 1080


def pointer_info():
    """(x, y, taste1_gedrueckt) des Mauszeigers - fuer das Flyout-Schliessen."""
    try:
        with _qlock:
            d = _query_display()
            p = d.screen().root.query_pointer()
        return p.root_x, p.root_y, bool(p.mask & X.Button1Mask)
    except Exception:
        return 0, 0, False


_esc_keycode = None


def escape_down():
    """True, solange die Esc-Taste gedrueckt ist (XQueryKeymap)."""
    global _esc_keycode
    try:
        with _qlock:
            d = _query_display()
            if _esc_keycode is None:
                _esc_keycode = d.keysym_to_keycode(0xFF1B)  # XK_Escape
            keymap = d.query_keymap()
        kc = _esc_keycode
        return bool(keymap[kc // 8] & (1 << (kc % 8)))
    except Exception:
        return False


def is_x11():
    return (os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland"
            and bool(os.environ.get("DISPLAY")))
