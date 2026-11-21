import wave
from pathlib import Path

import av

RATE = 16000


def to_wav(src: Path, dst: Path) -> Path:
    """Convert any audio file PyAV can open to 16 kHz mono 16-bit PCM wav."""
    src, dst = Path(src), Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"Audio file not found: {src}")
    chunks: list[bytes] = []
    try:
        with av.open(str(src)) as container:
            if not container.streams.audio:
                raise RuntimeError(f"Couldn't read {src.name} as audio: no audio stream")
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=RATE)
            for frame in container.decode(stream):
                for out in resampler.resample(frame):
                    chunks.append(bytes(out.planes[0])[: out.samples * 2])
            for out in resampler.resample(None):
                chunks.append(bytes(out.planes[0])[: out.samples * 2])
    except (av.FFmpegError, OSError) as err:
        raise RuntimeError(f"Couldn't read {src.name} as audio: {err}") from err
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(chunks))
    return dst
