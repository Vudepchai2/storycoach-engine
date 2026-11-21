import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

RATE = 16000


def _write_wav(path: Path, samples: np.ndarray, rate: int = RATE) -> Path:
    data = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


@pytest.fixture
def tone_wav(tmp_path):
    def make(freq=200, secs=2.0, lead_silence=0.0, tail_silence=0.0):
        t = np.arange(int(secs * RATE)) / RATE
        tone = 0.5 * np.sin(2 * np.pi * freq * t)
        sig = np.concatenate([np.zeros(int(lead_silence * RATE)), tone, np.zeros(int(tail_silence * RATE))])
        return _write_wav(tmp_path / f"tone_{freq}_{secs}_{lead_silence}_{tail_silence}.wav", sig)
    return make


@pytest.fixture
def silence_wav(tmp_path):
    def make(secs):
        return _write_wav(tmp_path / f"silence_{secs}.wav", np.zeros(int(secs * RATE)))
    return make


@pytest.fixture
def tts_wav(tmp_path):
    def make(text):
        out = tmp_path / f"tts_{abs(hash(text))}.wav"
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SetOutputToWaveFile('{out}'); $s.Speak(\"{text}\"); $s.Dispose()"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            pytest.skip("Windows System.Speech not available")
        return out
    return make


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """No test may reach the real data home: subprocesses and in-process calls both see this one."""
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path_factory.mktemp("home_default")))


@pytest.fixture
def encode_audio():
    """Encode float samples in [-1, 1] to any container/codec PyAV can write."""
    import av

    def make(path, samples, codec, rate=RATE, channels=1, extra_streams=False):
        path = Path(path)
        data = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
        layout = "stereo" if channels == 2 else "mono"
        if channels == 2:
            data = np.repeat(data[:, None], 2, axis=1).reshape(1, -1)
        else:
            data = data.reshape(1, -1)
        with av.open(str(path), "w") as out:
            stream = out.add_stream(codec, rate=rate, layout=layout)
            enc_fmt = stream.codec_context.codec.audio_formats[0].name
            resampler = av.AudioResampler(format=enc_fmt, layout=layout, rate=rate)
            frame = av.AudioFrame.from_ndarray(data, format="s16", layout=layout)
            frame.sample_rate = rate
            for f in [*resampler.resample(frame), *resampler.resample(None)]:
                out.mux(stream.encode(f))
            out.mux(stream.encode(None))
        return path
    return make
