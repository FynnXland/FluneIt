"""FluneIt - Effekt-Engine (Ein-/Ausgabe).

Holt Audio herein, schickt es durch fx_dsp.FxChain und gibt es wieder aus.
Alles im Benutzermodus, ohne Treiber und ohne Eingriff in die Registry.

Windows: Aufnahme ueber WASAPI-Loopback (IAudioClient mit
AUDCLNT_STREAMFLAGS_LOOPBACK) auf einem frei waehlbaren Ausgabegeraet,
Wiedergabe ueber sounddevice.
Linux: Aufnahme von der Monitor-Quelle des Geraets (PulseAudio/PipeWire
stellen die als normale Eingabe bereit), Wiedergabe ebenfalls sounddevice.

Das Prinzip der "Bruecke":
    Programme spielen auf Gerauet A (das niemand hoert)
      -> FluneIt nimmt A per Loopback auf
      -> Effektkette
      -> FluneIt gibt auf Geraet B aus (die echten Kopfhoerer)

Damit liegen Effekte auf allem, was das System abspielt, ohne dass ein
virtuelles Audiogeraet installiert werden muss.

Sicherheitsnetz: faellt die Engine aus, wird das Standardgeraet
zurueckgestellt (siehe on_stop) - sonst saesse der Nutzer ohne Ton da.
"""

import ctypes
import logging
import math
import queue
import sys
import threading
import time
from ctypes import POINTER, byref, c_byte, c_uint32, c_uint64

import numpy as np

from fluneit import fx_dsp

IS_WINDOWS = sys.platform == "win32"

# Blockgroessen je Latenzstufe (Frames bei 48 kHz)
LATENCY_MODES = {
    "niedrig": {"block": 240, "puffer": 2, "name": "Niedrig (schnell)"},
    "mittel": {"block": 480, "puffer": 3, "name": "Mittel (empfohlen)"},
    "sicher": {"block": 960, "puffer": 4, "name": "Sicher (keine Aussetzer)"},
}
DEFAULT_LATENCY = "mittel"


# ----------------------------- WASAPI-Loopback ------------------------------

if IS_WINDOWS:
    import comtypes
    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, CoCreateInstance
    from pycaw.api.audioclient import IAudioClient
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator

    AUDCLNT_SHAREMODE_SHARED = 0
    AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
    AUDCLNT_BUFFERFLAGS_SILENT = 0x1
    # IIDs aus Audioclient.h des Windows SDK (nicht aus dem Gedaechtnis -
    # eine falsche IID liefert nur ein wenig hilfreiches E_NOINTERFACE)
    IID_AUDIO_CAPTURE_CLIENT = "{C8ADBD64-E71E-48A0-A4DE-185C395CD317}"
    # WAVE_FORMAT_IEEE_FLOAT bzw. Subformat-GUID in WAVEFORMATEXTENSIBLE
    WAVE_FORMAT_PCM = 1
    WAVE_FORMAT_IEEE_FLOAT = 3
    WAVE_FORMAT_EXTENSIBLE = 0xFFFE
    KSDATAFORMAT_SUBTYPE_IEEE_FLOAT = GUID(
        "{00000003-0000-0010-8000-00AA00389B71}")

    class IAudioCaptureClient(comtypes.IUnknown):
        _iid_ = GUID(IID_AUDIO_CAPTURE_CLIENT)
        _methods_ = [
            COMMETHOD([], HRESULT, "GetBuffer",
                      (["out"], POINTER(POINTER(c_byte)), "ppData"),
                      (["out"], POINTER(c_uint32), "pNumFramesToRead"),
                      (["out"], POINTER(c_uint32), "pdwFlags"),
                      (["out"], POINTER(c_uint64), "pu64DevicePosition"),
                      (["out"], POINTER(c_uint64), "pu64QPCPosition")),
            COMMETHOD([], HRESULT, "ReleaseBuffer",
                      (["in"], c_uint32, "NumFramesRead")),
            COMMETHOD([], HRESULT, "GetNextPacketSize",
                      (["out"], POINTER(c_uint32), "pNumFramesInNextPacket")),
        ]


class LoopbackCapture:
    """WASAPI-Loopback auf einem Ausgabegeraet (nur Windows).

    Liefert float32-Bloecke der Form (frames, channels) ueber read().
    """

    def __init__(self, device_id=None, buffer_ms=200):
        if not IS_WINDOWS:
            raise RuntimeError("LoopbackCapture ist Windows-spezifisch")
        self._enum = CoCreateInstance(CLSID_MMDeviceEnumerator,
                                      IMMDeviceEnumerator, CLSCTX_ALL)
        if device_id:
            dev = self._enum.GetDevice(device_id)
        else:
            dev = self._enum.GetDefaultAudioEndpoint(0, 0)   # eRender, eConsole
        self.device_id = device_id or ""
        self.device_name = ""
        try:
            from pycaw.pycaw import AudioUtilities
            self.device_name = AudioUtilities.CreateDevice(dev).FriendlyName or ""
        except Exception:
            logging.debug("Geraetename der Bruecke nicht lesbar")
        self._client = dev.Activate(IAudioClient._iid_, CLSCTX_ALL,
                                    None).QueryInterface(IAudioClient)
        wfx = self._client.GetMixFormat()
        w = wfx.contents
        self.samplerate = int(w.nSamplesPerSec)
        self.channels = int(w.nChannels)
        self.block_align = int(w.nBlockAlign)
        self.bits = int(w.wBitsPerSample)
        self._dtype, self._scale = self._resolve_format(w)
        self._client.Initialize(AUDCLNT_SHAREMODE_SHARED,
                                AUDCLNT_STREAMFLAGS_LOOPBACK,
                                int(buffer_ms * 10_000), 0, wfx, None)
        self.buffer_frames = int(self._client.GetBufferSize())
        self._capture = self._client.GetService(
            GUID(IID_AUDIO_CAPTURE_CLIENT)).QueryInterface(IAudioCaptureClient)
        self._running = False

    @staticmethod
    def _resolve_format(w):
        """Mixformat -> (numpy-dtype, Skalierung auf +-1.0)."""
        tag = int(w.wFormatTag)
        bits = int(w.wBitsPerSample)
        if tag == WAVE_FORMAT_IEEE_FLOAT or (tag == WAVE_FORMAT_EXTENSIBLE
                                             and bits == 32):
            # Bei EXTENSIBLE muesste man das Subformat lesen; 32 bit im
            # Mixformat der Windows-Engine ist praktisch immer float.
            return np.float32, 1.0
        if bits == 16:
            return np.int16, 1.0 / 32768.0
        if bits == 32:
            return np.int32, 1.0 / 2147483648.0
        raise RuntimeError(f"unbekanntes Aufnahmeformat: {bits} bit, tag {tag}")

    def start(self):
        self._client.Start()
        self._running = True

    def stop(self):
        if self._running:
            try:
                self._client.Stop()
            except Exception:
                pass
            self._running = False

    def read(self):
        """Alle bereitliegenden Frames abholen. Gibt (frames, channels) oder
        ein leeres Array zurueck, wenn gerade nichts anliegt."""
        chunks = []
        while True:
            try:
                if not self._capture.GetNextPacketSize():
                    break
                pdata, nframes, flags, _pos, _qpc = self._capture.GetBuffer()
            except Exception:
                logging.exception("Loopback-Aufnahme abgebrochen")
                raise
            n = int(nframes)
            if n:
                if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                    chunks.append(np.zeros((n, self.channels), dtype=np.float32))
                else:
                    raw = ctypes.string_at(pdata, n * self.block_align)
                    a = np.frombuffer(raw, dtype=self._dtype)
                    a = a.reshape(-1, self.channels)
                    if self._scale != 1.0:
                        a = a.astype(np.float32) * np.float32(self._scale)
                    chunks.append(np.ascontiguousarray(a, dtype=np.float32))
            self._capture.ReleaseBuffer(n)
        if not chunks:
            return np.zeros((0, self.channels), dtype=np.float32)
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)

    def close(self):
        self.stop()
        self._capture = None
        self._client = None


class MonitorCapture:
    """Linux-Gegenstueck: nimmt von einer Monitor-Quelle auf (PulseAudio /
    PipeWire stellen fuer jede Senke eine bereit)."""

    def __init__(self, device=None, samplerate=48000, channels=2, block=480):
        import sounddevice as sd
        self._sd = sd
        if device is None:
            device = self.find_monitor()
        info = sd.query_devices(device, "input")
        self.samplerate = int(info["default_samplerate"] or samplerate)
        self.channels = min(2, int(info["max_input_channels"]) or channels)
        self._q = queue.Queue(maxsize=64)
        self._stream = sd.InputStream(
            device=device, samplerate=self.samplerate, channels=self.channels,
            dtype="float32", blocksize=block, callback=self._cb)

    def _cb(self, indata, frames, time_info, status):
        try:
            self._q.put_nowait(indata.copy())
        except queue.Full:
            pass

    @staticmethod
    def find_monitor(name_hint=None):
        """Passende Monitor-Quelle suchen."""
        import sounddevice as sd
        best = None
        for i, d in enumerate(sd.query_devices()):
            if not d["max_input_channels"]:
                continue
            n = d["name"].lower()
            if "monitor" not in n:
                continue
            if name_hint and name_hint.lower() in n:
                return i
            if best is None:
                best = i
        if best is None:
            raise RuntimeError("keine Monitor-Quelle gefunden (PulseAudio/"
                               "PipeWire laeuft nicht?)")
        return best

    def start(self):
        self._stream.start()

    def stop(self):
        try:
            self._stream.stop()
        except Exception:
            pass

    def read(self):
        chunks = []
        while True:
            try:
                chunks.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros((0, self.channels), dtype=np.float32)
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)

    def close(self):
        self.stop()
        try:
            self._stream.close()
        except Exception:
            pass


# ----------------------------- Geraeteliste ---------------------------------

def sd_output_index(name):
    """Ausgabegeraet-Name -> sounddevice-Index (WASAPI bevorzugt)."""
    import sounddevice as sd
    if not name:
        return None
    want = name.lower()
    apis = {i: a["name"] for i, a in enumerate(sd.query_hostapis())}
    best, best_score = None, -1
    for i, d in enumerate(sd.query_devices()):
        if not d["max_output_channels"]:
            continue
        dn = d["name"].lower()
        api = apis.get(d["hostapi"], "")
        # PortAudio kuerzt Namen bei manchen Host-APIs -> beidseitig pruefen
        if want in dn or dn in want or dn[:28] == want[:28]:
            score = 2 if "WASAPI" in api else (1 if "DirectSound" in api else 0)
            if score > best_score:
                best, best_score = i, score
    return best


def bridge_candidates(exclude_name=None):
    """Ausgabegeraete, die als Bruecke taugen. Bevorzugt werden Ausgaenge,
    an denen typischerweise nichts haengt (SPDIF/Digital), denn dort stoert
    es nicht, dass das Signal dort real ausgegeben wird."""
    import sounddevice as sd
    apis = {i: a["name"] for i, a in enumerate(sd.query_hostapis())}
    out = []
    seen = set()
    for i, d in enumerate(sd.query_devices()):
        if not d["max_output_channels"]:
            continue
        if "WASAPI" not in apis.get(d["hostapi"], "") and IS_WINDOWS:
            continue
        name = d["name"]
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        if exclude_name and (exclude_name.lower() in key or key in exclude_name.lower()):
            continue
        n = key
        if any(h in n for h in ("digital", "spdif", "s/pdif")):
            rank = 0                      # meist ungenutzt -> ideal
        elif "hdmi" in n or "nvidia" in n or "amd high definition" in n:
            rank = 1                      # Monitor-Ausgang, oft stumm
        else:
            rank = 2
        out.append({"index": i, "name": name, "rang": rank,
                    "kanaele": d["max_output_channels"]})
    out.sort(key=lambda x: (x["rang"], x["name"]))
    return out


# ----------------------------- Engine ---------------------------------------

class FxEngine:
    """Laeuft in einem eigenen Thread: aufnehmen -> verarbeiten -> ausgeben."""

    def __init__(self, on_stop=None, on_error=None):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._params = {}
        self._pending = None
        self.on_stop = on_stop          # wird immer aufgerufen, auch bei Fehler
        self.on_error = on_error
        # Statuswerte fuer die UI
        self.running = False
        self.latency_ms = 0.0
        self.dropouts = 0
        self.cpu_ms = 0.0
        self.load_percent = 0.0
        self.peak_in = 0.0
        self.peak_out = 0.0
        self.gain_reduction_db = 0.0
        self.samplerate = 0
        self.channels = 0
        self.error = None
        self.source_name = ""
        self.sink_name = ""

    # -- Steuerung ---------------------------------------------------------
    def set_params(self, params):
        """Effektwerte zur Laufzeit aendern (die Kette wird ohne Knacken
        umgestellt, s. Equalizer.set_bands)."""
        with self._lock:
            self._pending = dict(params or {})
            self._params = dict(params or {})

    def start(self, source, sink, params, latency="mittel", mic=False):
        """source: Geraetekennung der Quelle (Windows: Endpoint-ID der
        Bruecke bzw. None fuer das Standardgeraet; Linux: Monitor-Index).
        sink:   Name des Ausgabegeraets."""
        if self.running:
            self.stop()
        self._stop.clear()
        self.error = None
        self.dropouts = 0
        self._params = dict(params or {})
        self._pending = dict(params or {})
        self._thread = threading.Thread(
            target=self._run, args=(source, sink, latency, mic),
            name="FluneitFx", daemon=True)
        self._thread.start()
        # kurz warten, damit start() einen echten Fehler gleich melden kann
        for _ in range(60):
            if self.running or self.error:
                break
            time.sleep(0.02)
        return self.running

    def stop(self, timeout=2.0):
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout)
        self.running = False

    # -- Arbeitsschleife ---------------------------------------------------
    def _run(self, source, sink, latency, mic):
        import sounddevice as sd
        mode = LATENCY_MODES.get(latency, LATENCY_MODES[DEFAULT_LATENCY])
        cap = stream = None
        com_ready = False
        if IS_WINDOWS:
            # COM gilt pro Thread. MTA (nicht STA), weil dieser Thread keine
            # Nachrichtenschleife hat und WASAPI daraus bedient wird.
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
                com_ready = True
            except OSError:
                # Thread haengt schon in einem anderen Apartment - dann
                # weiterarbeiten und hoffen, dass es passt
                logging.debug("CoInitializeEx im Effekt-Thread fehlgeschlagen")
        try:
            if IS_WINDOWS:
                if mic:
                    cap = _MicCapture(source, block=mode["block"])
                else:
                    cap = LoopbackCapture(source, buffer_ms=200)
            else:
                cap = (_MicCapture(source, block=mode["block"]) if mic
                       else MonitorCapture(source, block=mode["block"]))
            self.samplerate = cap.samplerate
            self.channels = cap.channels
            self.source_name = getattr(cap, "device_name", "") or (
                str(source) if source else "Standardgeraet")
            self.sink_name = sink or "Standardgeraet"

            # Rueckkopplungssperre: nehmen wir das Geraet auf, auf das wir
            # gleich ausgeben, schaukelt sich das Signal endlos auf. Das ist
            # kein theoretischer Fall - es passiert, sobald jemand als
            # Bruecke sein normales Ausgabegeraet auswaehlt.
            if not mic and sink and self.source_name:
                a, b = self.source_name.lower(), sink.lower()
                if a in b or b in a:
                    raise RuntimeError(
                        "Quelle und Ziel sind dasselbe Geraet "
                        f"(\"{sink}\") - das wuerde ruckkoppeln")

            chain = fx_dsp.FxChain(cap.samplerate, cap.channels, mic=mic)
            with self._lock:
                chain.set_params(self._params)
                self._pending = None

            dev = sd_output_index(sink) if sink else None
            if sink and dev is None:
                # Nicht stillschweigend auf das Standardgeraet ausweichen:
                # das ist im Brueckenbetrieb genau die Quelle, wir wuerden
                # eine Rueckkopplung erzeugen.
                raise RuntimeError(f"Ausgabegeraet \"{sink}\" nicht gefunden")
            extra = None
            if IS_WINDOWS and dev is not None:
                api = sd.query_hostapis(sd.query_devices(dev)["hostapi"])["name"]
                if "WASAPI" in api:
                    # auto_convert laesst WASAPI die Abtastrate anpassen, falls
                    # Quelle und Ziel unterschiedlich laufen
                    extra = sd.WasapiSettings(auto_convert=True)
            block = int(mode["block"] * cap.samplerate / 48000) or mode["block"]
            stream = sd.OutputStream(
                device=dev, samplerate=cap.samplerate, channels=cap.channels,
                dtype="float32", blocksize=block,
                latency=mode["puffer"] * block / cap.samplerate,
                extra_settings=extra)
            stream.start()

            self.latency_ms = (chain.latency_ms
                               + 1000.0 * block * mode["puffer"] / cap.samplerate
                               + 1000.0 * block / cap.samplerate)
            self.running = True
            logging.info("Effekt-Engine laeuft: %s -> %s, %d Hz, %d ch, "
                         "Block %d, ~%.0f ms", self.source_name, self.sink_name,
                         cap.samplerate, cap.channels, block, self.latency_ms)

            cap.start()
            pending = np.zeros((0, cap.channels), dtype=np.float32)
            budget = block / cap.samplerate
            idle = 0.0

            while not self._stop.is_set():
                with self._lock:
                    if self._pending is not None:
                        chain.set_params(self._pending)
                        self._pending = None

                new = cap.read()
                if new.shape[0]:
                    pending = (new if pending.shape[0] == 0
                               else np.concatenate((pending, new), axis=0))
                    idle = 0.0
                else:
                    # Nichts spielt: kurz schlafen, damit wir keine CPU verbrennen
                    idle += 0.002
                    time.sleep(0.002 if idle < 0.2 else 0.01)

                # zu viel aufgelaufen (Engine kam nicht mit) -> aeltestes wegwerfen,
                # sonst waechst die Latenz unbegrenzt
                max_pending = block * (mode["puffer"] + 4)
                if pending.shape[0] > max_pending:
                    self.dropouts += 1
                    pending = pending[-max_pending:]

                # Taktausgleich: Bruecke und Kopfhoerer haengen an
                # verschiedenen Quarzen und laufen um einige ppm auseinander.
                # Unkorrigiert liefe der Puffer nach Minuten ueber oder leer -
                # beides ein hoerbarer Aussetzer. Darum hier laufend um
                # EINZELNE Samples nachregeln: bei 48 kHz ist ein Sample
                # 0,02 ms und damit unhoerbar, waehrend ein Aussetzer 10 ms
                # oder mehr reisst. Der Totbereich sorgt dafuer, dass nur bei
                # echter Drift eingegriffen wird.
                # Kein Nachregeln um einzelne Samples: stream.write() blockiert,
                # bis die Ausgabe Platz hat, und gibt damit bereits den Takt vor
                # - "pending" ist deshalb fast immer leer und taugt NICHT als
                # Driftanzeige. Ein Versuch damit griff gemessen 100-mal pro
                # Sekunde ein (statt der paar Mal pro Minute, die echte
                # Quarzdrift braucht); jede dieser Korrekturen ist ein
                # Sprung im Signal, zusammen ein hoerbares Brummen.
                # Laeuft die Quelle dauerhaft schneller, faengt das die
                # Ueberlaufgrenze oben ab; das zeigt der Aussetzer-Zaehler an.
                while pending.shape[0] >= block and not self._stop.is_set():
                    piece, pending = pending[:block], pending[block:]
                    t0 = time.perf_counter()
                    out = chain.process(piece)
                    dt = (time.perf_counter() - t0) * 1000.0
                    self.cpu_ms = dt
                    self.load_percent = dt / (budget * 1000.0) * 100.0
                    self.peak_in = chain.peak_in
                    self.peak_out = chain.peak_out
                    self.gain_reduction_db = min(chain.comp.gain_db,
                                                 chain.limiter.reduction_db)
                    try:
                        stream.write(np.ascontiguousarray(out))
                    except Exception:
                        logging.exception("Ausgabe fehlgeschlagen")
                        raise
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
            logging.exception("Effekt-Engine abgebrochen")
            if self.on_error:
                try:
                    self.on_error(self.error)
                except Exception:
                    logging.exception("on_error fehlgeschlagen")
        finally:
            self.running = False
            for obj, meth in ((cap, "close"), (stream, "stop"), (stream, "close")):
                if obj is not None:
                    try:
                        getattr(obj, meth)()
                    except Exception:
                        pass
            # Immer aufrufen: hier stellt der Aufrufer das Standardgeraet
            # zurueck. Ohne das saesse der Nutzer nach einem Absturz ohne Ton.
            if self.on_stop:
                try:
                    self.on_stop()
                except Exception:
                    logging.exception("on_stop fehlgeschlagen")
            if com_ready:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass


class _MicCapture:
    """Aufnahme von einem Eingabegeraet (Mikrofon) - auf beiden Plattformen
    ueber sounddevice."""

    def __init__(self, device=None, block=480):
        import sounddevice as sd
        self._sd = sd
        idx = device
        if isinstance(device, str) and device:
            idx = None
            want = device.lower()
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] and (want in d["name"].lower()
                                                or d["name"].lower() in want):
                    idx = i
                    break
        info = sd.query_devices(idx, "input")
        self.samplerate = int(info["default_samplerate"] or 48000)
        self.channels = min(2, int(info["max_input_channels"]) or 1)
        self._q = queue.Queue(maxsize=64)
        self._stream = sd.InputStream(
            device=idx, samplerate=self.samplerate, channels=self.channels,
            dtype="float32", blocksize=block, callback=self._cb)

    def _cb(self, indata, frames, time_info, status):
        try:
            self._q.put_nowait(indata.copy())
        except queue.Full:
            pass

    def start(self):
        self._stream.start()

    def stop(self):
        try:
            self._stream.stop()
        except Exception:
            pass

    def read(self):
        chunks = []
        while True:
            try:
                chunks.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros((0, self.channels), dtype=np.float32)
        return chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)

    def close(self):
        self.stop()
        try:
            self._stream.close()
        except Exception:
            pass


# ----------------------------- Selbsttest -----------------------------------

def selftest(seconds=2.0, verbose=True):
    """Nimmt kurz auf, verarbeitet und misst - ohne etwas umzustellen.
    Gibt True zurueck, wenn die Kette Frames geliefert hat."""
    ok = True

    def say(*a):
        if verbose:
            print(*a)

    say("--- Geraete ---")
    try:
        cands = bridge_candidates()
        for c in cands[:6]:
            say(f"  Rang {c['rang']}  [{c['index']:3}] {c['name']}")
    except Exception as e:
        say("  Geraeteliste fehlgeschlagen:", e)
        ok = False

    if not IS_WINDOWS:
        say("(Loopback-Test nur unter Windows implementiert)")
        return ok

    say("\n--- Loopback-Aufnahme auf dem Standardgeraet ---")
    try:
        cap = LoopbackCapture(None, buffer_ms=200)
        say(f"  {cap.samplerate} Hz, {cap.channels} ch, {cap.bits} bit, "
            f"Puffer {cap.buffer_frames} Frames")
        chain = fx_dsp.FxChain(cap.samplerate, cap.channels)
        chain.set_params(fx_dsp.preset_params("schritte"))
        cap.start()
        frames, peak, worst = 0, 0.0, 0.0
        t0 = time.monotonic()
        while time.monotonic() - t0 < seconds:
            blk = cap.read()
            if blk.shape[0]:
                t1 = time.perf_counter()
                out = chain.process(blk)
                dt = (time.perf_counter() - t1) * 1000.0
                budget = blk.shape[0] / cap.samplerate * 1000.0
                worst = max(worst, dt / max(budget, 0.01) * 100.0)
                frames += blk.shape[0]
                peak = max(peak, float(np.abs(out).max()) if out.size else 0.0)
            else:
                time.sleep(0.002)
        cap.close()
        say(f"  {frames} Frames verarbeitet ({frames/cap.samplerate:.2f} s Audio)")
        say(f"  Peak nach Effekten: {peak:.4f}, schlechteste Last: {worst:.1f} %")
        if not frames:
            say("  KEINE Frames - spielt gerade etwas Audio?")
            ok = False
    except Exception as e:
        say("  FEHLER:", type(e).__name__, e)
        ok = False

    say("\n" + ("ENGINE BEREIT" if ok else "ENGINE HAT PROBLEME"))
    return ok


