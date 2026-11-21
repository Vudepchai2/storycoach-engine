import json

import pytest

from storycoach import record as rec
from storycoach.__main__ import main
from storycoach.candidates import DEFAULT_KEY_BEATS, KEY_BEATS, select_candidates
from storycoach.scenarios import SCENARIOS, scenario_for
from storycoach.session import Session

from test_candidates import _take


def _new(tmp_path, *args):
    root = tmp_path / "sessions"
    main(["new", "Ada", "--root", str(root), "--self", *args])
    return root / "ada"


def test_new_with_scenario_sets_target_and_time_limit(tmp_path):
    data = json.loads((_new(tmp_path, "--scenario", "pitch") / "session.json").read_text(encoding="utf-8"))
    assert data["scenario"] == "pitch"
    assert data["target_length_s"] == [60, 180]
    assert data["time_limit_s"] == 180


def test_explicit_time_limit_wins(tmp_path):
    data = json.loads((_new(tmp_path, "--scenario", "job", "--time-limit", "90") / "session.json").read_text(encoding="utf-8"))
    assert data["time_limit_s"] == 90 and data["target_length_s"] == [60, 120]


def test_unknown_scenario_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as e:
        main(["new", "Ada", "--root", str(tmp_path), "--scenario", "poem"])
    assert e.value.code == 2


def test_scenario_values():
    assert {k: (v["target_s"], set(v["key_beats"])) for k, v in SCENARIOS.items()} == {
        "pitch": ((60, 180), {"turn", "resolution", "ask"}),
        "job": ((60, 120), {"turn", "resolution"}),
        "speech": ((120, 300), {"hook", "turn", "resolution"}),
        "content": ((30, 90), {"hook", "resolution"}),
    }
    assert DEFAULT_KEY_BEATS == frozenset({"turn", "ask"}) and KEY_BEATS == DEFAULT_KEY_BEATS


def test_scenario_for():
    assert scenario_for({}) is None
    assert scenario_for({"scenario": "content"}) is SCENARIOS["content"]
    assert scenario_for({"scenario": "unknown"}) is None


def test_candidates_use_scenario_key_beats():
    cur = _take(beat_louds=(-4.0, 0.1, -0.1, 0.1))
    prev = _take(beat_louds=(-4.0, 0.1, -0.1, 0.1))
    held = select_candidates(cur, prev, None)
    assert held["surface"] == [] and any("hook beat" in i for i in held["held_back"])
    c = select_candidates(cur, prev, None, key_beats=SCENARIOS["content"]["key_beats"])
    assert [i["where"].get("label") for i in c["surface"]] == ["hook"]


def test_old_session_without_scenario_unchanged():
    cur = _take(beat_louds=(-4.0, 0.1, -0.1, 0.1))
    assert select_candidates(cur, cur, None, key_beats=None) == select_candidates(cur, cur, None)


def test_default_max_for_pitch_session_is_360(tmp_path, monkeypatch):
    class Quiet:
        def __enter__(self): return self
        def __exit__(self, *e): return False

    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: Quiet())
    seen = []
    monkeypatch.setattr(rec, "record", lambda out, stop, max_s, stream_factory=None, rate=16000:
                        seen.append(max_s) or {"path": str(out), "seconds": 0, "stopped_by": "time_limit", "peak": 1})
    main(["record", str(_new(tmp_path, "--scenario", "pitch"))])
    assert seen == [360]
