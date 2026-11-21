import difflib
import re

_SENT = re.compile(r"(?<=[.!?])\s+")
# Absolute loudness (loudness.mean_db) is left out: it changes with mic gain and distance.
_DELIVERY = {
    "overall": ["syll_per_s", "duration_s", "fillers_per_min", "mean_pause_s",
                "loudness.sd_db", "loudness.range_db_p10_p90"],
    "opening": ["syll_per_s", "rate_vs_overall", "loudness_vs_overall_db"],
    "ending": ["syll_per_s", "rate_vs_overall", "intensity_slope_db_per_s", "loudness_vs_overall_db"],
}
_KEY_LINE = ["pause_before_s", "pause_after_s", "rate_vs_overall", "pitch_sd_vs_overall", "loudness_vs_overall_db"]


def _get(d: dict, path: str):
    for part in path.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text.strip()) if s.strip()]


def compare_takes(prev: dict, curr: dict, prev_text: str, curr_text: str) -> dict:
    """Before/after delivery measurements and sentence-level content changes."""
    delivery = {}
    for pos, metrics in _DELIVERY.items():
        for m in metrics:
            b, a = _get(prev.get(pos, {}), m), _get(curr.get(pos, {}), m)
            if b is not None or a is not None:
                delivery[f"{pos}.{m}"] = {"before": b, "after": a}
    for kc in curr.get("key_lines", []):
        best, score = None, 0.0
        for kp in prev.get("key_lines", []):
            r = difflib.SequenceMatcher(None, kp["text"].lower(), kc["text"].lower()).ratio()
            if r > score:
                best, score = kp, r
        if best is not None and score >= 0.6:
            for m in _KEY_LINE:
                if best.get(m) is not None or kc.get(m) is not None:
                    delivery[f'key_line "{kc["text"]}".{m}'] = {"before": best.get(m), "after": kc.get(m)}

    before, after = _sentences(prev_text), _sentences(curr_text)
    added, removed, kept = [], [], 0
    sm = difflib.SequenceMatcher(None, [s.lower() for s in before], [s.lower() for s in after])
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            kept += i2 - i1
        if op in ("delete", "replace"):
            removed += before[i1:i2]
        if op in ("insert", "replace"):
            added += after[j1:j2]
    return {"delivery": delivery, "content": {
        "added_sentences": added, "removed_sentences": removed, "kept": kept,
        "counts": _content_counts(prev.get("content", {}), curr.get("content", {})),
        "beat_word_share": _beat_shares(prev.get("beats", []), curr.get("beats", [])),
    }}


def _content_counts(p: dict, c: dict) -> dict:
    out = {}
    for k in dict.fromkeys([*p, *c]):
        if k == "connectives":
            pc, cc = p.get(k, {}), c.get(k, {})
            for w in dict.fromkeys([*pc, *cc]):
                out[f"connectives.{w}"] = {"before": pc.get(w, 0), "after": cc.get(w, 0)}
        else:
            out[k] = {"before": p.get(k), "after": c.get(k)}
    return out


def _beat_shares(prev: list, curr: list) -> dict:
    """First beat per label; a label missing from one take shows as None."""
    def first(beats: list) -> dict:
        out: dict = {}
        for b in beats:
            out.setdefault(b["label"], b.get("word_share"))
        return out

    p, c = first(prev), first(curr)
    return {lab: {"before": p.get(lab), "after": c.get(lab)} for lab in dict.fromkeys([*p, *c])}
