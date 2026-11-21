import json

from storycoach.reference import build_reference, place


def _feat(tmp_path, i, rate):
    p = tmp_path / f"f{i}.json"
    seg = {"syll_per_s": rate, "rate_vs_overall": 1.0}
    p.write_text(json.dumps({"overall": {"syll_per_s": rate}, "opening": seg, "ending": seg,
                             "key_lines": [{"pause_before_s": 0.5 + i / 10, "rate_vs_overall": 0.9}]}))
    return p


def test_place_bands():
    ref = {"overall": {"syll_per_s": {"p25": 1, "p50": 1.5, "p75": 2, "n": 9}}}
    assert [place(v, "overall", "syll_per_s", ref) for v in (0.5, 1.5, 3)] == ["below_typical", "typical", "above_typical"]


def test_place_none_without_reference():
    assert place(1.0, "overall", "syll_per_s", None) is None
    assert place(None, "overall", "syll_per_s", {"overall": {}}) is None


def test_reference_requires_n5(tmp_path):
    four = [_feat(tmp_path, i, 3 + i / 10) for i in range(4)]
    assert build_reference(four)["overall"] == {}
    six = four + [_feat(tmp_path, i, 3 + i / 10) for i in range(4, 6)]
    ref = build_reference(six)
    assert ref["overall"]["syll_per_s"]["n"] == 6
    assert ref["key_lines"]["pause_before_s"]["n"] == 6
