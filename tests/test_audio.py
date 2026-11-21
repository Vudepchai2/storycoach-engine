import wave
from pathlib import Path

import av
import numpy as np
import pytest

from storycoach.audio import to_wav


def _tone(rate, secs=1.0, freq=440):
    t = np.arange(int(secs * rate)) / rate
    return 0.5 * np.sin(2 * np.pi * freq * t)


def _check(out: Path):
    with wave.open(str(out), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert abs(w.getnframes() / w.getframerate() - 1.0) <= 0.05


def test_wav_48k_stereo_converts_to_16k_mono(encode_audio, tmp_path):
    src = encode_audio(tmp_path / "in.wav", _tone(48000), "pcm_s16le", rate=48000, channels=2)
    _check(to_wav(src, tmp_path / "out.wav"))


def test_m4a_aac_converts(encode_audio, tmp_path):
    src = encode_audio(tmp_path / "in.m4a", _tone(44100), "aac", rate=44100)
    _check(to_wav(src, tmp_path / "out.wav"))


def test_flac_converts(encode_audio, tmp_path):
    src = encode_audio(tmp_path / "in.flac", _tone(44100), "flac", rate=44100)
    _check(to_wav(src, tmp_path / "out.wav"))


def test_mp3_converts(encode_audio, tmp_path):
    try:
        av.codec.Codec("libmp3lame", "w")
    except Exception:
        pytest.skip("PyAV has no mp3 encoder")
    src = encode_audio(tmp_path / "in.mp3", _tone(44100), "libmp3lame", rate=44100)
    _check(to_wav(src, tmp_path / "out.wav"))


def test_audio_stream_not_first(tmp_path):
    """A container whose first stream is video must still decode its audio."""
    src = tmp_path / "av.mkv"
    with av.open(str(src), "w") as out:
        vs = out.add_stream("mpeg4", rate=10)
        vs.width, vs.height, vs.pix_fmt = 64, 64, "yuv420p"
        a = out.add_stream("flac", rate=16000, layout="mono")
        data = (_tone(16000) * 32767).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(data, format="s16", layout="mono")
        frame.sample_rate = 16000
        frame.pts = 0
        vframe = av.VideoFrame(64, 64, "yuv420p")
        vframe.pts = 0
        for pkt in vs.encode(vframe):
            out.mux(pkt)
        for pkt in vs.encode(None):
            out.mux(pkt)
        out.mux(a.encode(frame))
        out.mux(a.encode(None))
    assert src.exists()
    _check(to_wav(src, tmp_path / "out.wav"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        to_wav(tmp_path / "nope.m4a", tmp_path / "o.wav")


def test_garbage_file_raises_runtime_error(tmp_path):
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"this is not audio" * 100)
    with pytest.raises(RuntimeError, match="Couldn't read bad.m4a as audio"):
        to_wav(bad, tmp_path / "o.wav")


def test_no_ffmpeg_lookup():
    import storycoach.audio as audio

    assert "ffmpeg" not in Path(audio.__file__).read_text(encoding="utf-8")
