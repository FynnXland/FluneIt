"""Linux-Audio-Backend: PulseAudio/PipeWire ueber pulsectl.

Bildet die pycaw-Schnittstellen nach, die fluneit.py und ui.py benutzen
(Duck-Typing), damit die gemeinsame Logik unveraendert laeuft:

- Session          ~ pycaw AudioSession:  .Process, .SimpleAudioVolume
- SimpleAudioVolume: GetMasterVolume() / SetMasterVolume(v, None)
                     GetMute() / SetMute(m, None)
- Endpoint         ~ IAudioEndpointVolume: GetMasterVolumeLevelScalar() /
                     SetMasterVolumeLevelScalar(v, None) / GetMute() / SetMute(m, None)

Eine einzige Pulse-Verbindung, geschuetzt durch ein Lock (alle Aufrufer laufen
im Tk-Thread; das Lock sichert die wenigen Worker-Thread-Zugriffe ab). Bricht
die Verbindung ab (Daemon-Neustart), wird einmal neu verbunden.
"""

import logging
import threading

import psutil
import pulsectl

_lock = threading.RLock()
_pulse = None


def _pulse_conn():
    global _pulse
    if _pulse is None:
        _pulse = pulsectl.Pulse("fluneit", threading_lock=False)
    return _pulse


def _reset():
    global _pulse
    try:
        if _pulse is not None:
            _pulse.close()
    except Exception:
        pass
    _pulse = None


def _call(fn):
    """Pulse-Aufruf mit einmaligem Reconnect bei Verbindungsverlust."""
    with _lock:
        for attempt in (1, 2):
            try:
                return fn(_pulse_conn())
            except pulsectl.PulseError:
                _reset()
                if attempt == 2:
                    raise


# ----------------------------- App-Sessions (Sink-Inputs) --------------------

class _SinkInputVolume:
    """SimpleAudioVolume-Ersatz fuer einen Pulse-Sink-Input (per Index).
    Jeder Aufruf holt den frischen Zustand; ist der Stream weg, fliegt eine
    Exception - fluneit faengt das ab und laedt die Sessions neu (wie bei
    ungueltig gewordenen WASAPI-Sessions)."""

    def __init__(self, index):
        self.index = index

    def _info(self, p):
        return p.sink_input_info(self.index)

    def GetMasterVolume(self):
        return min(1.0, max(0.0, _call(lambda p: self._info(p).volume.value_flat)))

    def SetMasterVolume(self, value, _ctx=None):
        value = min(1.0, max(0.0, float(value)))

        def go(p):
            info = self._info(p)
            info.volume.value_flat = value
            p.sink_input_volume_set(self.index, info.volume)
        _call(go)

    def GetMute(self):
        return bool(_call(lambda p: self._info(p).mute))

    def SetMute(self, mute, _ctx=None):
        _call(lambda p: p.sink_input_mute(self.index, bool(mute)))


class Session:
    """Nachbau einer pycaw-AudioSession fuer einen Pulse-Sink-Input."""

    def __init__(self, sink_input):
        self.sink_input = sink_input
        self.SimpleAudioVolume = _SinkInputVolume(sink_input.index)
        self.pid = None
        self.binary = (sink_input.proplist.get("application.process.binary") or "").strip()
        self.app_name = (sink_input.proplist.get("application.name") or "").strip()
        try:
            self.pid = int(sink_input.proplist.get("application.process.id", "") or 0) or None
        except (TypeError, ValueError):
            self.pid = None
        self.Process = None
        if self.pid:
            try:
                self.Process = psutil.Process(self.pid)
            except psutil.Error:
                self.Process = None
        if self.Process is None and self.binary:
            # Kein PID-Property (z. B. Sandbox): Fake-Prozessobjekt mit Namen
            self.Process = _NamedProcess(self.binary)


class _NamedProcess:
    """Minimaler psutil.Process-Ersatz, wenn Pulse nur den Binaernamen kennt."""

    def __init__(self, name):
        self._name = name
        self.pid = 0

    def name(self):
        return self._name

    def exe(self):
        return ""

    def children(self, recursive=False):
        return []


def get_all_sessions():
    """Alle App-Audio-Streams (Sink-Inputs), analog AudioUtilities.GetAllSessions()."""
    try:
        infos = _call(lambda p: p.sink_input_list())
    except Exception:
        logging.exception("Pulse: Sink-Inputs nicht lesbar")
        return []
    out = []
    for si in infos:
        # Eigene/interne Streams (z. B. Pegelanzeigen) ueberspringen
        if (si.proplist.get("application.name") or "") == "fluneit":
            continue
        try:
            out.append(Session(si))
        except Exception:
            continue
    return out


# ----------------------------- Endpunkte (Sink / Source) --------------------

class _Endpoint:
    """IAudioEndpointVolume-Ersatz fuer das Standard-Wiedergabe- oder
    -Aufnahmegeraet. Loest das Geraet bei jedem Aufruf neu auf, damit ein
    Wechsel des Standardgeraets automatisch greift."""

    def __init__(self, kind):
        self.kind = kind  # "sink" oder "source"

    def _dev(self, p):
        info = p.server_info()
        if self.kind == "sink":
            return p.get_sink_by_name(info.default_sink_name)
        return p.get_source_by_name(info.default_source_name)

    def GetMasterVolumeLevelScalar(self):
        return min(1.0, max(0.0, _call(lambda p: self._dev(p).volume.value_flat)))

    def SetMasterVolumeLevelScalar(self, value, _ctx=None):
        value = min(1.0, max(0.0, float(value)))

        def go(p):
            dev = self._dev(p)
            dev.volume.value_flat = value
            p.volume_set(dev, dev.volume)
        _call(go)

    def GetMute(self):
        return bool(_call(lambda p: self._dev(p).mute))

    def SetMute(self, mute, _ctx=None):
        _call(lambda p: p.mute(self._dev(p), bool(mute)))


def default_endpoint(dataflow, _role=0):
    """dataflow wie bei WASAPI: 0 = Wiedergabe (Sink), 1 = Aufnahme (Source)."""
    return _Endpoint("source" if dataflow == 1 else "sink")


# ----------------------------- Ausgabegeraete --------------------------------

def list_output_devices():
    """[(geraete_id, name)], aktuelle Standard-ID. IDs sind Pulse-Sink-Namen."""

    def go(p):
        current = p.server_info().default_sink_name
        devs = [(s.name, s.description or s.name) for s in p.sink_list()]
        return devs, current
    return _call(go)


def set_default_output_device(dev_id):
    def go(p):
        sink = p.get_sink_by_name(dev_id)
        p.sink_default_set(sink)
        # Laufende Streams mit umziehen (PulseAudio macht das nicht immer selbst)
        for si in p.sink_input_list():
            try:
                p.sink_input_move(si.index, sink.index)
            except pulsectl.PulseError:
                pass
    _call(go)
