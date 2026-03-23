"""
Unit tests for audio_analyzer.py.

No real audio hardware required — all tests use synthetic waveforms.
"""

import numpy as np
import pytest

from audio_analyzer import analyze_chunk, BeatDetector, AudioLightMapper, _map


# ---------------------------------------------------------------------------
# _map helper
# ---------------------------------------------------------------------------

class TestMap:
    def test_maps_min(self):
        assert _map(0.0, 0.0, 1.0, 0.0, 100.0) == pytest.approx(0.0)

    def test_maps_max(self):
        assert _map(1.0, 0.0, 1.0, 0.0, 100.0) == pytest.approx(100.0)

    def test_maps_midpoint(self):
        assert _map(0.5, 0.0, 1.0, 0.0, 100.0) == pytest.approx(50.0)

    def test_clamps_below(self):
        assert _map(-1.0, 0.0, 1.0, 0.0, 100.0) == pytest.approx(0.0)

    def test_clamps_above(self):
        assert _map(2.0, 0.0, 1.0, 0.0, 100.0) == pytest.approx(100.0)

    def test_handles_zero_range(self):
        assert _map(0.5, 1.0, 1.0, 0.0, 50.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# analyze_chunk
# ---------------------------------------------------------------------------

class TestAnalyzeChunk:
    def _sine_bytes(self, freq_hz: float, duration_samples: int = 1024, amp: float = 0.5) -> bytes:
        t = np.arange(duration_samples) / 44100
        wave = (amp * np.sin(2 * np.pi * freq_hz * t) * 32767).astype(np.int16)
        return wave.tobytes()

    def test_silence_produces_zeros(self):
        silence = (np.zeros(1024, dtype=np.int16)).tobytes()
        result = analyze_chunk(silence)
        assert result["bass"] == pytest.approx(0.0)
        assert result["mid"] == pytest.approx(0.0)
        assert result["treble"] == pytest.approx(0.0)
        assert result["overall"] == pytest.approx(0.0)

    def test_empty_bytes(self):
        result = analyze_chunk(b"")
        assert result == {"bass": 0.0, "mid": 0.0, "treble": 0.0, "overall": 0.0}

    def test_bass_sine_has_high_bass_energy(self):
        raw = self._sine_bytes(100, amp=0.8)   # 100 Hz = bass
        result = analyze_chunk(raw)
        assert result["bass"] > 0.1
        # Treble should be near zero for a clean bass sine
        assert result["treble"] < result["bass"]

    def test_treble_sine_has_high_treble_energy(self):
        raw = self._sine_bytes(4000, amp=0.8)  # 4 kHz = treble
        result = analyze_chunk(raw)
        assert result["treble"] > 0.05
        assert result["bass"] < result["treble"]

    def test_values_in_range(self):
        raw = self._sine_bytes(440, amp=0.5)   # musical A4
        result = analyze_chunk(raw)
        for key in ("bass", "mid", "treble", "overall"):
            assert 0.0 <= result[key] <= 1.0


# ---------------------------------------------------------------------------
# BeatDetector
# ---------------------------------------------------------------------------

class TestBeatDetector:
    def test_no_beat_on_silence(self):
        bd = BeatDetector()
        for _ in range(30):
            assert bd.is_beat(0.0) is False

    def test_detects_sudden_energy_spike(self):
        bd = BeatDetector(history_size=10, threshold_ratio=1.3)
        # Feed low background energy
        for _ in range(15):
            bd.is_beat(0.05)
        # Sudden spike — should trigger a beat
        result = bd.is_beat(0.5)
        assert result is True

    def test_no_beat_for_constant_high_energy(self):
        bd = BeatDetector(history_size=10, threshold_ratio=1.4)
        # Constant high energy does not trigger a beat (no relative rise)
        results = [bd.is_beat(0.8) for _ in range(20)]
        # After history fills, ratio baseline == current, so no beat
        assert not all(results)


# ---------------------------------------------------------------------------
# AudioLightMapper
# ---------------------------------------------------------------------------

class TestAudioLightMapper:
    def _bands(self, bass=0.0, mid=0.0, treble=0.0) -> dict:
        return {"bass": bass, "mid": mid, "treble": treble, "overall": 0.0}

    def test_output_keys(self):
        mapper = AudioLightMapper()
        result = mapper.map(self._bands(bass=0.1, mid=0.2, treble=0.3))
        assert "hue" in result
        assert "saturation" in result
        assert "brightness" in result

    def test_hue_is_int_in_range(self):
        mapper = AudioLightMapper()
        for _ in range(10):
            result = mapper.map(self._bands(bass=0.5, mid=0.3, treble=0.2))
            assert isinstance(result["hue"], int)
            assert 0 <= result["hue"] <= 360

    def test_saturation_is_int_in_range(self):
        mapper = AudioLightMapper()
        result = mapper.map(self._bands(mid=0.5))
        assert 0 <= result["saturation"] <= 100

    def test_brightness_is_int_in_range(self):
        mapper = AudioLightMapper()
        result = mapper.map(self._bands(treble=0.5))
        assert 0 <= result["brightness"] <= 254

    def test_silence_gives_minimum_brightness(self):
        mapper = AudioLightMapper()
        result = mapper.map(self._bands())
        # Minimum brightness floor is 80
        assert result["brightness"] >= 80

    def test_sensitivity_scales_bands(self):
        mapper_low = AudioLightMapper(sensitivity=0.5)
        mapper_high = AudioLightMapper(sensitivity=2.0)
        bands = self._bands(mid=0.4, treble=0.4)
        low = mapper_low.map(bands)
        high = mapper_high.map(bands)
        assert high["saturation"] >= low["saturation"]
        assert high["brightness"] >= low["brightness"]
