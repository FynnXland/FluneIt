"""The effect chain, checked by calculation (no audio device needed)."""
import math

import numpy as np
import pytest

from fluneit import fx_dsp

FS, CH = 48000, 2


def tone(hz, n=FS, amp=0.2):
    t = np.arange(n) / FS
    s = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.column_stack([s, s])


def rms_db(x):
    return 20 * math.log10(max(float(np.sqrt(np.mean(x ** 2))), 1e-12))


def chain(params):
    c = fx_dsp.FxChain(FS, CH)
    c.set_params(params)
    return c


@pytest.mark.parametrize("hz, expected_db", [(1000, 12.0), (100, 0.0)])
def test_peaking_band_boosts_only_its_frequency(hz, expected_db):
    c = chain({"baender": [fx_dsp._b("glocke", 1000, 12.0, 1.0)]})
    x = tone(hz)
    y = c.process(x.copy())
    # the first half contains the filter settling
    gain = rms_db(y[FS // 2:]) - rms_db(x[FS // 2:])
    assert abs(gain - expected_db) < 1.5


def test_processing_in_blocks_equals_processing_at_once():
    params = {"baender": [fx_dsp._b("glocke", 800, 9.0, 1.2)]}
    x = tone(500, n=9600)
    whole = chain(params).process(x.copy())
    c = chain(params)
    parts = np.concatenate([c.process(x[i:i + 480].copy())
                            for i in range(0, len(x), 480)])
    assert np.allclose(whole, parts, atol=2e-5)


def test_limiter_holds_the_ceiling_even_with_extreme_gain():
    y = chain({"vorverstaerkung_db": 24.0, "limiter_db": -1.0}).process(tone(440, amp=0.5))
    assert 20 * math.log10(float(np.abs(y).max())) <= -0.5


def test_compressor_reduces_dynamic_range():
    params = {"kompressor": True,
              "kompressor_werte": {"schwelle_db": -30.0, "verhaeltnis": 8.0, "attack_ms": 1.0}}
    quiet = chain(params).process(tone(440, amp=0.02))
    loud = chain(params).process(tone(440, amp=0.6))
    span_in = rms_db(tone(440, amp=0.6)) - rms_db(tone(440, amp=0.02))
    span_out = rms_db(loud[FS // 2:]) - rms_db(quiet[FS // 2:])
    assert span_out < span_in - 6


def test_noise_gate_closes_on_near_silence():
    c = chain({"noise_gate": True,
               "gate_werte": {"schwelle_db": -40.0, "halten_ms": 10.0, "release_ms": 20.0}})
    c.process(tone(440, amp=0.3))
    quiet = c.process(tone(440, n=24000, amp=0.0005))
    assert rms_db(quiet[-8000:]) < -70


def test_noise_suppression_lowers_white_noise():
    noise = (np.random.default_rng(7).standard_normal((FS * 2, CH)) * 0.05).astype(np.float32)
    out = chain({"rauschunterdrueckung": True, "rausch_staerke": 0.9}).process(noise)
    assert rms_db(out[FS:]) - rms_db(noise[FS:]) < -4.0


@pytest.mark.parametrize("key", sorted(fx_dsp.ALL_PRESETS))
def test_every_preset_runs_and_stays_in_range(key):
    c = chain(fx_dsp.preset_params(key, {"baender": fx_dsp.default_bands()}))
    y = c.process(tone(1000, n=4800))
    assert np.all(np.isfinite(y))
    assert float(np.abs(y).max()) <= 1.0


@pytest.mark.parametrize("key", sorted(fx_dsp.PRESETS))
def test_presets_have_a_name_group_and_description(key):
    p = fx_dsp.PRESETS[key]
    assert p["name"] and p["beschreibung"] and p["gruppe"] in ("Gaming", "Alltag")


def test_gaming_presets_come_first():
    groups = [p["gruppe"] for p in fx_dsp.PRESETS.values()]
    assert groups == sorted(groups, key=lambda g: g != "Gaming")


def test_extreme_settings_produce_no_nan():
    c = chain({"vorverstaerkung_db": 40.0, "kompressor": True, "noise_gate": True,
               "rauschunterdrueckung": True,
               "baender": [fx_dsp._b("glocke", 30, 20.0, 18.0),
                           fx_dsp._b("glocke", 23000, -20.0, 0.1)]})
    noise = (np.random.default_rng(1).standard_normal((9600, CH)) * 0.9).astype(np.float32)
    assert np.all(np.isfinite(c.process(noise)))
    assert c.latency_ms > 0


def test_preset_curve_maps_onto_the_seven_sliders():
    bands = fx_dsp.bands_to_ui(fx_dsp.preset_params("schritte")["baender"])
    assert [b["hz"] for b in bands] == list(fx_dsp.UI_BANDS_HZ)
    by_hz = {b["hz"]: b["db"] for b in bands}
    # footsteps: presence up, rumble down
    assert by_hz[2500] > 3 and by_hz[6000] > 3
    assert by_hz[60] < -3
    assert all(-12 <= b["db"] <= 12 for b in bands)
