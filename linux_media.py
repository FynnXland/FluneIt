"""Linux-Medien-Backend: MPRIS ueber D-Bus (dbus-next, reines Python).

Ersetzt die Windows-SMTC-Aufrufe (winrt). Ein eigener Thread betreibt eine
asyncio-Schleife mit der D-Bus-Verbindung; alle oeffentlichen Funktionen sind
synchron mit Timeout und liefern None, wenn kein Player laeuft oder nicht
antwortet - exakt wie die Windows-Seite.

Player-Auswahl: bevorzugt wird der gerade spielende MPRIS-Player, sonst der
erste vorhandene (z. B. pausierter Spotify).
"""

import io
import logging
import threading
import urllib.parse
import urllib.request

from PIL import Image

_PLAYER_PREFIX = "org.mpris.MediaPlayer2."
_PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
_ROOT_IFACE = "org.mpris.MediaPlayer2"
_PATH = "/org/mpris/MediaPlayer2"

_cover_cache = {}


class _Bus(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="mpris-bus")
        self.loop = None
        self.bus = None
        self.ready = threading.Event()

    def run(self):
        import asyncio
        from dbus_next.aio import MessageBus

        async def main():
            try:
                self.bus = await MessageBus().connect()
            except Exception:
                logging.exception("D-Bus-Verbindung fehlgeschlagen")
            finally:
                self.ready.set()
            if self.bus is not None:
                await self.bus.wait_for_disconnect()

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(main())
        except Exception:
            logging.exception("MPRIS-Schleife beendet")


_bus_thread = None
_bus_lock = threading.Lock()


def _get_bus():
    global _bus_thread
    with _bus_lock:
        if _bus_thread is None:
            _bus_thread = _Bus()
            _bus_thread.start()
    _bus_thread.ready.wait(3.0)
    return _bus_thread


def _run(coro_factory, timeout=2.0):
    import asyncio
    bt = _get_bus()
    if bt.bus is None or bt.loop is None:
        return None
    try:
        fut = asyncio.run_coroutine_threadsafe(coro_factory(bt.bus), bt.loop)
        return fut.result(timeout)
    except Exception:
        return None


# ----------------------------- D-Bus-Bausteine -------------------------------

async def _call(bus, dest, iface, member, signature="", body=None, path=_PATH):
    from dbus_next import Message, MessageType
    reply = await bus.call(Message(destination=dest, path=path, interface=iface,
                                   member=member, signature=signature, body=body or []))
    if reply.message_type == MessageType.ERROR:
        raise RuntimeError(reply.body[0] if reply.body else "DBus-Fehler")
    return reply.body


async def _get_prop(bus, dest, iface, prop):
    body = await _call(bus, dest, "org.freedesktop.DBus.Properties", "Get",
                       "ss", [iface, prop])
    return body[0].value if body else None


async def _player_names(bus):
    body = await _call(bus, "org.freedesktop.DBus", "org.freedesktop.DBus",
                       "ListNames", path="/org/freedesktop/DBus")
    return [n for n in (body[0] if body else [])
            if n.startswith(_PLAYER_PREFIX) and not n.startswith(_PLAYER_PREFIX + "playerctld")]


async def _status(bus, name):
    try:
        return await _get_prop(bus, name, _PLAYER_IFACE, "PlaybackStatus") or ""
    except Exception:
        return ""


async def _current_player(bus):
    names = await _player_names(bus)
    if not names:
        return None
    fallback = names[0]
    for n in names:
        st = await _status(bus, n)
        if st == "Playing":
            return n
        if st == "Paused":
            fallback = n
    return fallback


def _meta_field(meta, key, default=""):
    v = meta.get(key)
    if v is None:
        return default
    v = getattr(v, "value", v)
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return v


async def _metadata(bus, name):
    try:
        meta = await _get_prop(bus, name, _PLAYER_IFACE, "Metadata") or {}
    except Exception:
        meta = {}
    return meta


def _load_cover(art_url, title, artist):
    """Album-Cover als PIL-Bild (gecacht pro Titel)."""
    key = (title, artist)
    if key in _cover_cache:
        return _cover_cache[key]
    cover = None
    try:
        if art_url.startswith("file://"):
            path = urllib.parse.unquote(urllib.parse.urlparse(art_url).path)
            cover = Image.open(path).convert("RGB")
        elif art_url.startswith(("http://", "https://")):
            with urllib.request.urlopen(art_url, timeout=1.5) as r:
                cover = Image.open(io.BytesIO(r.read())).convert("RGB")
        if cover is not None:
            cover.thumbnail((96, 96), Image.LANCZOS)
    except Exception:
        cover = None
    if len(_cover_cache) > 24:
        _cover_cache.clear()
    _cover_cache[key] = cover
    return cover


# ----------------------------- Oeffentliche API ------------------------------

def get_media_info():
    """{"title","artist","playing","cover"} des aktuellen Players oder None."""

    async def go(bus):
        name = await _current_player(bus)
        if not name:
            return None
        meta = await _metadata(bus, name)
        st = await _status(bus, name)
        title = str(_meta_field(meta, "xesam:title"))
        artist = str(_meta_field(meta, "xesam:artist"))
        art = str(_meta_field(meta, "mpris:artUrl"))
        return {"title": title, "artist": artist, "playing": st == "Playing",
                "art_url": art}

    info = _run(go)
    if info is None:
        return None
    info["cover"] = _load_cover(info.pop("art_url"), info["title"], info["artist"])
    return info


def get_snapshot():
    """Schneller Blick: {"title","pos"} (Sekunden) oder None."""

    async def go(bus):
        name = await _current_player(bus)
        if not name:
            return None
        meta = await _metadata(bus, name)
        try:
            pos = await _get_prop(bus, name, _PLAYER_IFACE, "Position") or 0
        except Exception:
            pos = 0
        return {"title": str(_meta_field(meta, "xesam:title")), "pos": pos / 1_000_000}

    return _run(go)


def _simple(member, times=1):
    async def go(bus):
        name = await _current_player(bus)
        if not name:
            return None
        for _ in range(times):
            await _call(bus, name, _PLAYER_IFACE, member)
        return True
    return _run(go)


def next_track(times=1):
    return _simple("Next", times)


def prev_track(times=1):
    return _simple("Previous", times)


def play_pause():
    return _simple("PlayPause")


def seek_by(secs):
    """Im Titel spulen. Liefert (neue_pos, laenge, anzeigetitel, art_url) oder None."""

    async def go(bus):
        name = await _current_player(bus)
        if not name:
            return None
        meta = await _metadata(bus, name)
        length = _meta_field(meta, "mpris:length", 0) or 0
        try:
            pos = await _get_prop(bus, name, _PLAYER_IFACE, "Position") or 0
        except Exception:
            pos = 0
        end = float(length) / 1_000_000
        new = min(max(pos / 1_000_000 + secs, 0.0), max(end - 1, 0.0))
        track_id = _meta_field(meta, "mpris:trackid", "")
        try:
            if track_id:
                await _call(bus, name, _PLAYER_IFACE, "SetPosition", "ox",
                            [str(track_id), int(new * 1_000_000)])
            else:
                await _call(bus, name, _PLAYER_IFACE, "Seek", "x",
                            [int((new - pos / 1_000_000) * 1_000_000)])
        except Exception:
            return None
        title = str(_meta_field(meta, "xesam:title")) or "Medien"
        artist = str(_meta_field(meta, "xesam:artist"))
        if artist:
            title += " – " + artist
        return new, end, title, str(_meta_field(meta, "mpris:artUrl"))

    res = _run(go)
    if res is None:
        return None
    new, end, title, art = res
    return new, end, title, _load_cover(art, title, "")


def restore_position(title, pos):
    """Nach 'vorheriger Titel': zur gemerkten Sekunde springen, wenn der
    Titel noch stimmt. Liefert (anzeigetitel, cover) oder None."""

    async def go(bus):
        name = await _current_player(bus)
        if not name:
            return None
        meta = await _metadata(bus, name)
        if str(_meta_field(meta, "xesam:title")) != title:
            return None
        track_id = _meta_field(meta, "mpris:trackid", "")
        try:
            if track_id:
                await _call(bus, name, _PLAYER_IFACE, "SetPosition", "ox",
                            [str(track_id), int(pos * 1_000_000)])
            else:
                pos_now = (await _get_prop(bus, name, _PLAYER_IFACE, "Position") or 0) / 1_000_000
                await _call(bus, name, _PLAYER_IFACE, "Seek", "x",
                            [int((pos - pos_now) * 1_000_000)])
        except Exception:
            return None
        disp = str(_meta_field(meta, "xesam:title")) or "Medien"
        artist = str(_meta_field(meta, "xesam:artist"))
        if artist:
            disp += " – " + artist
        return disp, str(_meta_field(meta, "mpris:artUrl"))

    res = _run(go)
    if res is None:
        return None
    disp, art = res
    return disp, _load_cover(art, disp, "")


def players_info():
    """Alle MPRIS-Player: [{"bus","identity","desktop","pid","playing"}].
    Grundlage fuer die Zuordnung Player -> Audio-Stream (Musik-App-Regelung)."""

    async def go(bus):
        out = []
        for name in await _player_names(bus):
            entry = {"bus": name, "identity": "", "desktop": "", "pid": None,
                     "playing": False}
            try:
                entry["identity"] = str(await _get_prop(bus, name, _ROOT_IFACE, "Identity") or "")
            except Exception:
                pass
            try:
                entry["desktop"] = str(await _get_prop(bus, name, _ROOT_IFACE, "DesktopEntry") or "")
            except Exception:
                pass
            try:
                body = await _call(bus, "org.freedesktop.DBus", "org.freedesktop.DBus",
                                   "GetConnectionUnixProcessID", "s", [name],
                                   path="/org/freedesktop/DBus")
                entry["pid"] = int(body[0]) if body else None
            except Exception:
                pass
            entry["playing"] = (await _status(bus, name)) == "Playing"
            out.append(entry)
        return out

    return _run(go, timeout=2.5) or []
