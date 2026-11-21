"""Combine transcript timing and acoustics into per-beat, key-line and ending features.

Outputs are measurements only: no scores, grades or emotion labels.
"""
import numpy as np

from storycoach.acoustics import loudness_stats, semitone_stats, voiced_median_hz, window
from storycoach.beats import Beats
from storycoach.content import content_counts, word_shares
from storycoach.models import Acoustics, Transcript
from storycoach.timing import count_syllables, find_fillers, find_pauses, speech_bounds

EDGE_FRACTION = 0.15
MIN_SECONDS_PER_WORD = 0.15
LOUDNESS_NOTICE_DB = 1.0  # smaller loudness differences are not mentioned


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def _segment(t: Transcript, ac: Acoustics, s: int, e: int, ctx: dict) -> dict:
    words = t.words[s : e + 1]
    start, end = words[0].start, words[-1].end
    dur = end - start
    sylls = sum(count_syllables(w.text) for w in words)
    measurable = dur >= MIN_SECONDS_PER_WORD * len(words)
    rate = sylls / dur if measurable else None
    loud = loudness_stats(window(ac, start, end))
    return {
        "start_s": _r(start),
        "end_s": _r(end),
        "loudness": loud,
        "loudness_vs_overall_db": (
            _r(loud["mean_db"] - ctx["loud_mean"]) if loud and ctx["loud_mean"] is not None else None
        ),
        "duration_s": _r(dur),
        "syll_per_s": _r(rate),
        "rate_vs_overall": _r(rate / ctx["rate"]) if rate is not None and ctx["rate"] else None,
        "fillers": sum(1 for i in ctx["fillers"] if s <= i <= e),
        "pauses": sum(1 for p in ctx["pauses"] if s <= p.after_word < e),
        "pitch": semitone_stats(window(ac, start, end), ctx["ref_hz"]),
    }


def compute_features(t: Transcript, ac: Acoustics, beats: Beats, time_limit_s: float | None) -> dict:
    n = len(t.words)
    start, end = speech_bounds(t.words)
    dur = max(end - start, 1e-6)
    pauses = find_pauses(t.words)
    fillers = find_fillers(t.words)
    speech = window(ac, start, end)
    ref_hz = voiced_median_hz(speech)
    rate = sum(count_syllables(w.text) for w in t.words) / dur
    overall_loud = loudness_stats(speech)
    ctx = {"rate": rate, "pauses": pauses, "fillers": fillers, "ref_hz": ref_hz,
           "loud_mean": overall_loud["mean_db"] if overall_loud else None}
    overall_pitch = semitone_stats(speech, ref_hz)

    overall = {
        "duration_s": _r(dur),
        "syll_per_s": _r(rate),
        "fillers_per_min": _r(len(fillers) / dur * 60),
        "filler_count": len(fillers),
        "pause_count": len(pauses),
        "mean_pause_s": _r(np.mean([p.duration for p in pauses])) if pauses else None,
        "pitch": overall_pitch,
        "loudness": overall_loud,
        "over_time_limit_s": _r(dur - time_limit_s) if time_limit_s else None,
        "time_limit_s": time_limit_s,
    }

    beat_feats = [
        {"label": b.label, "word_share": share, **_segment(t, ac, b.start_word, b.end_word, ctx)}
        for b, share in zip(beats.beats, word_shares(beats, n))
    ]

    key_lines = []
    for k in beats.key_lines:
        seg = _segment(t, ac, k.start_word, k.end_word, ctx)
        before = t.words[k.start_word].start - t.words[k.start_word - 1].end if k.start_word > 0 else 0.0
        after = t.words[k.end_word + 1].start - t.words[k.end_word].end if k.end_word < n - 1 else None
        sd_ratio = None
        if seg["pitch"] and overall_pitch and overall_pitch["sd_st"] > 0:
            sd_ratio = _r(seg["pitch"]["sd_st"] / overall_pitch["sd_st"])
        key_lines.append({
            "text": " ".join(w.text for w in t.words[k.start_word : k.end_word + 1]),
            "note": k.note,
            "pause_before_s": _r(max(before, 0.0)),
            "pause_after_s": _r(max(after, 0.0)) if after is not None else None,
            "rate_vs_overall": seg["rate_vs_overall"],
            "pitch_sd_vs_overall": sd_ratio,
            "loudness_vs_overall_db": seg["loudness_vs_overall_db"],
            "start_s": seg["start_s"],
            "end_s": seg["end_s"],
        })

    edge = max(1, round(EDGE_FRACTION * n))
    opening = _segment(t, ac, 0, edge - 1, ctx)
    ending = _segment(t, ac, n - edge, n - 1, ctx)
    ew = window(ac, t.words[n - edge].start, end)
    voiced = [(tt, db) for tt, db, f0 in zip(ew.times, ew.intensity_db, ew.f0_hz) if f0]
    ending["intensity_slope_db_per_s"] = (
        _r(np.polyfit([v[0] for v in voiced], [v[1] for v in voiced], 1)[0]) if len(voiced) >= 10 else None
    )

    peak = max((b["fillers"] for b in beat_feats), default=0)
    return {
        "overall": overall,
        "content": content_counts(t),
        "beats": beat_feats,
        "key_lines": key_lines,
        "opening": opening,
        "ending": ending,
        "filler_peak_beats": [b["label"] for b in beat_feats if peak and b["fillers"] == peak],
        "filler_peak_count": peak,
    }


def _quote(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "..."


def _x(v: float) -> str:
    return f"{v:.1f}x"


def _db_rel(v: float) -> str:
    return f"about {abs(v):.1f} dB {'above' if v >= 0 else 'below'} your average"


def observations(f: dict) -> list[str]:
    """Factual, judgement-free sentences derived from the features."""
    o = f["overall"]
    out = [f"Your telling lasted {o['duration_s']:.0f} s at an average of {o['syll_per_s']:.1f} syllables per second."]
    if o["time_limit_s"]:
        diff = o["over_time_limit_s"]
        out.append(
            f"That is {abs(diff):.0f} s {'over' if diff > 0 else 'under'} your time limit of {o['time_limit_s']:.0f} s."
        )
    if o["filler_count"]:
        where = " and ".join(f["filler_peak_beats"])
        plural = "beats" if len(f["filler_peak_beats"]) > 1 else "beat"
        out.append(
            f"You used {o['filler_count']} filler words ({o['fillers_per_min']:.1f} per minute); "
            f"the most in one beat was {f['filler_peak_count']}, in your {where} {plural}."
        )
    else:
        out.append("You used no filler words.")
    if o["pause_count"]:
        out.append(f"You paused {o['pause_count']} times, for {o['mean_pause_s']:.1f} s on average.")
    if o.get("loudness"):
        out.append(
            f"Your loudness varied across about {o['loudness']['range_db_p10_p90']:.1f} dB "
            "(the middle 80% of your voiced speech)."
        )
    if len(f["beats"]) >= 2 and all("word_share" in b for b in f["beats"]):
        big = max(f["beats"], key=lambda b: b["word_share"])
        out.append(f"Your {big['label']} beat took {big['word_share'] * 100:.0f}% of your words.")
    rel = [b for b in f["beats"] if b.get("loudness_vs_overall_db") is not None]
    if len(rel) >= 2:
        hi = max(rel, key=lambda b: b["loudness_vs_overall_db"])
        lo = min(rel, key=lambda b: b["loudness_vs_overall_db"])
        if hi["loudness_vs_overall_db"] - lo["loudness_vs_overall_db"] >= LOUDNESS_NOTICE_DB:
            out.append(
                f"Your loudest beat was your {hi['label']}, {_db_rel(hi['loudness_vs_overall_db'])}; "
                f"your quietest was your {lo['label']}, {_db_rel(lo['loudness_vs_overall_db'])}."
            )
    op = f["opening"]
    if op["rate_vs_overall"] is not None:
        out.append(f"Your opening was spoken at {_x(op['rate_vs_overall'])} your average pace.")
    for k in f["key_lines"]:
        text = _quote(k["text"])
        after = f" and {k['pause_after_s']:.1f} s after it" if k["pause_after_s"] is not None else ""
        out.append(f'You paused {k["pause_before_s"]:.1f} s before the key line "{text}"{after}.')
        if k["rate_vs_overall"] is not None:
            out.append(f'You spoke "{text}" at {_x(k["rate_vs_overall"])} your average pace.')
        if k["pitch_sd_vs_overall"] is not None:
            out.append(f'Your pitch moved {_x(k["pitch_sd_vs_overall"])} as much on "{text}" as across the whole telling.')
        kl = k.get("loudness_vs_overall_db")
        if kl is not None and abs(kl) >= LOUDNESS_NOTICE_DB:
            out.append(f'You spoke "{text}" about {abs(kl):.1f} dB {"louder" if kl > 0 else "quieter"} than your average.')
    en = f["ending"]
    if en["rate_vs_overall"] is not None:
        out.append(f"Your ending was spoken at {_x(en['rate_vs_overall'])} your average pace.")
    slope = en.get("intensity_slope_db_per_s")
    if slope is not None and abs(slope) >= 0.5:
        out.append(f"Your loudness {'fell' if slope < 0 else 'rose'} by about {abs(slope):.1f} dB per second across your ending.")
    return out
