#!/usr/bin/env python3
"""
Audio Analyzer — Real-time beat detection and frequency-to-light mapping.

Captures microphone / system audio, runs FFT analysis, and drives
Zigbee lights reactively:
  - Bass energy  → Hue (color shifts with kick/bass)
  - Mid energy   → Saturation (richness pulses with melody)
  - Treble energy→ Brightness (sparkles with hi-hats/cymbals)

Usage:
    python audio_analyzer.py                    # list devices + interactive
    python audio_analyzer.py --device 0         # use device index 0
    python audio_analyzer.py --test             # show FFT levels, no lights
    python audio_analyzer.py --sensitivity 1.5  # boost sensitivity

Standalone (no gamepad required). Integrates with gamepad_light_controller.py
via AudioReactiveMode when imported as a module.
"""

import argparse
import sys
import time
import threading
import math

try:
    import numpy as np
except ImportError:
    print("numpy not installed. Run: pip install numpy", file=sys.stderr)
    sys.exit(1)

try:
    import pyaudio
except ImportError:
    print("pyaudio not installed. Run: pip install pyaudio", file=sys.stderr)
    sys.exit(1)

from zigbee_light_controller import ZigbeeLightController

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE = 44100
CHUNK_SIZE = 1024           # frames per read (~23ms at 44.1kHz)
CHANNELS = 1
FORMAT = pyaudio.paInt16
HOP_MS = 50                 # minimum ms between light updates

# Frequency band boundaries (Hz)
BASS_LOW, BASS_HIGH = 60, 250
MID_LOW, MID_HIGH = 250, 2000
TREBLE_LOW, TREBLE_HIGH = 2000, 8000


# ---------------------------------------------------------------------------
# Helper: map a value from one range to another (clamped)
# ---------------------------------------------------------------------------

def _map(value: float, in_lo: float, in_hi: float, out_lo: float, out_hi: float) -> float:
    if in_hi == in_lo:
        return out_lo
    ratio = (value - in_lo) / (in_hi - in_lo)
    return out_lo + max(0.0, min(1.0, ratio)) * (out_hi - out_lo)


# ---------------------------------------------------------------------------
# FFT analysis
# ---------------------------------------------------------------------------

def _band_energy(magnitudes: np.ndarray, freqs: np.ndarray, low: float, high: float) -> float:
    """RMS energy of FFT magnitudes within a frequency band."""
    mask = (freqs >= low) & (freqs < high)
    if not mask.any():
        return 0.0
    band = magnitudes[mask]
    return float(np.sqrt(np.mean(band ** 2)))


def analyze_chunk(raw_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> dict:
    """
    Analyze one audio chunk and return normalized band energies.

    Returns:
        {
            "bass":    0.0–1.0,  # kick / bass guitar energy
            "mid":     0.0–1.0,  # vocals / melody energy
            "treble":  0.0–1.0,  # hi-hats / cymbals energy
            "overall": 0.0–1.0,  # full-spectrum RMS
        }
    """
    samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return {"bass": 0.0, "mid": 0.0, "treble": 0.0, "overall": 0.0}

    # Apply Hann window to reduce spectral leakage
    window = np.hanning(len(samples))
    windowed = samples * window

    fft_mag = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)

    bass = _band_energy(fft_mag, freqs, BASS_LOW, BASS_HIGH)
    mid = _band_energy(fft_mag, freqs, MID_LOW, MID_HIGH)
    treble = _band_energy(fft_mag, freqs, TREBLE_LOW, TREBLE_HIGH)
    overall = float(np.sqrt(np.mean(samples ** 2)))

    # Rough normalization (speech/music peak ≈ 0.1–0.3 RMS)
    scale = 5.0
    return {
        "bass": min(1.0, bass * scale),
        "mid": min(1.0, mid * scale),
        "treble": min(1.0, treble * scale),
        "overall": min(1.0, overall * scale),
    }


# ---------------------------------------------------------------------------
# Beat detector (simple onset strength threshold)
# ---------------------------------------------------------------------------

class BeatDetector:
    """Detect beats by tracking energy rise above a rolling mean."""

    def __init__(self, history_size: int = 20, threshold_ratio: float = 1.4):
        self._history: list[float] = []
        self._size = history_size
        self._ratio = threshold_ratio

    def is_beat(self, energy: float) -> bool:
        self._history.append(energy)
        if len(self._history) > self._size:
            self._history.pop(0)
        if len(self._history) < 4:
            return False
        mean = sum(self._history) / len(self._history)
        return energy > mean * self._ratio and energy > 0.05


# ---------------------------------------------------------------------------
# Audio → Light mapping
# ---------------------------------------------------------------------------

class AudioLightMapper:
    """
    Translates real-time audio analysis into HSV light commands.

    Mapping strategy:
      - Bass beat  → hue shift (+30° per beat, cycles through spectrum)
      - Mid energy → saturation (0.3–1.0)
      - Treble     → brightness (100–254)
    """

    def __init__(self, sensitivity: float = 1.0):
        self.sensitivity = sensitivity
        self._hue: float = 0.0
        self._beat_detector = BeatDetector()

    def map(self, bands: dict) -> dict:
        """
        Convert band energies to HSV light parameters.

        Returns:
            {"hue": int, "saturation": int, "brightness": int}
        """
        bass = min(1.0, bands["bass"] * self.sensitivity)
        mid = min(1.0, bands["mid"] * self.sensitivity)
        treble = min(1.0, bands["treble"] * self.sensitivity)

        if self._beat_detector.is_beat(bass):
            self._hue = (self._hue + 30.0) % 360.0

        saturation = int(_map(mid, 0.0, 0.8, 30, 100))
        brightness = int(_map(treble, 0.0, 0.7, 100, 254))

        # Ensure minimum brightness so lights stay on
        brightness = max(brightness, 80)

        return {
            "hue": int(self._hue),
            "saturation": saturation,
            "brightness": brightness,
        }


# ---------------------------------------------------------------------------
# Main audio capture loop
# ---------------------------------------------------------------------------

class AudioReactiveController:
    """
    Captures audio from a microphone and drives Zigbee lights in real time.
    Can be run standalone or embedded inside GamepadLightController.
    """

    def __init__(
        self,
        lights: list[str],
        controller: ZigbeeLightController,
        device_index: int | None = None,
        sensitivity: float = 1.0,
    ):
        self.lights = lights
        self.controller = controller
        self.device_index = device_index
        self.mapper = AudioLightMapper(sensitivity=sensitivity)
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_update = 0.0

    def start(self):
        """Start audio capture in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("Audio reactive mode started.")

    def stop(self):
        """Stop audio capture."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("Audio reactive mode stopped.")

    def _loop(self):
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while self._running:
                raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                bands = analyze_chunk(raw)

                now = time.time() * 1000
                if now - self._last_update < HOP_MS:
                    continue
                self._last_update = now

                hsv = self.mapper.map(bands)
                for light in self.lights:
                    self.controller.set_color_hue(
                        light,
                        hsv["hue"],
                        hsv["saturation"],
                        hsv["brightness"],
                        transition=0.05,
                    )
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()


# ---------------------------------------------------------------------------
# Device listing utility
# ---------------------------------------------------------------------------

def list_audio_devices():
    pa = pyaudio.PyAudio()
    print("\nAvailable audio input devices:")
    print("-" * 50)
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            print(f"  [{i}] {info['name']}")
    pa.terminate()
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Audio-reactive Zigbee light controller")
    parser.add_argument("--device", type=int, default=None, help="Audio input device index")
    parser.add_argument("--sensitivity", type=float, default=1.0, help="Sensitivity multiplier (default 1.0)")
    parser.add_argument("--test", action="store_true", help="Show FFT levels only, no lights")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        return

    if args.test:
        print("Audio test mode — press Ctrl+C to stop\n")
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
            input=True, input_device_index=args.device, frames_per_buffer=CHUNK_SIZE,
        )
        try:
            while True:
                raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                b = analyze_chunk(raw)
                bar = lambda v: "#" * int(v * 30)
                print(
                    f"\rBass [{bar(b['bass']):<30}] "
                    f"Mid [{bar(b['mid']):<30}] "
                    f"Treble [{bar(b['treble']):<30}]",
                    end="", flush=True,
                )
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            stream.stop_stream(); stream.close(); pa.terminate()
        return

    # Full mode: connect to lights and start audio reactive control
    list_audio_devices()
    ctrl = ZigbeeLightController()
    if not ctrl.connect():
        print("Cannot connect to MQTT broker.", file=sys.stderr)
        sys.exit(1)

    lights = ctrl.discover_lights()
    if not lights:
        print("No color lights discovered.", file=sys.stderr)
        sys.exit(1)

    arc = AudioReactiveController(
        lights=lights,
        controller=ctrl,
        device_index=args.device,
        sensitivity=args.sensitivity,
    )
    arc.start()
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        arc.stop()
        ctrl.disconnect()


if __name__ == "__main__":
    main()
