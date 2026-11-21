import json

from storycoach.candidates import select_candidates

LINE = "she called me at midnight"


def _beat(label, loud=0.0, rate=1.0, share=0.2, start=0.0):
    return {"label": label, "word_share": share, "rate_vs_overall": rate, "loudness_vs_overall_db": loud,
            "start_s": start, "end_s": start + 10, "fillers": 3}


def _take(line_loud=0.0, line_pause=0.5, beat_louds=(0.3, -0.3, 0.2, -0.2), turn_rate=1.0,
          shares=(0.1, 0.45, 0.2, 0.25)):
    labels = ["hook", "context", "turn", "resolution"]
    beats = [_beat(lab, loud=lv, share=s, start=i * 10.0) for i, (lab, lv, s) in enumerate(zip(labels, beat_louds, shares))]
    beats[2]["rate_vs_overall"] = turn_rate
    return {
        "overall": {"mean_pause_s": 0.5, "fillers_per_min": 6.0, "filler_count": 6},
        "beats": beats,
        "key_lines": [{"text": LINE, "pause_before_s": line_pause, "pause_after_s": 0.5, "rate_vs_overall": 1.0,
                       "pitch_sd_vs_overall": 1.0, "loudness_vs_overall_db": line_loud, "start_s": 21.0, "end_s": 24.0}],
    }


def _ids(c, key="surface"):
    return [i["id"] for i in c[key]]


def test_single_take_dip_without_focus_is_held_back_not_surfaced():
    c = select_candidates(_take(line_loud=-3.6), prev=None, focus=None)
    assert c["mode"] == "no_focus"
    assert c["surface"] == []
    assert any("loudness" in i for i in c["held_back"])


def test_dip_in_two_takes_running_surfaces_without_focus():
    c = select_candidates(_take(line_loud=-3.6), prev=_take(line_loud=-2.8), focus=None)
    item = c["surface"][0]
    assert item["metric"] == "loudness_vs_overall_db" and item["where"]["text"] == LINE
    assert item["previous"] == -2.8 and item["where"]["start_s"] == 21.0


def test_focus_line_change_since_last_take_surfaces():
    focus = {"text": "the midnight call should hit hard", "line": "called me at midnight"}
    c = select_candidates(_take(line_loud=-3.6), prev=_take(line_loud=-1.0), focus=focus)
    assert c["mode"] == "focus"
    item = c["surface"][0]
    assert item["touches_focus"] and item["moved"]
    assert item["change"] == -2.6


def test_focus_line_within_band_and_unchanged_stays_quiet():
    focus = {"text": "hit hard", "line": LINE}
    c = select_candidates(_take(line_loud=-0.4), prev=_take(line_loud=-0.3), focus=focus)
    assert c["surface"] == []


def test_dip_on_line_outside_focus_is_not_surfaced():
    c = select_candidates(_take(line_loud=-3.6), prev=_take(line_loud=-3.0), focus={"text": "slow the ask", "beat": "ask"})
    assert c["surface"] == []


def test_focus_beat_pace_surfaces():
    c = select_candidates(_take(turn_rate=1.4), prev=_take(turn_rate=1.0), focus={"text": "slow the turn", "beat": "turn"})
    item = c["surface"][0]
    assert item["where"] == {"type": "beat", "label": "turn", "start_s": 20.0, "end_s": 30.0}
    assert item["metric"] == "rate_vs_overall"


def test_fillers_are_never_candidates():
    c = select_candidates(_take(), prev=_take(), focus=None)
    assert not any("filler" in json.dumps(i) for i in c["surface"] + c["held_back"])


def test_at_most_two_surface():
    t = _take(line_loud=-4.0, line_pause=2.0, turn_rate=1.5)
    t["key_lines"][0]["pause_after_s"] = 2.0
    c = select_candidates(t, prev=_take(), focus={"text": "the turn", "beat": "turn", "line": LINE})
    assert len(c["surface"]) <= 2


def test_band_comes_from_this_takes_spread():
    # Beats vary a lot in loudness, so a 1.5 dB dip on the line is ordinary for this speaker.
    t = _take(line_loud=-1.5, beat_louds=(3.0, -3.0, 2.5, -2.5))
    c = select_candidates(t, prev=_take(line_loud=-1.5, beat_louds=(3.0, -3.0, 2.5, -2.5)), focus=None)
    assert c["surface"] == []


def test_setup_heavy_flag():
    assert select_candidates(_take(shares=(0.1, 0.45, 0.2, 0.25)), None, None)["content"]["setup_heavy"] is True
    assert select_candidates(_take(shares=(0.1, 0.2, 0.4, 0.3)), None, None)["content"]["setup_heavy"] is False


def test_word_share_changes_reported():
    c = select_candidates(_take(shares=(0.1, 0.45, 0.2, 0.25)), _take(shares=(0.1, 0.3, 0.3, 0.3)), None)
    assert c["content"]["word_share_changes"]["context"] == {"before": 0.3, "after": 0.45}
    assert "hook" not in c["content"]["word_share_changes"]  # unchanged beats left out


def _real_line_take(line_loud):
    t = _take(line_loud=line_loud)
    t["key_lines"][0]["text"] = "I managed to convert 30 of them into beta testers for our product."
    return t


def test_paraphrased_focus_line_still_matches():
    focus = {"text": "hit hard", "line": "converted 30 builders into beta testers"}
    c = select_candidates(_real_line_take(-3.6), _real_line_take(-1.0), focus)
    assert c["focus_matched"] is True
    assert c["surface"] and c["surface"][0]["touches_focus"]


def test_focus_line_matching_nothing_is_flagged():
    c = select_candidates(_take(line_loud=-3.6), None, {"text": "x", "line": "the pricing slide went wrong"})
    assert c["focus_matched"] is False and c["surface"] == []


def test_short_focus_line_does_not_match_by_word_overlap():
    t = _take(line_loud=-3.6)
    t["key_lines"][0]["text"] = "and then the ask came from her"
    c = select_candidates(t, None, {"text": "x", "line": "the ask"})
    assert c["focus_matched"] is True  # substring still counts
    c = select_candidates(t, None, {"text": "x", "line": "then her"})
    assert c["focus_matched"] is False
