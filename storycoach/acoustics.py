import math
from pathlib import Path

import numpy as np
import parselmouth

from storycoach.models import Acoustics

MIN_VOICED_FRAMES = 20


def extract_acoustics(wav: Path, step: float = 0.01) -> Acoustics:
    """Pitch (Hz, None when unvoiced) and intensity (dB) on a shared time grid."""
    snd = parselmouth.Sound(str(wav))
    pitch = snd.to_pitch(time_step=step, pitch_floor=75, pitch_ceiling=500)
    intensity = snd.to_intensity(time_step=step)
    times = [round(float(t), 3) for t in pitch.xs()]
    f0 = []
    for t in pitch.xs():
        v = pitch.get_value_at_time(t)
        f0.append(None if v is None or math.isnan(v) or v <= 0 else round(float(v), 2))
    db = []
    for t in pitch.xs():
        v = intensity.get_value(t)
        db.append(0.0 if v is None or math.isnan(v) else round(float(v), 2))
    return Acoustics(times=times, f0_hz=f0, intensity_db=db)


def window(ac: Acoustics, start: float, end: float) -> Acoustics:
    idx = [i for i, t in enumerate(ac.times) if start <= t <= end]
    return Acoustics(
        times=[ac.times[i] for i in idx],
        f0_hz=[ac.f0_hz[i] for i in idx],
        intensity_db=[ac.intensity_db[i] for i in idx],
    )


def voiced_median_hz(ac: Acoustics) -> float | None:
    voiced = [f for f in ac.f0_hz if f]
    return float(np.median(voiced)) if len(voiced) >= MIN_VOICED_FRAMES else None


def loudness_stats(ac: Acoustics) -> dict | None:
    """Intensity (dB) over voiced frames only, so pauses don't widen the spread.

    mean_db depends on microphone gain and distance: compare it only within one take.
    sd_db and range_db_p10_p90 are spreads, so they can be compared between takes.
    """
    db = np.array([d for d, f in zip(ac.intensity_db, ac.f0_hz) if f], dtype=float)
    if len(db) < MIN_VOICED_FRAMES:
        return None
    return {
        "mean_db": round(float(np.mean(db)), 2),
        "sd_db": round(float(np.std(db)), 2),
        "range_db_p10_p90": round(float(np.percentile(db, 90) - np.percentile(db, 10)), 2),
    }


def semitone_stats(ac: Acoustics, ref_hz: float | None) -> dict | None:
    """Pitch in semitones relative to ref_hz; None when too few voiced frames."""
    voiced = np.array([f for f in ac.f0_hz if f], dtype=float)
    if ref_hz is None or len(voiced) < MIN_VOICED_FRAMES:
        return None
    st = 12 * np.log2(voiced / ref_hz)
    return {
        "median_st": round(float(np.median(st)), 2),
        "range_st_p10_p90": round(float(np.percentile(st, 90) - np.percentile(st, 10)), 2),
        "sd_st": round(float(np.std(st)), 2),
    }
