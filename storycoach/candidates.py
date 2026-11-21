"""Decide which measurements are worth raising after a take.

Two gates, from reports/Feedback design for speaking coaches.md:
1. Unusual for this speaker: outside a noise band taken from this take's own spread.
2. Relevant: it touches the speaker's chosen focus, or (with no focus) it is a key moment
   that sat outside the band in this take and the previous one, in the same direction.

Everything that passes gate 1 but not gate 2 is held back. Fillers are never candidates.
"""
import difflib
import re

import numpy as np

from storycoach.scenarios import DEFAULT_KEY_BEATS

MAX_SURFACE = 2
KEY_BEATS = DEFAULT_KEY_BEATS  # kept for older imports
SETUP_BEATS = {"context"}
SHARE_CHANGE = 0.05  # word-share moves smaller than 5 points are left out
LINE_MATCH = 0.6

# metric -> (baseline, band floor). Baseline "pause" means the take's mean pause.
_LINE_METRICS = {
    "loudness_vs_overall_db": (0.0, 1.0),
    "rate_vs_overall": (1.0, 0.10),
    "pitch_sd_vs_overall": (1.0, 0.30),
    "pause_before_s": ("pause", 0.4),
    "pause_after_s": ("pause", 0.4),
}
_BEAT_METRICS = ["loudness_vs_overall_db", "rate_vs_overall"]
_SPREAD_FROM_BEATS = {"loudness_vs_overall_db", "rate_vs_overall", "pitch_sd_vs_overall"}


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))]


def _similar(focus_line: str, text: str) -> bool:
    """A focus line is the speaker's paraphrase, so also accept most of its words appearing in the line.

    Words match on their first five letters, so "converted" matches "convert".
    """
    a, b = focus_line.lower().strip(), text.lower().strip()
    if a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= LINE_MATCH:
        return True
    fa, fb = _tokens(a), {w[:5] for w in _tokens(b)}
    return len(fa) >= 3 and sum(w[:5] in fb for w in fa) / len(fa) >= LINE_MATCH


def _bands(f: dict) -> dict:
    bands = {}
    for m, (_, floor) in _LINE_METRICS.items():
        vals = [b[m] for b in f.get("beats", []) if b.get(m) is not None] if m in _SPREAD_FROM_BEATS else []
        spread = float(np.std(vals)) if len(vals) >= 2 else 0.0
        bands[m] = round(max(floor, spread), 2)
    return bands


def _baseline(m: str, f: dict) -> float | None:
    base = _LINE_METRICS[m][0]
    return f.get("overall", {}).get("mean_pause_s") if base == "pause" else base


def _moments(f: dict, key_beats=DEFAULT_KEY_BEATS):
    """Yield (where, key_moment, metric list, source dict) for every key line and beat."""
    for k in f.get("key_lines", []):
        yield ({"type": "key_line", "text": k["text"], "start_s": k.get("start_s"), "end_s": k.get("end_s")},
               True, list(_LINE_METRICS), k)
    seen = set()
    for b in f.get("beats", []):
        if b["label"] in seen:
            continue
        seen.add(b["label"])
        yield ({"type": "beat", "label": b["label"], "start_s": b.get("start_s"), "end_s": b.get("end_s")},
               b["label"] in key_beats, _BEAT_METRICS, b)


def _match_prev(where: dict, prev: dict | None) -> dict | None:
    if not prev:
        return None
    if where["type"] == "beat":
        return next((b for b in prev.get("beats", []) if b["label"] == where["label"]), None)
    best, score = None, 0.0
    for k in prev.get("key_lines", []):
        r = difflib.SequenceMatcher(None, k["text"].lower(), where["text"].lower()).ratio()
        if r > score:
            best, score = k, r
    return best if score >= LINE_MATCH else None


def _touches(where: dict, focus: dict | None) -> bool:
    if not focus:
        return False
    if where["type"] == "beat":
        return bool(focus.get("beat")) and focus["beat"] == where["label"]
    return bool(focus.get("line")) and _similar(focus["line"], where["text"])


def _deviation(v, m, f):
    base = _baseline(m, f)
    if v is None or base is None:
        return None
    return v - base


def _id(m: str, where: dict) -> str:
    place = f'key line "{where["text"]}"' if where["type"] == "key_line" else f"{where['label']} beat"
    return f"{m} at {place}"


def select_candidates(f: dict, prev: dict | None, focus: dict | None, key_beats=None) -> dict:
    key_beats = DEFAULT_KEY_BEATS if key_beats is None else key_beats
    bands, prev_bands = _bands(f), _bands(prev) if prev else {}
    surface, held = [], []
    for where, key_moment, metrics, src in _moments(f, key_beats):
        p_src = _match_prev(where, prev)
        touches = _touches(where, focus)
        for m in metrics:
            v = src.get(m)
            dev = _deviation(v, m, f)
            if dev is None:
                continue
            band = bands[m]
            pv = p_src.get(m) if p_src else None
            change = round(v - pv, 2) if pv is not None else None
            out = abs(dev) > band
            moved = change is not None and abs(change) > band
            pdev = _deviation(pv, m, prev) if prev else None
            prev_out = pdev is not None and abs(pdev) > prev_bands[m] and (pdev > 0) == (dev > 0)
            if not (out or moved):
                continue
            item = {"id": _id(m, where), "metric": m, "where": where, "value": v, "previous": pv,
                    "change": change, "baseline": _baseline(m, f), "band": band, "out_of_band": out,
                    "moved": moved, "out_of_band_last_take": prev_out, "touches_focus": touches,
                    "key_moment": key_moment}
            if focus:
                ok = touches
            else:
                ok = key_moment and out and prev_out
            weight = max(abs(dev), abs(change or 0)) / band
            (surface if ok else held).append((weight, item))
    surface.sort(key=lambda x: -x[0])
    chosen = [i for _, i in surface[:MAX_SURFACE]]
    held_back = [i["id"] for _, i in surface[MAX_SURFACE:]] + [i["id"] for _, i in held]
    return {"mode": "focus" if focus else "no_focus", "focus": focus, "focus_matched": _focus_matched(f, focus),
            "surface": chosen,
            "held_back": held_back, "content": _content(f, prev)}


def _focus_matched(f: dict, focus: dict | None) -> bool | None:
    """None when there is nothing to match (no focus, or a free-text focus)."""
    if not focus or not (focus.get("line") or focus.get("beat")):
        return None
    return any(_touches(where, focus) for where, *_ in _moments(f))


def _shares(f: dict | None) -> dict:
    out: dict = {}
    for b in (f or {}).get("beats", []):
        out.setdefault(b["label"], b.get("word_share"))
    return out


def _content(f: dict, prev: dict | None) -> dict:
    s = _shares(f)
    setup = sum(v for k, v in s.items() if k in SETUP_BEATS and v is not None)
    payoff = sum(s.get(k) or 0 for k in ("turn", "resolution"))
    heavy = (setup >= payoff) if any(k in s for k in SETUP_BEATS) else None
    changes = {}
    if prev:
        p = _shares(prev)
        for lab, after in s.items():
            before = p.get(lab)
            if before is not None and after is not None and abs(after - before) >= SHARE_CHANGE:
                changes[lab] = {"before": before, "after": after}
    return {"setup_heavy": heavy, "setup_share": round(setup, 3), "turn_and_resolution_share": round(payoff, 3),
            "word_share_changes": changes}
