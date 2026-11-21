import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAID = {"kind": "said", "ref": "sessions/a"}


def run(*args, cwd=ROOT, env=None, text=True):
    return subprocess.run([sys.executable, "-m", "storycoach", *map(str, args)], capture_output=True, text=text,
                          cwd=cwd, env={**os.environ, "PYTHONPATH": str(ROOT), **(env or {})})


def _batch(tmp_path, items, name="batch.json"):
    f = tmp_path / name
    f.write_text(json.dumps({"source": SAID, "items": items}, ensure_ascii=False), encoding="utf-8")
    return f


def _bank(tmp_path, items=None, name="Ana"):
    r = run("memory", "init", name, "--root", tmp_path / "people")
    assert r.returncode == 0, r.stderr
    bank = Path(r.stdout.strip())
    if items:
        r = run("memory", "retain", bank, _batch(tmp_path, items))
        assert r.returncode == 0, r.stderr
    return bank


MOMENT = {"type": "moment", "title": "The night shift", "what_happened": "She fixed the line."}


def test_init_retain_brief_roundtrip(tmp_path):
    bank = _bank(tmp_path)
    assert (bank / "person.json").exists()
    r = run("memory", "retain", bank, _batch(tmp_path, [MOMENT]))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["added"][0]["id"] == "m1"
    r = run("memory", "brief", bank)
    assert r.returncode == 0 and "The night shift" in r.stdout
    assert (bank / "pages" / "profile.md").exists()


def test_retain_bad_batch_exit_1_lists_errors(tmp_path):
    bank = _bank(tmp_path)
    r = run("memory", "retain", bank, _batch(tmp_path, [{"type": "bogus"}, {"type": "nope"}]))
    assert r.returncode == 1
    assert len(r.stderr.strip().splitlines()) == 2
    log = bank / "log.jsonl"
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_retain_accepts_bom_and_reports_bad_json(tmp_path):
    bank = _bank(tmp_path)
    f = tmp_path / "bom.json"
    f.write_text(json.dumps({"source": SAID, "items": [MOMENT]}), encoding="utf-8-sig")
    assert run("memory", "retain", bank, f).returncode == 0
    f.write_text("{nope", encoding="utf-8")
    r = run("memory", "retain", bank, f)
    assert r.returncode == 1 and "batch file is not valid JSON" in r.stderr


def test_brief_prints_unicode_on_any_console(tmp_path):
    title = "René’s call"
    bank = _bank(tmp_path, [{**MOMENT, "title": title}])
    r = run("memory", "brief", bank, env={"PYTHONIOENCODING": "cp1252"}, text=False)
    assert r.returncode == 0, r.stderr
    assert title.encode("utf-8") in r.stdout


def test_missing_bank_is_clean_error(tmp_path):
    r = run("memory", "brief", tmp_path / "nobody")
    assert r.returncode == 1 and "no memory bank" in r.stderr


def test_new_self_creates_bank_and_occasion(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    r = run("new", "Sam", "--self", "--occasion", "GRANT application", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    data = json.loads((S / "sam-grant-application" / "session.json").read_text(encoding="utf-8"))
    assert data["person"] == "sam" and data["occasion_id"] == "oc1"
    assert data["occasion"] == "GRANT application" and data["consent"]["memory"] is True
    assert (P / "sam" / "person.json").exists()
    s = run("status", "--root", S)
    assert "  person: sam" in s.stdout


def test_new_operator_without_memory_has_no_bank(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    r = run("new", "Ada", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    data = json.loads((S / "ada" / "session.json").read_text(encoding="utf-8"))
    assert "person" not in data and not P.exists()
    assert "person:" not in run("status", "--root", S).stdout


def test_second_occasion_reuses_bank(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    run("new", "Sam", "--self", "--occasion", "One", "--root", S, "--people-root", P)
    r = run("new", "Sam", "--self", "--occasion", "Two", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    data = json.loads((S / "sam-two" / "session.json").read_text(encoding="utf-8"))
    assert data["occasion_id"] == "oc2"
    assert [p.name for p in P.iterdir()] == ["sam"]


def test_accented_name_maps_to_one_bank(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    run("new", "René", "--self", "--occasion", "One", "--root", S, "--people-root", P)
    r = run("new", "Rene", "--self", "--occasion", "Two", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    assert len(list(P.iterdir())) == 1


def test_delete_requires_yes(tmp_path):
    bank = _bank(tmp_path, [MOMENT])
    r = run("memory", "delete", bank)
    assert r.returncode == 2
    assert f"Refusing to delete {bank} without --yes. This removes every memory for this person and cannot be undone." in r.stderr
    assert bank.exists()
    assert run("memory", "delete", bank, "--yes").returncode == 0
    assert not bank.exists()


def test_link_existing_session(tmp_path):
    bank = _bank(tmp_path)
    S = tmp_path / "S"
    run("new", "Ana", "--root", S)
    sd = S / "ana"
    r = run("memory", "link", sd, bank)
    assert r.returncode == 0, r.stderr
    assert json.loads((sd / "session.json").read_text(encoding="utf-8"))["person"] == "ana"
    assert run("memory", "link", tmp_path / "nope", bank).returncode == 1


def test_forget_retracts(tmp_path):
    bank = _bank(tmp_path, [MOMENT])
    n = len((bank / "log.jsonl").read_text(encoding="utf-8").splitlines())
    assert run("memory", "forget", bank, "m1").returncode == 2  # --reason required by argparse
    r = run("memory", "forget", bank, "m1", "--reason", "she asked")
    assert r.returncode == 0, r.stderr
    assert len((bank / "log.jsonl").read_text(encoding="utf-8").splitlines()) == n + 1
    r = run("memory", "recall", bank, "--type", "moment")
    assert json.loads(r.stdout) == []
    assert run("memory", "forget", bank, "m1", "--reason", "again").returncode == 1


def test_import_recall_gaps_pages(tmp_path):
    bank = _bank(tmp_path)
    doc = tmp_path / "cv.txt"
    doc.write_text("hello", encoding="utf-8")
    r = run("memory", "import", bank, doc)
    assert r.returncode == 0 and r.stdout.strip() == "s1 new"
    assert run("memory", "import", bank, doc).stdout.strip() == "s1 already imported"
    assert isinstance(json.loads(run("memory", "gaps", bank).stdout), list)
    assert run("memory", "pages", bank).returncode == 0


def test_new_bad_founder_name_is_clean_error_and_leaves_no_session(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    r = run("new", "!!!", "--self", "--root", S, "--people-root", P)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "cannot make a bank name" in r.stderr
    assert not S.exists() or not list(S.iterdir())


def test_new_failure_after_session_create_removes_that_session(tmp_path, monkeypatch):
    import pytest
    from storycoach.__main__ import main
    from storycoach.memory import cli
    from storycoach.memory.retain import BatchError

    def boom(store, batch):
        raise BatchError(["nope"])

    monkeypatch.setattr(cli, "retain", boom)
    S, P = tmp_path / "S", tmp_path / "P"
    with pytest.raises(SystemExit) as e:
        main(["new", "Sam", "--self", "--root", str(S), "--people-root", str(P)])
    assert e.value.code == 1
    assert not (S / "sam").exists()
    monkeypatch.undo()
    assert run("new", "Sam", "--self", "--root", S, "--people-root", P).returncode == 0


def test_default_people_root_honours_env(tmp_path, monkeypatch):
    from storycoach.home import people_dir

    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    assert people_dir() == tmp_path / "h" / "people"


def _log_lines(bank):
    log = bank / "log.jsonl"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_new_never_deletes_a_folder_it_did_not_create(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    (S / "sam-deck").mkdir(parents=True)
    (S / "sam-deck" / "my-notes.txt").write_text("mine", encoding="utf-8")
    (P / "sam").mkdir(parents=True)  # a folder that is not a bank: the bank can't be used
    r = run("new", "Sam", "--self", "--occasion", "deck", "--root", S, "--people-root", P)
    assert r.returncode == 1 and "Traceback" not in r.stderr and "not a memory bank" in r.stderr
    assert [p.name for p in (S / "sam-deck").iterdir()] == ["my-notes.txt"]
    assert (S / "sam-deck" / "my-notes.txt").read_text(encoding="utf-8") == "mine"
    assert list((P / "sam").iterdir()) == []


def test_new_failure_after_create_keeps_files_it_did_not_write(tmp_path, monkeypatch):
    import pytest
    from storycoach.__main__ import main
    from storycoach.memory import cli

    S, P = tmp_path / "S", tmp_path / "P"
    (S / "sam").mkdir(parents=True)
    (S / "sam" / "my-notes.txt").write_text("mine", encoding="utf-8")
    for exc in (KeyboardInterrupt, OSError):
        def boom(store, batch, exc=exc):
            raise exc("stop")

        monkeypatch.setattr(cli, "retain", boom)
        with pytest.raises(exc):
            main(["new", "Sam", "--self", "--root", str(S), "--people-root", str(P)])
        assert [p.name for p in (S / "sam").iterdir()] == ["my-notes.txt"]
        assert not P.exists() or list(P.iterdir()) == []  # the bank this call made is undone too


def test_operator_reuse_of_a_bank_needs_person(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    r = run("new", "Sam", "--memory", "--occasion", "Pitch A", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    n = len(_log_lines(P / "sam"))
    r = run("new", "Sam", "--memory", "--occasion", "Other Sam app", "--root", S, "--people-root", P)
    assert r.returncode == 1 and "Traceback" not in r.stderr
    assert "--person sam" in r.stderr and "distinguishing name" in r.stderr
    assert not (S / "sam-other-sam-app").exists() and len(_log_lines(P / "sam")) == n
    r = run("new", "Sam", "--person", "sam", "--occasion", "Pitch B", "--root", S, "--people-root", P)
    assert r.returncode == 0, r.stderr
    assert "reusing memory bank" in r.stderr.lower() and "1 record" in r.stderr
    data = json.loads((S / "sam-pitch-b" / "session.json").read_text(encoding="utf-8"))
    assert data["person"] == "sam" and data["occasion_id"] == "oc2"
    r = run("new", "Sue", "--person", "nobody", "--root", S, "--people-root", P)
    assert r.returncode == 1 and "no memory bank" in r.stderr and not (S / "sue").exists()


def test_self_mode_reuses_its_bank_with_a_notice(tmp_path):
    S, P = tmp_path / "S", tmp_path / "P"
    assert "reusing" not in run("new", "Sam", "--self", "--occasion", "One", "--root", S,
                                "--people-root", P).stderr.lower()
    r = run("new", "Sam", "--self", "--occasion", "Two", "--root", S, "--people-root", P)
    assert r.returncode == 0 and "reusing memory bank" in r.stderr.lower() and "(1 record)" in r.stderr


def test_new_records_the_session_ref_in_canonical_form(tmp_path, monkeypatch):
    from storycoach.__main__ import main
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path))
    main(["new", "Sam", "--self", "--occasion", "deck", "--root", str(tmp_path / "sessions"),
          "--people-root", str(tmp_path / "people")])
    event = json.loads(_log_lines(tmp_path / "people" / "sam")[0])
    assert event["source"]["ref"] == "sessions/sam-deck"
    assert event["data"]["session"] == "sessions/sam-deck"


def test_page_failure_after_retain_is_a_warning_and_the_report_prints(tmp_path):
    bank = _bank(tmp_path)
    (bank / "pages" / "profile.md.tmp").mkdir()  # makes writing that page fail
    r = run("memory", "retain", bank, _batch(tmp_path, [MOMENT]))
    assert r.returncode == 0 and "Traceback" not in r.stderr
    assert json.loads(r.stdout)["added"][0]["id"] == "m1"
    assert "pages were not updated" in r.stderr
    assert len(_log_lines(bank)) == 1
