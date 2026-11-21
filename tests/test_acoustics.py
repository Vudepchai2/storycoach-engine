import statistics

import pytest

from storycoach.acoustics import extract_acoustics, semitone_stats, window


def test_tone_pitch_is_200(tone_wav):
    ac = extract_acoustics(tone_wav())
    voiced = [f for f in ac.f0_hz if f]
    assert abs(statistics.median(voiced) - 200) < 3


def test_unvoiced_audio_gives_null_pitch(silence_wav):
    assert semitone_stats(extract_acoustics(silence_wav(2.0)), ref_hz=150) is None


def test_leading_trailing_silence_ignored(tone_wav):
    ac = extract_acoustics(tone_wav(lead_silence=3.0, tail_silence=3.0))
    w = window(ac, 3.0, 5.0)
    assert min(w.times) >= 3.0 and max(w.times) <= 5.0
    assert semitone_stats(w, 200)["median_st"] == pytest.approx(0, abs=0.3)


def _flat(db_values, f0=200.0):
    from storycoach.models import Acoustics
    n = len(db_values)
    return Acoustics(times=[i * 0.01 for i in range(n)], f0_hz=[f0] * n, intensity_db=list(db_values))


def test_loudness_stats_uses_voiced_frames_only():
    from storycoach.acoustics import loudness_stats
    ac = _flat([60.0, 70.0] * 50 + [30.0] * 50)
    for i in range(100, 150):
        ac.f0_hz[i] = None  # quiet unvoiced gap must not widen the spread
    s = loudness_stats(ac)
    assert s["mean_db"] == pytest.approx(65.0)
    assert s["sd_db"] == pytest.approx(5.0)
    assert s["range_db_p10_p90"] == pytest.approx(10.0)


def test_loudness_stats_none_when_too_few_voiced():
    from storycoach.acoustics import loudness_stats
    assert loudness_stats(_flat([60.0] * 10)) is None
