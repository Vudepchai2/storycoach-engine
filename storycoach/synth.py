"""Made-up voice measurements for practice takes: no recording, no real voice."""
import numpy as np

from storycoach.models import Acoustics, Transcript

STEP_S = 0.01
TAIL_S = 0.5
PAUSE_DROP_DB = 25.0


def synthesize_acoustics(transcript: Transcript, delivery: dict) -> Acoustics:
    """Pitch and loudness for each 0.01 s frame, steered by a delivery description. Same input, same output."""
    rng = np.random.default_rng(delivery["seed"])
    words = transcript.words
    end = words[-1].end if words else 0.0
    n = int(round((end + TAIL_S) / STEP_S)) + 1
    times = np.round(np.arange(n) * STEP_S, 2)

    db_offset = np.zeros(n)
    pitch_scale = np.ones(n)
    in_word = np.zeros(n, dtype=bool)
    seg_for = {}
    for seg in delivery.get("segments", []):
        for i in range(seg["start_word"], seg["end_word"] + 1):
            seg_for[i] = seg
    for i, w in enumerate(words):
        mask = (times >= w.start) & (times < w.end)
        in_word |= mask
        seg = seg_for.get(i)
        if seg:
            db_offset[mask] = seg["db"]
            pitch_scale[mask] = seg["pitch_sd_scale"]

    semitones = rng.normal(0.0, 1.0, n) * 1.5 * pitch_scale
    smooth = np.convolve(semitones, np.ones(5) / 5, mode="same")
    noise_db = rng.normal(0.0, 1.0, n)
    base_db = float(delivery["base_db"])
    f0 = delivery["base_hz"] * 2.0 ** (smooth / 12.0)
    db = np.where(in_word, base_db + db_offset + noise_db, base_db - PAUSE_DROP_DB)
    return Acoustics(times=[float(t) for t in times],
                     f0_hz=[float(f) if w else None for f, w in zip(f0, in_word)],
                     intensity_db=[float(x) for x in db])
