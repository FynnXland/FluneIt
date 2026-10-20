"""Fluneit - Audio-Effekte (DSP-Kern).

Reine Signalverarbeitung, ohne Ein-/Ausgabe und ohne Plattformbezug: alles
hier arbeitet auf numpy-Bloecken der Form (frames, channels) in float32.
Damit ist der Kern offline testbar (s. selftest() unten) und laeuft auf
Windows wie Linux identisch.

Aufbau der Kette (fuer Wiedergabe):
    Vorverstaerkung -> Equalizer -> Kompressor -> Limiter
Fuer das Mikrofon zusaetzlich davor:
    Hochpass -> Rauschunterdrueckung -> Noise Gate

Der Limiter laeuft immer als letztes Glied und ist nicht abschaltbar: er ist
die Sicherung dagegen, dass eine unglueckliche Einstellung uebersteuert und
jemandem die Ohren zerreisst.

Alle Filter sind zeitkontinuierlich (IIR) und fuegen keine zusaetzliche
Latenz hinzu - die einzige Ausnahme ist die Rauschunterdrueckung, die mit
einer STFT arbeitet (s. NoiseSuppressor.latency_frames).
"""

import math

import numpy as np
from scipy import signal

# ----------------------------- Filter-Koeffizienten -------------------------
# RBJ-Cookbook-Biquads. Jede Funktion liefert ein Section-Array (1, 6) im
# scipy-"sos"-Format [b0, b1, b2, a0, a1, a2].


def _sos(b0, b1, b2, a0, a1, a2):
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]],
                    dtype=np.float64)


def peaking(fs, f0, gain_db, q):
    """Glockenfilter - das Arbeitstier des Equalizers."""
    if abs(gain_db) < 1e-4:
        return None
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2 * q)
    cw = math.cos(w0)
    return _sos(1 + alpha * A, -2 * cw, 1 - alpha * A,
                1 + alpha / A, -2 * cw, 1 - alpha / A)


def low_shelf(fs, f0, gain_db, q=0.707):
    if abs(gain_db) < 1e-4:
        return None
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / 2 * math.sqrt((A + 1 / A) * (1 / q - 1) + 2)
    tsa = 2 * math.sqrt(A) * alpha
    return _sos(A * ((A + 1) - (A - 1) * cw + tsa),
                2 * A * ((A - 1) - (A + 1) * cw),
                A * ((A + 1) - (A - 1) * cw - tsa),
                (A + 1) + (A - 1) * cw + tsa,
                -2 * ((A - 1) + (A + 1) * cw),
                (A + 1) + (A - 1) * cw - tsa)


def high_shelf(fs, f0, gain_db, q=0.707):
    if abs(gain_db) < 1e-4:
        return None
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / 2 * math.sqrt((A + 1 / A) * (1 / q - 1) + 2)
    tsa = 2 * math.sqrt(A) * alpha
    return _sos(A * ((A + 1) + (A - 1) * cw + tsa),
                -2 * A * ((A - 1) + (A + 1) * cw),
                A * ((A + 1) + (A - 1) * cw - tsa),
                (A + 1) - (A - 1) * cw + tsa,
                2 * ((A - 1) - (A + 1) * cw),
                (A + 1) - (A - 1) * cw - tsa)


def highpass(fs, f0, q=0.707):
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    return _sos((1 + cw) / 2, -(1 + cw), (1 + cw) / 2,
                1 + alpha, -2 * cw, 1 - alpha)


def lowpass(fs, f0, q=0.707):
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    return _sos((1 - cw) / 2, 1 - cw, (1 - cw) / 2,
                1 + alpha, -2 * cw, 1 - alpha)


BAND_TYPES = ("glocke", "tiefen", "hoehen", "hochpass", "tiefpass")


def _band_sos(fs, band):
    """Ein Config-Band -> sos-Section (oder None, wenn wirkungslos)."""
    if not band.get("an", True):
        return None
    typ = str(band.get("typ", "glocke")).lower()
    f0 = float(band.get("hz", 1000))
    # Frequenz im gueltigen Bereich halten, sonst rechnet der Biquad Unsinn
    f0 = min(max(f0, 20.0), fs * 0.45)
    gain = float(band.get("db", 0.0))
    q = max(0.1, min(float(band.get("q", 0.707)), 18.0))
    if typ == "glocke":
        return peaking(fs, f0, gain, q)
    if typ == "tiefen":
        return low_shelf(fs, f0, gain, q)
    if typ == "hoehen":
        return high_shelf(fs, f0, gain, q)
    if typ == "hochpass":
        return highpass(fs, f0, q)
    if typ == "tiefpass":
        return lowpass(fs, f0, q)
    return None


# ----------------------------- Equalizer ------------------------------------

class Equalizer:
    """Kaskade von Biquads. Der Filterzustand bleibt ueber Bloecke hinweg
    erhalten, sonst knackt es an jeder Blockgrenze."""

    def __init__(self, fs, channels):
        self.fs = fs
        self.channels = channels
        self.sos = None
        self.zi = None

    def set_bands(self, bands):
        sections = [s for s in (_band_sos(self.fs, b) for b in bands or [])
                    if s is not None]
        if not sections:
            self.sos, self.zi = None, None
            return
        new = np.concatenate(sections, axis=0)
        old_zi, old_sos = self.zi, self.sos
        self.sos = new
        # Zustand mitnehmen, soweit die Sektionen gleich geblieben sind -
        # dadurch knackt es beim Schieben eines Reglers nicht.
        self.zi = np.zeros((new.shape[0], 2, self.channels))
        if old_zi is not None and old_sos is not None:
            keep = min(old_sos.shape[0], new.shape[0])
            same = min(keep, old_zi.shape[0])
            if same:
                self.zi[:same] = old_zi[:same]

    def process(self, block):
        if self.sos is None:
            return block
        out, self.zi = signal.sosfilt(self.sos, block, axis=0, zi=self.zi)
        return out.astype(np.float32, copy=False)

    def response_db(self, freqs):
        """Frequenzantwort in dB - fuer die Kurve in der UI."""
        if self.sos is None:
            return np.zeros(len(freqs))
        w = 2 * np.pi * np.asarray(freqs, dtype=float) / self.fs
        _, h = signal.sosfreqz(self.sos, worN=w)
        return 20 * np.log10(np.maximum(np.abs(h), 1e-9))


# ----------------------------- Dynamik --------------------------------------

def _coef(ms, fs):
    """Zeitkonstante in Millisekunden -> Glaettungsfaktor pro Sample."""
    ms = max(0.01, float(ms))
    return math.exp(-1.0 / (fs * ms / 1000.0))


class Compressor:
    """Weicher Kompressor mit Peak-Detektor. Arbeitet auf der Blocksumme
    (ein Gain fuer alle Kanaele), damit das Stereobild stehen bleibt."""

    def __init__(self, fs):
        self.fs = fs
        self.env = 0.0
        self.gain_db = 0.0
        self.set(threshold_db=-18.0, ratio=2.5, attack_ms=8.0,
                 release_ms=120.0, makeup_db=0.0, knee_db=6.0)

    def set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, float(v))
        self.ratio = max(1.0, self.ratio)
        self.a_att = _coef(self.attack_ms, self.fs)
        self.a_rel = _coef(self.release_ms, self.fs)

    def _target_db(self, level_db):
        """Statische Kennlinie mit weichem Knie."""
        over = level_db - self.threshold_db
        k = self.knee_db
        if k > 0 and -k / 2 <= over <= k / 2:
            # quadratische Interpolation im Knie
            over = (over + k / 2) ** 2 / (2 * k)
        elif over <= 0:
            return 0.0
        return -over * (1.0 - 1.0 / self.ratio)

    def process(self, block):
        if self.ratio <= 1.0001:
            return block
        # Huellkurve pro Sample, aber vektorisiert ueber den Blockmaximalwert
        # je Sample (Peak ueber Kanaele)
        peak = np.max(np.abs(block), axis=1) if block.ndim > 1 else np.abs(block)
        env = np.empty_like(peak)
        e = self.env
        a_att, a_rel = self.a_att, self.a_rel
        for i in range(peak.shape[0]):
            p = peak[i]
            a = a_att if p > e else a_rel
            e = a * e + (1.0 - a) * p
            env[i] = e
        self.env = float(e)
        level_db = 20.0 * np.log10(np.maximum(env, 1e-7))
        over = level_db - self.threshold_db
        k = self.knee_db
        red = np.zeros_like(over)
        if k > 0:
            in_knee = (over > -k / 2) & (over < k / 2)
            above = over >= k / 2
            ok = (over[in_knee] + k / 2) ** 2 / (2 * k)
            red[in_knee] = -ok * (1.0 - 1.0 / self.ratio)
            red[above] = -over[above] * (1.0 - 1.0 / self.ratio)
        else:
            above = over > 0
            red[above] = -over[above] * (1.0 - 1.0 / self.ratio)
        self.gain_db = float(red[-1]) if red.size else 0.0
        g = (10.0 ** ((red + self.makeup_db) / 20.0)).astype(np.float32)
        return block * g[:, None] if block.ndim > 1 else block * g


class NoiseGate:
    """Blendet Signal unterhalb der Schwelle aus - gegen Tastaturklappern
    und Luefterrauschen in Sprechpausen."""

    def __init__(self, fs):
        self.fs = fs
        self.env = 0.0
        self.gain = 0.0
        self.hold_left = 0
        self.set(threshold_db=-45.0, attack_ms=5.0, release_ms=150.0,
                 hold_ms=120.0, range_db=-60.0)

    def set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, float(v))
        self.a_att = _coef(self.attack_ms, self.fs)
        self.a_rel = _coef(self.release_ms, self.fs)
        self.hold_samples = int(self.fs * self.hold_ms / 1000.0)
        self.floor = 10.0 ** (self.range_db / 20.0)

    def process(self, block):
        peak = np.max(np.abs(block), axis=1) if block.ndim > 1 else np.abs(block)
        thr = 10.0 ** (self.threshold_db / 20.0)
        # Hysterese: schliessen erst 6 dB unter der Oeffnungsschwelle
        thr_close = thr * 0.5
        g = np.empty_like(peak)
        cur, hold = self.gain, self.hold_left
        for i in range(peak.shape[0]):
            p = peak[i]
            if p > thr:
                hold = self.hold_samples
                target = 1.0
            elif hold > 0:
                hold -= 1
                target = 1.0
            else:
                target = 1.0 if p > thr_close and cur > 0.5 else self.floor
            a = self.a_att if target > cur else self.a_rel
            cur = a * cur + (1.0 - a) * target
            g[i] = cur
        self.gain, self.hold_left = float(cur), int(hold)
        gf = g.astype(np.float32)
        return block * gf[:, None] if block.ndim > 1 else block * gf


class Limiter:
    """Brickwall-Limiter mit Vorschau (Lookahead). Letzte Instanz gegen
    Uebersteuerung; laeuft immer."""

    def __init__(self, fs, channels, ceiling_db=-1.0, lookahead_ms=2.0):
        self.fs = fs
        self.channels = channels
        self.ceiling = 10.0 ** (ceiling_db / 20.0)
        self.la = max(1, int(fs * lookahead_ms / 1000.0))
        self.delay = np.zeros((self.la, channels), dtype=np.float32)
        self.gain = 1.0
        self.a_rel = _coef(80.0, fs)
        self.reduction_db = 0.0

    def process(self, block):
        n = block.shape[0]
        # Signal um die Vorschau verzoegern, damit der Gain fruehzeitig faellt
        buf = np.concatenate((self.delay, block), axis=0)
        delayed = buf[:n]
        self.delay = buf[n:n + self.la]
        if self.delay.shape[0] < self.la:      # sehr kleiner Block
            pad = np.zeros((self.la - self.delay.shape[0], self.channels),
                           dtype=np.float32)
            self.delay = np.concatenate((self.delay, pad), axis=0)

        peak = np.max(np.abs(buf[:n + self.la]), axis=1)
        need = np.minimum(1.0, self.ceiling / np.maximum(peak, 1e-9))
        g = np.empty(n, dtype=np.float64)
        cur = self.gain
        for i in range(n):
            t = need[min(i + self.la, need.shape[0] - 1)]
            # sofort runter, langsam wieder hoch
            cur = t if t < cur else self.a_rel * cur + (1.0 - self.a_rel) * t
            g[i] = cur
        self.gain = float(cur)
        self.reduction_db = 20.0 * math.log10(max(self.gain, 1e-6))
        return (delayed * g[:, None].astype(np.float32)).astype(np.float32,
                                                                copy=False)

    @property
    def latency_frames(self):
        return self.la


class NoiseSuppressor:
    """Spektrale Rauschunterdrueckung: schaetzt den Rauschteppich fortlaufend
    aus den leisesten Anteilen jedes Frequenzbandes und daempft alles, was
    nicht deutlich darueber liegt.

    Arbeitet mit STFT und Overlap-Add und kostet dadurch echte Latenz
    (s. latency_frames). Fuer die Wiedergabe daher standardmaessig aus, fuers
    Mikrofon ist es das Kernstueck.
    """

    def __init__(self, fs, channels, n_fft=512, strength=0.8):
        self.fs = fs
        self.channels = channels
        self.n_fft = n_fft
        self.hop = n_fft // 2
        self.win = np.hanning(n_fft + 1)[:-1].astype(np.float32)
        self.strength = float(strength)
        self.noise = None                       # geschaetztes Rauschprofil
        self._in = np.zeros((0, channels), dtype=np.float32)
        self._out = np.zeros((0, channels), dtype=np.float32)
        self._primed = False

    def reset_profile(self):
        self.noise = None
        self._primed = False

    def process(self, block):
        self._in = np.concatenate((self._in, block), axis=0)
        frames_out = []
        while self._in.shape[0] >= self.n_fft:
            seg = self._in[:self.n_fft]
            self._in = self._in[self.hop:]
            spec = np.fft.rfft(seg * self.win[:, None], axis=0)
            mag = np.abs(spec)
            if self.noise is None:
                self.noise = mag.copy()
                self._primed = False
            else:
                # Rauschteppich: schnell nach unten, sehr langsam nach oben.
                # So "lernt" er Pausen, ohne Sprache mitzuzaehlen.
                up, down = 0.995, 0.5
                a = np.where(mag < self.noise, down, up)
                self.noise = a * self.noise + (1 - a) * mag
                self._primed = True
            # Wiener-aehnliche Daempfung
            snr = mag / np.maximum(self.noise * (1.0 + 2.0 * self.strength), 1e-9)
            mask = np.clip((snr - 1.0) / np.maximum(snr, 1e-9), 0.0, 1.0)
            mask = np.maximum(mask, 1.0 - self.strength)   # nie ganz zu
            out = np.fft.irfft(spec * mask, n=self.n_fft, axis=0).astype(np.float32)
            frames_out.append(out * self.win[:, None])

        if frames_out:
            # Overlap-Add
            need = self.hop * len(frames_out)
            tail = np.zeros((self.n_fft, self.channels), dtype=np.float32)
            acc = np.zeros((need + self.n_fft, self.channels), dtype=np.float32)
            acc[:self._out.shape[0]] += self._out
            for i, f in enumerate(frames_out):
                acc[i * self.hop:i * self.hop + self.n_fft] += f
            ready, self._out = acc[:need], acc[need:need + self.n_fft]
            if self._out.shape[0] < self.n_fft:
                self._out = np.concatenate(
                    (self._out, tail[:self.n_fft - self._out.shape[0]]), axis=0)
        else:
            ready = np.zeros((0, self.channels), dtype=np.float32)

        # Der Aufrufer erwartet gleich viele Frames wie hineingegeben - fehlende
        # mit Stille auffuellen (nur am Anfang, danach laeuft es synchron)
        n = block.shape[0]
        if ready.shape[0] < n:
            ready = np.concatenate(
                (np.zeros((n - ready.shape[0], self.channels), dtype=np.float32),
                 ready), axis=0)
        elif ready.shape[0] > n:
            ready = ready[-n:]
        return ready

    @property
    def latency_frames(self):
        return self.n_fft


# ----------------------------- Gesamtkette ----------------------------------

class FxChain:
    """Die komplette Effektkette fuer einen Strom.

    `params` ist genau das, was in config.json unter "effekte" steht - so
    kann die UI Werte direkt durchreichen, ohne Zwischenformat.
    """

    def __init__(self, fs, channels, mic=False):
        self.fs = fs
        self.channels = channels
        self.mic = mic
        self.eq = Equalizer(fs, channels)
        self.comp = Compressor(fs)
        self.gate = NoiseGate(fs)
        self.limiter = Limiter(fs, channels)
        self.ns = NoiseSuppressor(fs, channels)
        self.hp_sos = None
        self.hp_zi = None
        self.params = {}
        self.peak_in = 0.0
        self.peak_out = 0.0
        self.set_params({})

    # -- Einstellungen -----------------------------------------------------
    def set_params(self, p):
        p = dict(p or {})
        self.params = p
        self.pre_gain = 10.0 ** (float(p.get("vorverstaerkung_db", 0.0)) / 20.0)
        self.eq.set_bands(p.get("baender", []))

        self.use_comp = bool(p.get("kompressor", False))
        c = p.get("kompressor_werte", {}) or {}
        self.comp.set(threshold_db=c.get("schwelle_db", -18.0),
                      ratio=c.get("verhaeltnis", 2.5),
                      attack_ms=c.get("attack_ms", 8.0),
                      release_ms=c.get("release_ms", 120.0),
                      makeup_db=c.get("ausgleich_db", 0.0),
                      knee_db=c.get("knie_db", 6.0))

        self.use_gate = bool(p.get("noise_gate", False))
        g = p.get("gate_werte", {}) or {}
        self.gate.set(threshold_db=g.get("schwelle_db", -45.0),
                      attack_ms=g.get("attack_ms", 5.0),
                      release_ms=g.get("release_ms", 150.0),
                      hold_ms=g.get("halten_ms", 120.0),
                      range_db=g.get("bereich_db", -60.0))

        self.use_ns = bool(p.get("rauschunterdrueckung", False))
        self.ns.strength = float(p.get("rausch_staerke", 0.8))

        hp_hz = float(p.get("hochpass_hz", 0.0))
        if hp_hz >= 20.0:
            self.hp_sos = highpass(self.fs, min(hp_hz, self.fs * 0.45))
            if self.hp_zi is None or self.hp_zi.shape[0] != 1:
                self.hp_zi = np.zeros((1, 2, self.channels))
        else:
            self.hp_sos, self.hp_zi = None, None

        ceil = float(p.get("limiter_db", -1.0))
        self.limiter.ceiling = 10.0 ** (ceil / 20.0)

    # -- Verarbeitung ------------------------------------------------------
    def process(self, block):
        """block: (frames, channels) float32 -> gleiche Form."""
        if block.ndim == 1:
            block = block[:, None]
        if block.shape[0] == 0:
            return block
        self.peak_in = float(np.abs(block).max())

        out = block
        if self.pre_gain != 1.0:
            out = out * np.float32(self.pre_gain)

        if self.hp_sos is not None:
            out, self.hp_zi = signal.sosfilt(self.hp_sos, out, axis=0,
                                             zi=self.hp_zi)
            out = out.astype(np.float32, copy=False)

        if self.use_ns:
            out = self.ns.process(out)
        if self.use_gate:
            out = self.gate.process(out)

        out = self.eq.process(out)

        if self.use_comp:
            out = self.comp.process(out)

        out = self.limiter.process(out)
        self.peak_out = float(np.abs(out).max()) if out.size else 0.0
        return out

    @property
    def latency_ms(self):
        frames = self.limiter.latency_frames
        if self.use_ns:
            frames += self.ns.latency_frames
        return 1000.0 * frames / self.fs


# ----------------------------- Voreinstellungen -----------------------------
# Die Gaming-Presets arbeiten mit Frequenzen, nicht mit "Sound-Typen": ein
# Spiel liefert nur einen fertigen Stereomix, einzelne Klaenge lassen sich
# daraus nicht herauslesen. Was hilft, ist das Band anzuheben, in dem
# Schritte und Nachladen liegen (ca. 2-6 kHz), und Explosionsbass zu
# senken, der sie sonst verdeckt. Genau das machen kommerzielle
# "Gaming-Equalizer" auch.

def _b(typ, hz, db, q=0.707, an=True):
    return {"typ": typ, "hz": hz, "db": db, "q": q, "an": an}


PRESETS = {
    # --- Gaming -----------------------------------------------------------
    "schritte": {
        "name": "Gaming – Schritte & Details",
        "gruppe": "Gaming",
        "beschreibung": "Für Shooter: hebt den Bereich, in dem Schritte und Nachladen "
                        "liegen, und nimmt Explosionsbass zurück, der sie verdeckt.",
        "werte": {
            "vorverstaerkung_db": -2.0,
            "baender": [_b("tiefen", 120, -6.0),
                        _b("glocke", 400, -3.0, 1.0),
                        _b("glocke", 2200, 4.5, 1.2),
                        _b("glocke", 4000, 5.5, 1.4),
                        _b("glocke", 6500, 3.0, 1.6),
                        _b("hoehen", 11000, -2.5)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -22.0, "verhaeltnis": 3.0,
                                 "attack_ms": 5.0, "release_ms": 90.0,
                                 "ausgleich_db": 3.0},
        },
    },
    "gaming_ausgewogen": {
        "name": "Gaming – Ausgewogen",
        "gruppe": "Gaming",
        "beschreibung": "Für Rollenspiele und Open World: Wucht bleibt, Stimmen und "
                        "Umgebung kommen klarer. Leichte Kompression gleicht Lautes "
                        "und Leises aus.",
        "werte": {
            "vorverstaerkung_db": -1.5,
            "baender": [_b("tiefen", 90, 2.0),
                        _b("glocke", 350, -2.0, 0.9),
                        _b("glocke", 2800, 2.5, 1.0),
                        _b("hoehen", 9000, 1.5)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -24.0, "verhaeltnis": 2.0,
                                 "attack_ms": 10.0, "release_ms": 150.0,
                                 "ausgleich_db": 2.0},
        },
    },
    "ruhig": {
        "name": "Gaming – Leise Nacht",
        "gruppe": "Gaming",
        "beschreibung": "Starke Kompression: Explosionen werden leiser, Schritte und "
                        "Stimmen bleiben hörbar. Für spät abends, ohne ständig am "
                        "Lautstärkerad zu drehen.",
        "werte": {
            "vorverstaerkung_db": 0.0,
            "baender": [_b("tiefen", 90, -8.0), _b("glocke", 3000, 2.5, 1.2)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -32.0, "verhaeltnis": 6.0,
                                 "attack_ms": 3.0, "release_ms": 200.0,
                                 "ausgleich_db": 6.0},
        },
    },
    # --- Alltag -----------------------------------------------------------
    "musik": {
        "name": "Musik",
        "gruppe": "Alltag",
        "beschreibung": "Sanfte Badewanne: etwas mehr Bass und Glanz, die Mitten "
                        "treten leicht zurück.",
        "werte": {
            "vorverstaerkung_db": -1.5,
            "baender": [_b("tiefen", 100, 3.5), _b("glocke", 900, -1.5, 0.9),
                        _b("hoehen", 9000, 2.5)],
            "kompressor": False,
        },
    },
    "film": {
        "name": "Film & Serie",
        "gruppe": "Alltag",
        "beschreibung": "Dialoge nach vorn, Effektbass leicht gezähmt – man muss "
                        "zwischen Gespräch und Action nicht nachregeln.",
        "werte": {
            "vorverstaerkung_db": -1.0,
            "baender": [_b("tiefen", 110, -2.5), _b("glocke", 1800, 3.0, 1.0),
                        _b("glocke", 3200, 2.0, 1.2)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -26.0, "verhaeltnis": 2.5,
                                 "attack_ms": 10.0, "release_ms": 180.0,
                                 "ausgleich_db": 3.0},
        },
    },
    "sprache": {
        "name": "Sprache & Podcast",
        "gruppe": "Alltag",
        "beschreibung": "Auf Verständlichkeit getrimmt, Rumpeln raus. Gut für "
                        "Podcasts, Videos und Calls.",
        "werte": {
            "vorverstaerkung_db": 0.0,
            "hochpass_hz": 90.0,
            "baender": [_b("glocke", 250, -2.5, 1.0), _b("glocke", 2500, 4.0, 1.1),
                        _b("hoehen", 8000, -3.0)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -24.0, "verhaeltnis": 3.5,
                                 "attack_ms": 6.0, "release_ms": 120.0,
                                 "ausgleich_db": 4.0},
        },
    },
    "bass": {
        "name": "Bass",
        "gruppe": "Alltag",
        "beschreibung": "Deutlich mehr Tiefton – für Kopfhörer, denen Druck fehlt.",
        "werte": {
            "vorverstaerkung_db": -3.0,
            "baender": [_b("tiefen", 90, 7.0), _b("glocke", 60, 3.0, 1.2)],
            "kompressor": False,
        },
    },
    "neutral": {
        "name": "Neutral",
        "gruppe": "Alltag",
        "beschreibung": "Alles flach – Ausgangspunkt für eigene Einstellungen.",
        "werte": {"vorverstaerkung_db": 0.0, "baender": [], "kompressor": False},
    },
}

MIC_PRESETS = {
    "mic_neutral": {
        "name": "Mikrofon – Neutral",
        "beschreibung": "Nur Rumpelfilter und Schutzlimiter.",
        "werte": {"hochpass_hz": 80.0, "baender": []},
    },
    "mic_klar": {
        "name": "Mikrofon – Klar",
        "beschreibung": "Rauschunterdrueckung, Gate und Praesenzanhebung - "
                        "der Alltagsmodus fuer Discord und TeamSpeak.",
        "werte": {
            "hochpass_hz": 95.0,
            "rauschunterdrueckung": True, "rausch_staerke": 0.75,
            "noise_gate": True,
            "gate_werte": {"schwelle_db": -42.0, "halten_ms": 150.0},
            "baender": [_b("glocke", 200, -3.0, 1.0), _b("glocke", 3000, 3.5, 1.1),
                        _b("hoehen", 7500, 2.0)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -20.0, "verhaeltnis": 3.0,
                                 "ausgleich_db": 4.0},
        },
    },
    "mic_radio": {
        "name": "Mikrofon – Radio",
        "beschreibung": "Kraeftig komprimiert und warm, wie im Sendestudio.",
        "werte": {
            "hochpass_hz": 100.0,
            "rauschunterdrueckung": True, "rausch_staerke": 0.85,
            "noise_gate": True,
            "gate_werte": {"schwelle_db": -40.0},
            "baender": [_b("tiefen", 180, 2.5), _b("glocke", 500, -3.5, 1.0),
                        _b("glocke", 2800, 4.0, 1.0), _b("hoehen", 8000, 2.5)],
            "kompressor": True,
            "kompressor_werte": {"schwelle_db": -26.0, "verhaeltnis": 5.0,
                                 "attack_ms": 4.0, "release_ms": 140.0,
                                 "ausgleich_db": 7.0},
        },
    },
}

ALL_PRESETS = dict(PRESETS)
ALL_PRESETS.update(MIC_PRESETS)

# Die Bandmitten des einfachen Equalizers in der UI (Oktavabstand)
UI_BANDS_HZ = (60, 150, 400, 1000, 2500, 6000, 12000)


def preset_params(key, base=None):
    """Voreinstellung -> vollstaendiger Parametersatz."""
    p = dict(base or {})
    entry = ALL_PRESETS.get(key)
    if not entry:
        return p
    # Alle Effektschalter zuruecksetzen, damit ein Preset nichts von der
    # vorherigen Auswahl mitschleppt
    p.update({"vorverstaerkung_db": 0.0, "baender": [], "kompressor": False,
              "rauschunterdrueckung": False, "noise_gate": False,
              "hochpass_hz": 0.0})
    p.update(entry["werte"])
    p["voreinstellung"] = key
    return p


def default_bands():
    """Grafischer Equalizer mit sieben Baendern, alle auf 0 dB."""
    return [_b("glocke", hz, 0.0, 1.1) for hz in UI_BANDS_HZ]


def bands_to_ui(bands, fs=48000, limit=12.0):
    """Beliebige Filterliste auf das feste 7-Band-Raster der UI abbilden.

    Ein Preset benutzt intern Shelves und andere Frequenzen als die sieben
    Regler. Damit die Regler nach der Auswahl trotzdem zeigen, was passiert
    (und man von dort weiterdrehen kann), wird die Frequenzantwort des Presets
    an den sieben Bandmitten abgetastet und als Reglerstellung uebernommen.
    Das ist die uebliche Naeherung eines grafischen Equalizers - nicht
    bitgenau dasselbe, aber sichtbar und weiterbearbeitbar.
    """
    ui = default_bands()
    if not bands:
        return ui
    eq = Equalizer(fs, 1)
    eq.set_bands(bands)
    resp = eq.response_db(list(UI_BANDS_HZ))
    for band, db in zip(ui, resp):
        band["db"] = round(max(-limit, min(limit, float(db))) * 2) / 2
    return ui


# ----------------------------- Selbsttest -----------------------------------

def selftest(verbose=True):
    """Prueft die Kette rechnerisch - laeuft ohne Audiogeraet."""
    fs, ch = 48000, 2
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        if verbose:
            print(f"  {'OK  ' if cond else 'FEHL'} {name} {detail}")

    def tone(hz, n=48000, amp=0.2):
        t = np.arange(n) / fs
        s = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        return np.column_stack([s, s])

    def rms_db(x):
        return 20 * math.log10(max(float(np.sqrt(np.mean(x ** 2))), 1e-12))

    # 1. Equalizer hebt genau das gewaehlte Band an
    chain = FxChain(fs, ch)
    chain.set_params({"baender": [_b("glocke", 1000, 12.0, 1.0)]})
    for hz, expect in ((1000, 12.0), (100, 0.0)):
        x = tone(hz)
        y = chain.process(x.copy())
        # erste Bloecke enthalten den Filtereinschwinger -> zweite Haelfte messen
        d = rms_db(y[fs // 2:]) - rms_db(x[fs // 2:])
        check(f"EQ bei {hz} Hz ~{expect:+.0f} dB", abs(d - expect) < 1.5,
              f"(gemessen {d:+.2f} dB)")

    # 2. Blockweise = in einem Stueck (kein Knacken an Blockgrenzen)
    c1 = FxChain(fs, ch)
    c1.set_params({"baender": [_b("glocke", 800, 9.0, 1.2)]})
    c2 = FxChain(fs, ch)
    c2.set_params({"baender": [_b("glocke", 800, 9.0, 1.2)]})
    x = tone(500, n=9600)
    whole = c1.process(x.copy())
    parts = np.concatenate([c2.process(x[i:i + 480].copy())
                            for i in range(0, x.shape[0], 480)], axis=0)
    check("blockweise == komplett", np.allclose(whole, parts, atol=2e-5),
          f"(max Abw. {float(np.abs(whole - parts).max()):.2e})")

    # 3. Limiter haelt die Decke
    chain = FxChain(fs, ch)
    chain.set_params({"vorverstaerkung_db": 24.0, "limiter_db": -1.0})
    y = chain.process(tone(440, amp=0.5))
    peak_db = 20 * math.log10(max(float(np.abs(y).max()), 1e-9))
    check("Limiter <= -1 dBFS", peak_db <= -0.5, f"(Peak {peak_db:+.2f} dBFS)")

    # 4. Kompressor reduziert Dynamik
    chain = FxChain(fs, ch)
    chain.set_params({"kompressor": True,
                      "kompressor_werte": {"schwelle_db": -30.0, "verhaeltnis": 8.0,
                                           "attack_ms": 1.0}})
    q = chain.process(tone(440, amp=0.02))
    chain2 = FxChain(fs, ch)
    chain2.set_params(chain.params)
    l = chain2.process(tone(440, amp=0.6))
    span_in = rms_db(tone(440, amp=0.6)) - rms_db(tone(440, amp=0.02))
    span_out = rms_db(l[fs // 2:]) - rms_db(q[fs // 2:])
    check("Kompressor verkleinert Dynamik", span_out < span_in - 6,
          f"(rein {span_in:.1f} dB -> raus {span_out:.1f} dB)")

    # 5. Noise Gate schliesst bei Stille
    chain = FxChain(fs, ch)
    chain.set_params({"noise_gate": True,
                      "gate_werte": {"schwelle_db": -40.0, "halten_ms": 10.0,
                                     "release_ms": 20.0}})
    chain.process(tone(440, amp=0.3))                 # Gate oeffnen
    quiet = chain.process(tone(440, n=24000, amp=0.0005))
    check("Gate daempft Stille", rms_db(quiet[-8000:]) < -70,
          f"({rms_db(quiet[-8000:]):.1f} dBFS)")

    # 6. Rauschunterdrueckung senkt weisses Rauschen, laesst Ton stehen
    rng = np.random.default_rng(7)
    chain = FxChain(fs, ch)
    chain.set_params({"rauschunterdrueckung": True, "rausch_staerke": 0.9})
    noise = (rng.standard_normal((fs * 2, ch)) * 0.05).astype(np.float32)
    out_n = chain.process(noise)
    red = rms_db(out_n[fs:]) - rms_db(noise[fs:])
    check("Rauschen gedaempft", red < -4.0, f"({red:+.1f} dB)")

    # 7. Presets liefern gueltige Parameter und laufen durch
    for key in ALL_PRESETS:
        c = FxChain(fs, ch)
        c.set_params(preset_params(key, {"baender": default_bands()}))
        y = c.process(tone(1000, n=4800))
        good = np.all(np.isfinite(y)) and float(np.abs(y).max()) <= 1.0
        check(f"Preset '{key}'", good)

    # 8. Kein NaN bei Extremwerten
    chain = FxChain(fs, ch)
    chain.set_params({"vorverstaerkung_db": 40.0, "kompressor": True,
                      "noise_gate": True, "rauschunterdrueckung": True,
                      "baender": [_b("glocke", 30, 20.0, 18.0),
                                  _b("glocke", 23000, -20.0, 0.1)]})
    y = chain.process((rng.standard_normal((9600, ch)) * 0.9).astype(np.float32))
    check("keine NaN/Inf bei Extremen", np.all(np.isfinite(y)))
    check(f"Latenz gemeldet ({chain.latency_ms:.1f} ms)", chain.latency_ms > 0)

    if verbose:
        print("\n" + ("ALLE TESTS BESTANDEN" if ok else "FEHLER IN DER KETTE"))
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
