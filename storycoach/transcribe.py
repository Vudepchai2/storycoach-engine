import os
import tempfile
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

from storycoach.audio import to_wav
from storycoach.models import Transcript, Word

FILLER_PROMPT = "Um, uh, so, like, I mean, hmm, you know, er, okay."


class NoSpeechError(Exception):
    pass


def quiet_hub() -> None:
    """Never send a stored Hugging Face token, and turn off the hub's telemetry."""
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def resolve_model(model_size: str) -> str:
    """The local model folder. The cache is tried first, with no network; only a miss goes online."""
    quiet_hub()
    from faster_whisper.utils import download_model

    try:
        return download_model(model_size, local_files_only=True, use_auth_token=False)
    except Exception:  # noqa: BLE001  not cached yet: fetch it once
        return download_model(model_size, use_auth_token=False)


@lru_cache(maxsize=2)
def _model(model_size: str):
    quiet_hub()
    from faster_whisper import WhisperModel

    return WhisperModel(resolve_model(model_size), device="cpu", compute_type="int8")


def _read_wav(path: Path) -> np.ndarray:
    """Read a wav into 16 kHz mono float32, converting with PyAV if needed."""
    with wave.open(str(path), "rb") as w:
        ok = w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        if ok:
            data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if not ok:
        with tempfile.TemporaryDirectory() as tmp:
            return _read_wav(to_wav(path, Path(tmp) / "conv.wav"))
    return data.astype(np.float32) / 32768.0


def transcribe(wav: Path, model_size: str = "small.en") -> Transcript:
    """Transcribe English speech locally with word timestamps, keeping filler words."""
    segments, _info = _model(model_size).transcribe(
        _read_wav(Path(wav)),
        language="en",
        word_timestamps=True,
        vad_filter=False,
        initial_prompt=FILLER_PROMPT,
    )
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append(Word(text=text, start=round(w.start, 3), end=round(w.end, 3)))
    if not words:
        raise NoSpeechError("No speech found in recording.")
    words.sort(key=lambda w: w.start)
    return Transcript(words=words, text=" ".join(w.text for w in words))
