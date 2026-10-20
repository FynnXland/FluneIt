"""Linux-Tray: natives StatusNotifierItem (SNI) ueber D-Bus.

Plasma rendert xembed-Icons (pystray xorg/gtk) haeufig als schwarzes
Quadrat oder gar nicht - deshalb sprechen wir das KDE/freedesktop-
Tray-Protokoll direkt: org.kde.StatusNotifierItem plus ein minimales
com.canonical.dbusmenu fuer das Rechtsklick-Menue. Keine zusaetzlichen
Bibliotheken noetig (dbus-next ist ohnehin dabei).

Verhalten wie unter Windows:
- Linksklick  -> Mixer-Flyout
- Mittelklick -> Play/Pause
- Rechtsklick -> Menue (Mixer, Einstellungen, Autostart, Neu starten, Beenden)
"""

import asyncio
import logging
import threading

from dbus_next import Variant
from dbus_next.service import ServiceInterface, method, dbus_property, signal, PropertyAccess

from fluneit import linux_media


def _pixmap_from_pil(img):
    """PIL-RGBA -> SNI-IconPixmap a(iiay): ARGB32, netzwerk-Byteorder."""
    img = img.convert("RGBA")
    w, h = img.size
    raw = bytearray()
    for r, g, b, a in img.getdata():
        raw += bytes((a, r, g, b))
    return [[w, h, bytes(raw)]]


class _MenuIface(ServiceInterface):
    """Minimales com.canonical.dbusmenu fuer das statische Tray-Menue."""

    def __init__(self, tray):
        super().__init__("com.canonical.dbusmenu")
        self.tray = tray
        self.revision = 1

    def _layout(self):
        t = self.tray

        def item(mid, label, extra=None):
            props = {"label": Variant("s", label)}
            if extra:
                props.update(extra)
            return Variant("(ia{sv}av)", [mid, props, []])

        sep = {"type": Variant("s", "separator"), "label": Variant("s", "")}
        children = [
            item(1, "Mixer"),
            item(2, "Einstellungen öffnen"),
            Variant("(ia{sv}av)", [3, dict(sep), []]),
            item(4, t.autostart_label, {
                "toggle-type": Variant("s", "checkmark"),
                "toggle-state": Variant("i", 1 if t.autostart_enabled() else 0),
            }),
            Variant("(ia{sv}av)", [5, dict(sep), []]),
            item(6, "Neu starten"),
            item(7, "Beenden"),
        ]
        return [0, {"children-display": Variant("s", "submenu")}, children]

    @method()
    def GetLayout(self, parentId: "i", recursionDepth: "i", propertyNames: "as") -> "u(ia{sv}av)":
        return [self.revision, self._layout()]

    @method()
    def GetGroupProperties(self, ids: "ai", propertyNames: "as") -> "a(ia{sv})":
        return []

    @method()
    def GetProperty(self, id: "i", name: "s") -> "v":
        return Variant("s", "")

    @method()
    def Event(self, id: "i", eventId: "s", data: "v", timestamp: "u"):
        if eventId == "clicked":
            self.tray.on_menu_click(id)

    @method()
    def EventGroup(self, events: "a(isvu)") -> "ai":
        for id_, event_id, _data, _ts in events:
            if event_id == "clicked":
                self.tray.on_menu_click(id_)
        return []

    @method()
    def AboutToShow(self, id: "i") -> "b":
        return False

    @method()
    def AboutToShowGroup(self, ids: "ai") -> "abab":
        return [[], []]

    @signal()
    def LayoutUpdated(self) -> "ui":
        return [self.revision, 0]

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":
        return []


class _SniIface(ServiceInterface):
    def __init__(self, tray):
        super().__init__("org.kde.StatusNotifierItem")
        self.tray = tray

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return "fluneit"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return self.tray.title

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def WindowId(self) -> "i":
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":
        return self.tray.pixmap

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def ToolTip(self) -> "(sa(iiay)ss)":
        return ["", [], self.tray.title, ""]

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return "/MenuBar"

    @method()
    def Activate(self, x: "i", y: "i"):
        self.tray.on_activate()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):
        self.tray.on_middle_click()

    @method()
    def ContextMenu(self, x: "i", y: "i"):
        pass  # Plasma nutzt das dbusmenu

    @method()
    def Scroll(self, delta: "i", orientation: "s"):
        pass

    @signal()
    def NewIcon(self):
        pass

    @signal()
    def NewStatus(self, status: "s"):
        pass


class Tray:
    """Oeffentliche Schnittstelle - Gegenstueck zu pystray.Icon."""

    def __init__(self, image, title, autostart_label, autostart_enabled,
                 on_mixer, on_settings, on_toggle_autostart, on_restart,
                 on_quit, on_middle_click):
        self.pixmap = _pixmap_from_pil(image)
        self.title = title
        self.autostart_label = autostart_label
        self.autostart_enabled = autostart_enabled
        self._cb = {1: on_mixer, 2: on_settings, 4: on_toggle_autostart,
                    6: on_restart, 7: on_quit}
        self.on_activate = on_mixer
        self.on_middle_click = on_middle_click
        self._menu = _MenuIface(self)
        self._sni = _SniIface(self)
        self._registered = threading.Event()
        self._ok = False

    def on_menu_click(self, item_id):
        cb = self._cb.get(item_id)
        if cb:
            try:
                cb()
            except Exception:
                logging.exception("Tray-Menueaktion fehlgeschlagen")
        if item_id == 4:
            # Haekchen aktualisieren
            self._menu.revision += 1
            try:
                self._menu.LayoutUpdated()
            except Exception:
                pass

    def start(self):
        """Registriert das Item beim StatusNotifierWatcher (via MPRIS-Bus-Thread).
        Liefert True bei Erfolg."""

        async def go(bus):
            from dbus_next import Message
            bus.export("/MenuBar", self._menu)
            bus.export("/StatusNotifierItem", self._sni)
            reply = await bus.call(Message(
                destination="org.kde.StatusNotifierWatcher",
                path="/StatusNotifierWatcher",
                interface="org.kde.StatusNotifierWatcher",
                member="RegisterStatusNotifierItem",
                signature="s", body=[bus.unique_name]))
            return True

        try:
            self._ok = bool(linux_media._run(go, timeout=3.0))
        except Exception:
            logging.exception("SNI-Registrierung fehlgeschlagen")
            self._ok = False
        return self._ok

    def stop(self):
        async def go(bus):
            bus.unexport("/StatusNotifierItem", self._sni)
            bus.unexport("/MenuBar", self._menu)
            return True
        try:
            linux_media._run(go, timeout=2.0)
        except Exception:
            pass
