import csv

from storycoach.blind import make_blind_set, tally_blind


def test_blind_order_randomised_and_tallied(tmp_path, tone_wav):
    a, b = tmp_path / "take_01", tmp_path / "take_03"
    for d, f in ((a, 200), (b, 300)):
        d.mkdir()
        tone_wav(freq=f).replace(d / "audio.wav")
    out = make_blind_set(a, b, tmp_path / "blind", listeners=6, seed=1)
    key = list(csv.DictReader(open(out / "key.csv")))
    assert {row["A_is"] for row in key} == {"baseline", "final"}
    with open(out / "results.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["listener", "preferred"])
        for row in key:
            w.writerow([row["listener"], "A" if row["A_is"] == "final" else "B"])
    assert tally_blind(out) == {"final_preferred": 6, "baseline_preferred": 0, "n": 6}


def test_rerun_does_not_wipe_answers(tmp_path, tone_wav):
    import pytest
    a, b = tmp_path / "take_01", tmp_path / "take_02"
    for d in (a, b):
        d.mkdir()
        tone_wav().replace(d / "audio.wav") if not (d / "audio.wav").exists() else None
    (b / "audio.wav").write_bytes((a / "audio.wav").read_bytes()) if not (b / "audio.wav").exists() else None
    out = make_blind_set(a, b, tmp_path / "blind", listeners=2, seed=0)
    with open(out / "results.csv", "a", newline="") as fh:
        fh.write("listener_01,A\n")
    with pytest.raises(FileExistsError):
        make_blind_set(a, b, tmp_path / "blind", listeners=4, seed=0)
    assert "listener_01,A" in (out / "results.csv").read_text()


def test_tally_counts_each_listener_once(tmp_path, tone_wav):
    a, b = tmp_path / "take_01", tmp_path / "take_02"
    for d in (a, b):
        d.mkdir()
        (d / "audio.wav").write_bytes(tone_wav().read_bytes())
    out = make_blind_set(a, b, tmp_path / "blind", listeners=2, seed=0)
    key = list(csv.DictReader(open(out / "key.csv")))
    final_letter = "A" if key[0]["A_is"] == "final" else "B"
    with open(out / "results.csv", "a", newline="") as fh:
        fh.write(f"{key[0]['listener']},{final_letter}\n{key[0]['listener']},{final_letter}\n")
    assert tally_blind(out)["n"] == 1
