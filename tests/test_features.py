import json
import re

import pytest

from storycoach.beats import Beat, Beats, KeyLine
from storycoach.features import compute_features, observations
from storycoach.models import Acoustics, Transcript, Word

BANNED = ["nervous", "anxious", "confident", "unconfident", "excited", "bored", "sad", "happy", "angry", "emotional"]


def _transcript(words):
    return Transcript(words=words, text=" ".join(w.text for w in words))


def _acoustics(end, f0=180.0):
    n = int(end * 100) + 1
    times = [round(i * 0.01, 2) for i in range(n)]
    f0s = [None if f0 is None else f0 * (1 + 0.05 * ((i // 50) % 3)) for i in range(n)]
    db = [70.0 - 0.5 * t for t in times]
    return Acoustics(times=times, f0_hz=f0s, intensity_db=db)


def _two_speed_take():
    a = [Word("go", 0.5 * i, 0.5 * i + 0.4) for i in range(10)]
    b = [Word("go", 5.0 + 0.25 * j, 5.0 + 0.25 * j + 0.2) for j in range(10)]
    beats = Beats([Beat("hook", 0, 9), Beat("turn", 10, 19)])
    return _transcript(a + b), beats


def test_rates_relative_to_overall():
    t, beats = _two_speed_take()
    f = compute_features(t, _acoustics(8), beats, None)
    a, b = f["beats"]
    assert b["rate_vs_overall"] / a["rate_vs_overall"] == pytest.approx(2.0, abs=0.1)


def test_key_line_pauses():
    words = [Word("w", i * 0.5, i * 0.5 + 0.3) for i in range(5)]
    words += [Word("k", 2.3 + 1.2 + i * 0.5, 2.3 + 1.2 + i * 0.5 + 0.3) for i in range(5)]
    beats = Beats([Beat("hook", 0, 9)], [KeyLine(5, 9)])
    f = compute_features(_transcript(words), _acoustics(7), beats, None)
    assert f["key_lines"][0]["pause_before_s"] == pytest.approx(1.2)


def test_time_limit():
    words = [Word("go", i * 1.0, i * 1.0 + 0.5) for i in range(130)] + [Word("end", 129.6, 130.0)]
    beats = Beats([Beat("other", 0, 130)])
    t = _transcript(words)
    assert compute_features(t, _acoustics(131), beats, 120)["overall"]["over_time_limit_s"] == pytest.approx(10)
    assert compute_features(t, _acoustics(131), beats, None)["overall"]["over_time_limit_s"] is None


def test_null_pitch_propagates():
    t, beats = _two_speed_take()
    f = compute_features(t, _acoustics(8, f0=None), beats, None)
    assert f["overall"]["pitch"] is None
    assert all(b["pitch"] is None for b in f["beats"])
    json.dumps(f, allow_nan=False)


def test_observations_have_no_scores_or_emotions():
    words = [Word("So", 0.0, 0.3), Word("um", 0.4, 0.6)]
    words += [Word("customer", 0.7 + 0.4 * i, 1.0 + 0.4 * i) for i in range(20)]
    words += [Word("midnight", 10.0 + 0.2 * i, 10.15 + 0.2 * i) for i in range(10)]
    beats = Beats([Beat("hook", 0, 11), Beat("turn", 12, 21), Beat("resolution", 22, 31)], [KeyLine(22, 25, "the call")])
    f = compute_features(_transcript(words), _acoustics(13), beats, 10)
    obs = observations(f)
    assert len(obs) >= 4
    for o in obs:
        assert not re.search(r"\b(\d+/\d+|score|grade|rating|rank)\b", o, re.I), o
        assert not any(re.search(rf"\b{b}\b", o, re.I) for b in BANNED), o


def test_ending_slope_ignores_trailing_silence():
    words = [Word("go", 0.5 * i, 0.5 * i + 0.4) for i in range(20)]
    beats = Beats([Beat("other", 0, 19)])
    ac = _acoustics(10.5)
    for i, tt in enumerate(ac.times):
        ac.intensity_db[i] = 70.0
        if tt > 9.2:  # word end overruns into silence
            ac.intensity_db[i], ac.f0_hz[i] = 20.0, None
    f = compute_features(_transcript(words), ac, beats, None)
    assert abs(f["ending"]["intensity_slope_db_per_s"]) < 1.0


def test_long_key_line_not_cut_mid_word():
    words = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(
        "then a plumber named rosa called me at midnight because she could not pay her apprentice".split())]
    beats = Beats([Beat("turn", 0, len(words) - 1)], [KeyLine(0, len(words) - 1)])
    obs = observations(compute_features(_transcript(words), _acoustics(7), beats, None))
    quoted = [o for o in obs if "key line" in o][0]
    inner = quoted.split('"')[1].rstrip(".…")
    assert all(w in words_text for w in inner.split()) if (words_text := [w.text for w in words]) else True


def test_filler_peak_reports_ties():
    words = [Word("um", 0, .2), Word("a", .3, .5), Word("uh", .6, .8), Word("b", .9, 1.1)]
    beats = Beats([Beat("hook", 0, 1), Beat("turn", 2, 3)])
    obs = observations(compute_features(_transcript(words), _acoustics(2), beats, None))
    filler = [o for o in obs if "filler" in o][0]
    assert "most of them" not in filler and "hook" in filler and "turn" in filler


def test_zero_length_segment_gives_no_rate():
    words = [Word("Midnight.", 1.0, 1.0)] + [Word("go", 1.2 + 0.4 * i, 1.5 + 0.4 * i) for i in range(10)]
    beats = Beats([Beat("hook", 0, 10)], [KeyLine(0, 0)])
    f = compute_features(_transcript(words), _acoustics(6), beats, None)
    assert f["key_lines"][0]["rate_vs_overall"] is None
    assert all("1050000" not in o for o in observations(f))


def _quiet_then_loud():
    """Hook spoken at 64 dB, turn at 72 dB."""
    t, beats = _two_speed_take()
    ac = _acoustics(8)
    for i, tt in enumerate(ac.times):
        ac.intensity_db[i] = 64.0 if tt < 4.8 else 72.0
    return t, beats, ac


def test_loudness_overall_and_per_beat():
    t, beats, ac = _quiet_then_loud()
    f = compute_features(t, ac, beats, None)
    assert f["overall"]["loudness"]["range_db_p10_p90"] == pytest.approx(8.0)
    hook, turn = f["beats"]
    assert hook["loudness_vs_overall_db"] < -1 < 1 < turn["loudness_vs_overall_db"]
    json.dumps(f, allow_nan=False)


def test_key_line_loudness_vs_overall():
    t, _, ac = _quiet_then_loud()
    beats = Beats([Beat("hook", 0, 9), Beat("turn", 10, 19)], [KeyLine(12, 18)])
    f = compute_features(t, ac, beats, None)
    assert f["key_lines"][0]["loudness_vs_overall_db"] > 1


def test_loudness_observations_are_relative_not_absolute():
    t, beats, ac = _quiet_then_loud()
    obs = observations(compute_features(t, ac, beats, None))
    loud = [o for o in obs if "loud" in o.lower()]
    assert any("turn" in o and "hook" in o for o in loud), loud
    assert any("varied" in o for o in loud), loud
    for o in loud:
        assert not re.search(r"\b(64|72)(\.0)? dB\b", o), o  # absolute level depends on the mic
        assert not any(re.search(rf"\b{b}\b", o, re.I) for b in BANNED), o


def test_no_loudness_without_voiced_frames():
    t, beats = _two_speed_take()
    f = compute_features(t, _acoustics(8, f0=None), beats, None)
    assert f["overall"]["loudness"] is None
    assert all(b["loudness_vs_overall_db"] is None for b in f["beats"])
    assert not [o for o in observations(f) if "loudest" in o or "varied" in o]


def test_beats_and_key_lines_carry_times():
    t, _ = _two_speed_take()
    beats = Beats([Beat("hook", 0, 9), Beat("turn", 10, 19)], key_lines=[KeyLine(10, 12, None)])
    f = compute_features(t, _acoustics(8), beats, None)
    assert (f["beats"][0]["start_s"], f["beats"][0]["end_s"]) == (0.0, 4.9)
    assert (f["beats"][1]["start_s"], f["beats"][1]["end_s"]) == (5.0, 7.45)
    assert (f["key_lines"][0]["start_s"], f["key_lines"][0]["end_s"]) == (5.0, 5.7)
