import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from storycoach import home
from storycoach.__main__ import main
from storycoach.models import Transcript, Word
from storycoach.synth import synthesize_acoustics

CASE = Path(__file__).parent / "data" / "practice_case"


def _transcript(n=20):
    return Transcript(words=[Word(f"w{i}", 0.3 + i * 0.3, 0.3 + i * 0.3 + 0.2) for i in range(n)], text="x")


def test_synth_is_deterministic_and_marks_pauses():
    t = _transcript()
    d = {"base_hz": 180.0, "base_db": 60.0, "seed": 7, "segments": []}
    a, b = synthesize_acoustics(t, d), synthesize_acoustics(t, d)
    assert a == b
    assert len(a.times) == len(a.f0_hz) == len(a.intensity_db)
    assert a.times[1] - a.times[0] == pytest.approx(0.01)
    assert a.times[-1] >= t.words[-1].end + 0.5 - 0.011
    inside = [i for i, x in enumerate(a.times) if t.words[0].start <= x < t.words[0].end]
    gap = [i for i, x in enumerate(a.times) if t.words[0].end + 0.02 < x < t.words[1].start - 0.01]
    assert inside and gap
    assert all(isinstance(a.f0_hz[i], float) for i in inside)
    assert all(a.f0_hz[i] is None and a.intensity_db[i] == pytest.approx(35.0) for i in gap)
    json.dumps(a.to_dict(), allow_nan=False)


def test_synth_segment_db_offset():
    t = _transcript()
    d = {"base_hz": 180.0, "base_db": 60.0, "seed": 3,
         "segments": [{"start_word": 5, "end_word": 9, "db": -3.0, "pitch_sd_scale": 1.0}]}
    a = synthesize_acoustics(t, d)
    seg = (t.words[5].start, t.words[9].end)

    def mean(want_seg):
        v = [db for x, db, f in zip(a.times, a.intensity_db, a.f0_hz)
             if f is not None and ((seg[0] <= x < seg[1]) == want_seg)]
        return float(np.mean(v))
    assert 2.5 <= mean(False) - mean(True) <= 3.5


def _practice(*extra):
    main(["practice", str(CASE), *extra])


def _slug():
    from storycoach.memory import bank_slug
    return bank_slug("Maria Test")


def test_practice_creates_session_with_features(capsys):
    _practice()
    s = home.practice_dir() / "bakery-practice"
    assert str(s) in capsys.readouterr().out
    data = json.loads((s / "session.json").read_text(encoding="utf-8"))
    assert data["practice"] is True and data["mode"] == "self" and data["scenario"] == "pitch"
    assert (s / "context.md").exists()
    for n in ("take_01", "take_02"):
        take = s / n
        assert (take / "SYNTHETIC.txt").read_text(encoding="utf-8").strip() == "Made-up practice take, no real voice"
        assert (take / "words.txt").read_text(encoding="utf-8").splitlines()[0] == "0\tLast"
        f = json.loads((take / "features.json").read_text(encoding="utf-8"))
        assert "candidates" in f
    f2 = json.loads((s / "take_02" / "features.json").read_text(encoding="utf-8"))
    assert f2["candidates"]["previous_take"] == "take_01"


def test_practice_prints_bank_and_stores_person(capsys):
    _practice()
    out = capsys.readouterr().out.splitlines()
    bank = home.practice_dir() / "people" / _slug()
    assert out[-2] == str(home.practice_dir() / "bakery-practice")
    assert out[-1] == f"memory: {bank}"
    data = json.loads((home.practice_dir() / "bakery-practice" / "session.json").read_text(encoding="utf-8"))
    assert data["person"] == _slug() == bank.name


def test_practice_memory_is_separate():
    _practice()
    assert list(home.people_dir().iterdir()) == []
    assert list(home.sessions_dir().iterdir()) == []
    assert (home.practice_dir() / "people" / _slug() / "log.jsonl").exists()
    assert (home.practice_dir() / "people" / _slug() / "pages").is_dir()


def test_practice_refuses_existing_without_reset(capsys):
    _practice()
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        _practice()
    assert e.value.code == 1
    err = capsys.readouterr().err
    assert "bakery-practice" in err and "--reset" in err
    _practice("--reset")
    assert (home.practice_dir() / "bakery-practice" / "take_02" / "features.json").exists()


def test_reset_stays_inside_practice_dir(tmp_path):
    home.ensure_home()
    sentinel = home.sessions_dir() / "keep.txt"
    sentinel.write_text("mine", encoding="utf-8")
    other = home.practice_dir() / "other-case"
    other.mkdir()
    (other / "x.txt").write_text("x", encoding="utf-8")
    _practice()
    _practice("--reset")
    assert sentinel.read_text(encoding="utf-8") == "mine"
    assert (other / "x.txt").exists()
    # a case named to climb out of practice/ is flattened or refused, never followed
    evil = tmp_path / "evil"
    shutil.copytree(CASE, evil)
    c = json.loads((evil / "case.json").read_text(encoding="utf-8"))
    c["name"] = "../../sessions"
    (evil / "case.json").write_text(json.dumps(c), encoding="utf-8")
    try:
        main(["practice", str(evil), "--reset"])
    except SystemExit:
        pass
    assert sentinel.read_text(encoding="utf-8") == "mine"
    assert home.sessions_dir().is_dir()
