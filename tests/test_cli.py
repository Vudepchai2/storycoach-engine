import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from storycoach.session import Session

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "storycoach", *map(str, args)], capture_output=True, text=True,
                          cwd=cwd, env={**os.environ, "PYTHONPATH": str(ROOT)})


def _session(tmp_path, recording=False):
    s = Session.create(tmp_path, "Ada Founder", 120)
    if recording:
        s.data["consent"]["recording"] = True
        s.save()
    return s


def test_analyse_refuses_without_consent(tmp_path, tone_wav):
    s = _session(tmp_path)
    r = run("analyse", s.dir, tone_wav())
    assert r.returncode == 2
    assert "Consent to record not given for this session." in r.stderr


def test_take_numbering(tmp_path):
    s = _session(tmp_path)
    first = s.next_take_dir()
    first.mkdir()
    assert first.name == "take_01"
    assert s.next_take_dir().name == "take_02"


def test_features_requires_beats(tmp_path):
    take = tmp_path / "take_01"
    take.mkdir()
    r = run("features", take)
    assert r.returncode != 0 and "beats.json" in r.stderr


def test_features_reports_beats_errors(tmp_path):
    take = tmp_path / "take_01"
    take.mkdir()
    (take / "transcript.json").write_text(json.dumps({"text": "a b", "words": [
        {"text": "a", "start": 0, "end": 0.2}, {"text": "b", "start": 0.3, "end": 0.5}]}))
    (take / "acoustics.json").write_text(json.dumps({"times": [0.0], "f0_hz": [None], "intensity_db": [60.0]}))
    (take / "beats.json").write_text(json.dumps({"beats": [{"label": "climax", "start_word": 0, "end_word": 1}]}))
    r = run("features", take)
    assert r.returncode != 0 and "unknown label 'climax'" in r.stderr


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows System.Speech")
def test_end_to_end(tmp_path, tts_wav):
    r = run("new", "Ada Founder", "--time-limit", "120", "--root", tmp_path)
    assert r.returncode == 0, r.stderr
    sdir = Path(r.stdout.strip())
    data = json.loads((sdir / "session.json").read_text())
    data["consent"]["recording"] = True
    (sdir / "session.json").write_text(json.dumps(data))
    r = run("analyse", sdir, tts_wav("Our first customer called me at midnight. That call changed everything."))
    assert r.returncode == 0, r.stderr
    take = Path(r.stdout.strip())
    n = len((take / "words.txt").read_text().strip().splitlines())
    (take / "beats.json").write_text(json.dumps({"beats": [{"label": "other", "start_word": 0, "end_word": n - 1}],
                                                 "key_lines": [{"start_word": 0, "end_word": 2, "note": ""}]}))
    r = run("features", take)
    assert r.returncode == 0, r.stderr
    assert json.loads((take / "features.json").read_text())["observations"]


def test_failed_analyse_leaves_no_take(tmp_path):
    s = _session(tmp_path, recording=True)
    r = run("analyse", s.dir, tmp_path / "missing.m4a")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr and "missing.m4a" in r.stderr
    assert not list(s.dir.glob("take_*"))


def test_compare_missing_features_is_clean(tmp_path):
    a, b = tmp_path / "take_01", tmp_path / "take_02"
    a.mkdir(); b.mkdir()
    r = run("compare", a, b)
    assert r.returncode == 1
    assert "Traceback" not in r.stderr and "features.json" in r.stderr


def test_new_creates_context_and_question_log(tmp_path):
    r = run("new", "Ada Founder", "--root", tmp_path)
    sdir = Path(r.stdout.strip())
    assert (sdir / "context.md").exists() and (sdir / "questions_log.md").exists()


def test_take_numbering_after_deleted_take(tmp_path):
    s = _session(tmp_path)
    for n in ("take_01", "take_03"):
        (s.dir / n).mkdir()
    assert s.next_take_dir().name == "take_04"


def test_string_false_is_not_consent(tmp_path, tone_wav):
    s = _session(tmp_path)
    s.data["consent"]["recording"] = "false"
    s.save()
    assert run("analyse", s.dir, tone_wav()).returncode == 2


def test_close_without_research_consent_removes_measurements(tmp_path):
    s = _session(tmp_path)
    (s.dir / "take_01").mkdir()
    (s.dir / "take_01" / "features.json").write_text("{}")
    (s.dir / "compare_01_02.json").write_text("{}")
    r = run("close", s.dir)
    assert r.returncode == 0, r.stderr
    assert not (s.dir / "take_01").exists() and not (s.dir / "compare_01_02.json").exists()


def test_close_with_research_consent_keeps_measurements(tmp_path):
    s = _session(tmp_path)
    s.data["consent"]["research"] = True
    s.save()
    (s.dir / "take_01").mkdir()
    assert run("close", s.dir).returncode == 0
    assert (s.dir / "take_01").exists()


def test_placements_only_rate_metrics():
    from storycoach.__main__ import _placements
    ref = {pos: {m: {"p25": 0, "p50": 1, "p75": 2, "n": 9} for m in
                 ["duration_s", "pauses", "fillers", "syll_per_s", "rate_vs_overall", "pitch.median_st"]}
           for pos in ("opening", "ending", "overall", "key_lines")}
    seg = {"duration_s": 5, "pauses": 1, "fillers": 0, "syll_per_s": 1, "rate_vs_overall": 1, "pitch": {"median_st": 0}}
    p = _placements({"opening": seg, "ending": seg, "overall": seg, "key_lines": []}, ref)
    assert set(p["opening"]) == {"syll_per_s", "rate_vs_overall"}


def _new_self(tmp_path):
    r = run("new", "Me", "--self", "--root", tmp_path, "--people-root", tmp_path / "people")
    assert r.returncode == 0 and r.stdout.strip(), r.stderr
    return Path(r.stdout.strip())


def test_new_self_mode_grants_recording(tmp_path):
    data = json.loads((_new_self(tmp_path) / "session.json").read_text())
    assert data["mode"] == "self" and data["consent"]["recording"] is True


def test_close_self_mode_keeps_takes(tmp_path):
    sdir = _new_self(tmp_path)
    (sdir / "take_01").mkdir()
    assert run("close", sdir).returncode == 0
    assert (sdir / "take_01").exists()


def test_close_delete_flag_removes_takes(tmp_path):
    sdir = _new_self(tmp_path)
    (sdir / "take_01").mkdir()
    assert run("close", sdir, "--delete").returncode == 0
    assert not (sdir / "take_01").exists()


def test_new_twice_is_clean_error(tmp_path):
    run("new", "Me", "--root", tmp_path)
    r = run("new", "Me", "--root", tmp_path)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "already exists" in r.stderr


def test_wrong_session_path_is_clean_error(tmp_path, tone_wav):
    r = run("analyse", tmp_path / "nope", tone_wav())
    assert r.returncode == 1 and "Traceback" not in r.stderr and "session.json" in r.stderr


def test_partial_takes_are_ignored(tmp_path):
    s = _session(tmp_path)
    (s.dir / "take_01.partial").mkdir()
    assert s.takes() == [] and s.next_take_dir().name == "take_01"


def test_features_without_transcript_is_clean(tmp_path):
    take = tmp_path / "take_01"
    take.mkdir()
    (take / "beats.json").write_text("{}")
    r = run("features", take)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "transcript.json" in r.stderr


def test_status_lists_sessions_and_takes(tmp_path):
    sdir = _new_self(tmp_path)
    (sdir / "take_01").mkdir()
    (sdir / "take_01" / "features.json").write_text("{}")
    (sdir / "take_02").mkdir()
    r = run("status", "--root", tmp_path)
    assert r.returncode == 0
    assert "me" in r.stdout and "take_01 (analysed, features)" in r.stdout and "take_02 (analysed)" in r.stdout


def test_status_hint_names_the_storycoach_command(tmp_path):
    r = run("status", "--root", tmp_path)
    assert r.returncode == 0
    assert "Start one with: storycoach new <name> --self" in r.stdout and "python -m" not in r.stdout
    r = run("focus", tmp_path, "x")  # no session.json here
    assert "storycoach new <name>" in r.stderr and "python -m" not in r.stderr
    Session.create(tmp_path, "Ada Founder", 120)
    with pytest.raises(FileExistsError) as e:
        Session.create(tmp_path, "Ada Founder", 120)
    assert "`storycoach status`" in str(e.value) and "python -m" not in str(e.value)


def test_latest_audio_picks_newest(tmp_path):
    import time
    from storycoach.__main__ import latest_audio
    old, new = tmp_path / "a.m4a", tmp_path / "b.m4a"
    old.write_bytes(b"x"); time.sleep(0.05); new.write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    assert latest_audio(tmp_path) == new


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows System.Speech")
def test_solo_two_takes_from_padded_m4a(tmp_path, tts_wav, encode_audio):
    """Self mode: Sound-Recorder-style .m4a with silence padding -> baseline, take 2, compare."""
    import time
    import wave as _wave

    import numpy as np

    from storycoach.audio import to_wav

    rec = tmp_path / "Sound recordings"
    rec.mkdir()
    lines = ["Um, so I started this company because my uncle lost money on unsent invoices.",
             "Then a plumber named Rosa called me at midnight. She could not pay her apprentice."]
    for i, text in enumerate(lines, 1):
        with _wave.open(str(to_wav(tts_wav(text), tmp_path / f"speech_{i}.wav")), "rb") as w:
            speech = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0
        pad = np.zeros(3 * 16000)
        encode_audio(rec / f"Recording ({i}).m4a", np.concatenate([pad, speech, pad]), "aac", rate=16000)
        time.sleep(0.05)
    sdir = _new_self(tmp_path)
    takes = []
    for i in (1, 2):
        os.utime(rec / f"Recording ({i}).m4a")  # make take i the newest
        r = run("analyse", sdir, "--latest", "--from", rec)
        assert r.returncode == 0, r.stderr
        take = Path(r.stdout.strip())
        n = len((take / "words.txt").read_text().strip().splitlines())
        (take / "beats.json").write_text(json.dumps({"beats": [{"label": "other", "start_word": 0, "end_word": n - 1}]}))
        assert run("features", take).returncode == 0
        f = json.loads((take / "features.json").read_text())
        assert f["overall"]["duration_s"] < 9, "silence padding must not count as speech"
        takes.append(take)
    assert [t.name for t in takes] == ["take_01", "take_02"]
    r = run("compare", *takes)
    assert r.returncode == 0, r.stderr
    assert json.loads(Path(r.stdout.strip()).read_text())["content"]["added_sentences"]


def test_focus_set_history_and_clear(tmp_path):
    s = _session(tmp_path)
    assert run("focus", s.dir, "the midnight call should hit hard", "--line", "called me at midnight").returncode == 0
    assert run("focus", s.dir, "slow the ask", "--beat", "ask").returncode == 0
    d = Session.load(s.dir).data
    assert d["focus"] == {"text": "slow the ask", "beat": "ask", "line": None, "set_before_take": 1}
    assert [h["text"] for h in d["focus_history"]] == ["the midnight call should hit hard", "slow the ask"]
    assert run("focus", s.dir, "--clear").returncode == 0
    d = Session.load(s.dir).data
    assert d["focus"] is None and len(d["focus_history"]) == 2


def test_focus_rejects_unknown_beat(tmp_path):
    s = _session(tmp_path)
    r = run("focus", s.dir, "x", "--beat", "climax")
    assert r.returncode != 0 and "climax" in r.stderr


def _write_take(take, loud=70.0):
    take.mkdir()
    words = [{"text": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(20)]
    (take / "transcript.json").write_text(json.dumps({"text": " ".join(w["text"] for w in words), "words": words}))
    n = 1001
    (take / "acoustics.json").write_text(json.dumps({
        "times": [i * 0.01 for i in range(n)], "f0_hz": [180.0] * n,
        "intensity_db": [loud - 4.0 if 5.0 <= i * 0.01 <= 6.5 else loud for i in range(n)]}))
    (take / "beats.json").write_text(json.dumps({
        "beats": [{"label": "hook", "start_word": 0, "end_word": 9}, {"label": "turn", "start_word": 10, "end_word": 19}],
        "key_lines": [{"start_word": 10, "end_word": 12}]}))


def test_features_writes_candidates_with_focus_and_previous_take(tmp_path):
    s = _session(tmp_path)
    _write_take(s.dir / "take_01")
    assert run("features", s.dir / "take_01").returncode == 0
    first = json.loads((s.dir / "take_01" / "features.json").read_text())
    assert first["candidates"]["mode"] == "no_focus" and first["focus"] is None
    run("focus", s.dir, "land the turn", "--line", "w10 w11 w12")
    _write_take(s.dir / "take_02")
    assert run("features", s.dir / "take_02").returncode == 0
    f = json.loads((s.dir / "take_02" / "features.json").read_text())
    assert f["focus"]["text"] == "land the turn"
    assert f["candidates"]["mode"] == "focus" and f["candidates"]["previous_take"] == "take_01"
    assert f["candidates"]["surface"][0]["previous"] is not None


def test_clip_cuts_local_wav(tmp_path, tone_wav):
    import shutil
    import wave
    s = _session(tmp_path)
    take = s.dir / "take_01"
    take.mkdir()
    shutil.copy(tone_wav(secs=3.0), take / "audio.wav")
    r = run("clip", take, "0.5", "1.75")
    assert r.returncode == 0
    out = Path(r.stdout.strip())
    assert out.parent == s.dir / "clips" and out.name == "take_01_0.50-1.75.wav"
    with wave.open(str(out)) as w:
        assert abs(w.getnframes() / w.getframerate() - 1.25) < 0.01


def test_clip_rejects_bad_range(tmp_path, tone_wav):
    import shutil
    s = _session(tmp_path)
    take = s.dir / "take_01"
    take.mkdir()
    shutil.copy(tone_wav(secs=1.0), take / "audio.wav")
    r = run("clip", take, "0.8", "0.2")
    assert r.returncode != 0 and "end" in r.stderr


def test_corrupt_session_json_is_one_line_not_a_traceback(tmp_path):
    s = _session(tmp_path, recording=True)
    (s.dir / "session.json").write_text('{"consent": {"recording": tru\n}', encoding="utf-8")
    r = run("analyse", s.dir, "x.wav")
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    assert "session.json" in r.stderr and "not valid JSON" in r.stderr and "line 1" in r.stderr
    assert len(r.stderr.strip().splitlines()) == 1


def test_list_valued_scenario_is_ignored_not_a_crash():
    from storycoach.scenarios import scenario_for

    assert scenario_for({"scenario": ["pitch"]}) is None
