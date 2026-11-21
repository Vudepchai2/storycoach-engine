from storycoach.compare import compare_takes


def _f(rate):
    seg = {"syll_per_s": rate, "rate_vs_overall": 1.0, "duration_s": 10}
    return {"overall": {"syll_per_s": rate, "duration_s": 60, "fillers_per_min": 3, "mean_pause_s": 0.5},
            "opening": dict(seg), "ending": dict(seg),
            "key_lines": [{"text": "She called me at midnight", "pause_before_s": 0.1, "rate_vs_overall": 1.2}]}


def test_content_diff():
    d = compare_takes(_f(4), _f(4), "We started in a garage. She called me at midnight.",
                      "She called me at midnight. Everything changed.")
    assert d["content"]["added_sentences"] == ["Everything changed."]
    assert d["content"]["removed_sentences"] == ["We started in a garage."]
    assert d["content"]["kept"] == 1


def test_delivery_before_after():
    d = compare_takes(_f(4.5), _f(3.8), "a.", "a.")
    assert d["delivery"]["overall.syll_per_s"] == {"before": 4.5, "after": 3.8}


def test_loudness_spread_compared():
    a, b = _f(4), _f(4)
    a["overall"]["loudness"] = {"mean_db": 60, "sd_db": 2.0, "range_db_p10_p90": 5.0}
    b["overall"]["loudness"] = {"mean_db": 66, "sd_db": 3.1, "range_db_p10_p90": 7.5}
    a["key_lines"][0]["loudness_vs_overall_db"] = -0.5
    b["key_lines"][0]["loudness_vs_overall_db"] = 2.0
    d = compare_takes(a, b, "a.", "a.")["delivery"]
    assert d["overall.loudness.range_db_p10_p90"] == {"before": 5.0, "after": 7.5}
    assert d['key_line "She called me at midnight".loudness_vs_overall_db'] == {"before": -0.5, "after": 2.0}
    assert "overall.loudness.mean_db" not in d  # absolute level depends on mic and distance


def test_content_counts_and_beat_shares_compared():
    a, b = _f(4), _f(4)
    a["content"] = {"word_count": 174, "first_person_singular": 9, "number_mentions": 2,
                    "connectives": {"but": 3}, "habitual_or_hypothetical": 1}
    b["content"] = {"word_count": 157, "first_person_singular": 14, "number_mentions": 5,
                    "connectives": {"but": 1, "because": 2}, "habitual_or_hypothetical": 0}
    a["beats"] = [{"label": "context", "word_share": 0.27}, {"label": "turn", "word_share": 0.3}]
    b["beats"] = [{"label": "context", "word_share": 0.28}, {"label": "resolution", "word_share": 0.29}]
    c = compare_takes(a, b, "a.", "a.")["content"]
    assert c["counts"]["word_count"] == {"before": 174, "after": 157}
    assert c["counts"]["connectives.because"] == {"before": 0, "after": 2}
    assert c["beat_word_share"]["turn"] == {"before": 0.3, "after": None}
    assert c["beat_word_share"]["resolution"] == {"before": None, "after": 0.29}
