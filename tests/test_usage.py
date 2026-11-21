import json
import re
from pathlib import Path

import pytest

from storycoach import home, usage
from storycoach.__main__ import main
from storycoach.scenarios import SCENARIOS


def run(*args):
    """Run the CLI in-process; return the exit code."""
    try:
        main([str(a) for a in args])
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


def events():
    f = home.usage_dir() / "events.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]


def test_usage_rejects_free_text(capsys):
    assert run("usage", "log", "question_asked", "phase=what made you care") == 1
    assert not (home.usage_dir() / "events.jsonl").exists()
    assert run("usage", "log", "question_asked", "phase=") == 1
    assert events() == []


def test_usage_rejects_unknown_field(capsys):
    assert run("usage", "log", "question_asked", "phase=capture", "note=hi") == 1
    assert run("usage", "log", "question_asked") == 1  # missing field
    assert run("usage", "log", "nonsense", "phase=capture") == 1
    assert events() == []


def test_validate_types():
    with pytest.raises(ValueError):
        usage.validate("take_analysed", {"take": True, "seconds": 1.0, "focus_set": False})
    with pytest.raises(ValueError):
        usage.validate("take_analysed", {"take": 1, "seconds": True, "focus_set": False})
    with pytest.raises(ValueError):
        usage.validate("take_analysed", {"take": 1, "seconds": 2.0, "focus_set": 1})
    usage.validate("take_analysed", {"take": 1, "seconds": 2, "focus_set": False})
    usage.validate("command", {"name": "version", "seconds": 0.1, "ok": False, "error": None})
    with pytest.raises(ValueError):
        usage.validate("command", {"name": "version", "seconds": 0.1, "ok": False, "error": "my/path"})
    with pytest.raises(ValueError):
        usage.validate("command", {"name": "not-a-command", "seconds": 0.1, "ok": True, "error": None})


def test_usage_off_writes_nothing():
    assert run("usage", "off") == 0
    assert usage.enabled() is False
    assert usage.log("question_asked", phase="capture") is False
    assert run("usage", "log", "question_asked", "phase=capture") == 0
    assert run("version") == 0
    assert not (home.usage_dir() / "events.jsonl").exists()
    assert json.loads(home.settings_path().read_text(encoding="utf-8"))["usage"] is False
    assert run("usage", "on") == 0
    assert usage.log("question_asked", phase="capture") is True


def test_off_does_not_create_install_id():
    usage.set_enabled(False)
    s = json.loads(home.settings_path().read_text(encoding="utf-8"))
    assert "install_id" not in s
    run("version")
    assert "install_id" not in json.loads(home.settings_path().read_text(encoding="utf-8"))


def test_settings_keys_preserved():
    home.data_home().mkdir(parents=True, exist_ok=True)
    home.settings_path().write_text(json.dumps({"other": 5}), encoding="utf-8")
    usage.set_enabled(False)
    usage.set_enabled(True)
    usage.install_id()
    s = json.loads(home.settings_path().read_text(encoding="utf-8"))
    assert s["other"] == 5 and s["usage"] is True and "install_id" in s


def test_every_command_logs_a_command_event(tmp_path):
    assert run("status", "--root", tmp_path) == 0
    ev = events()
    assert len(ev) == 1
    assert ev[0]["type"] == "command" and ev[0]["name"] == "status" and ev[0]["ok"] is True
    assert ev[0]["error"] is None and isinstance(ev[0]["seconds"], float)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", ev[0]["at"])


def test_memory_subcommand_name(tmp_path):
    assert run("memory", "init", "Ada", "--root", tmp_path / "people") == 0
    assert [e["name"] for e in events()] == ["memory init"]


def test_failed_command_logs_error_class_not_message(tmp_path):
    missing = tmp_path / "secret_person_dir"
    assert run("analyse", missing, "x.wav") == 1
    ev = events()
    assert len(ev) == 1 and ev[0]["ok"] is False and ev[0]["error"] == "FileNotFoundError"
    assert "secret_person_dir" not in (home.usage_dir() / "events.jsonl").read_text(encoding="utf-8")


def test_consent_exit_logs_systemexit(tmp_path):
    assert run("new", "Ada", "--root", tmp_path) == 0
    sess = next(tmp_path.iterdir())
    assert run("analyse", sess, "x.wav") == 2
    last = events()[-1]
    assert last["name"] == "analyse" and last["ok"] is False and last["error"] == "SystemExit"


def test_new_logs_session_started(tmp_path):
    run("new", "Ada", "--root", tmp_path, "--self", "--scenario", "pitch", "--people-root", tmp_path / "p")
    run("new", "Bob", "--root", tmp_path)
    started = [e for e in events() if e["type"] == "session_started"]
    assert [(e["scenario"], e["mode"]) for e in started] == [("pitch", "self"), ("none", "operator")]


def test_logging_failure_never_fails_command(monkeypatch, capsys, tmp_path):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(usage, "log", boom)
    assert run("status", "--root", tmp_path) == 0
    assert "usage" in capsys.readouterr().err.lower()


def test_self_check_by_take():
    for ans, take in [("yes", 1), ("no", 1), ("yes", 2)]:
        assert run("usage", "log", "self_check", f"answer={ans}", f"take={take}") == 0
    s = usage.summary()
    assert s["self_check"] == {"yes": 2, "no": 1}
    assert s["self_check_by_take"] == {"1": {"yes": 1, "no": 1}, "2": {"yes": 1}}


def test_summary_means():
    usage.log("session_started", scenario="job", mode="self")
    usage.log("session_started", scenario="job", mode="operator")
    for t in (1, 2, 3):
        usage.log("take_analysed", take=t, seconds=10.5, focus_set=False)
    usage.log("question_asked", phase="capture")
    s = usage.summary()
    assert s["sessions_by_scenario"] == {"job": 2}
    assert s["takes_per_session"] == 1.5 and s["questions_per_session"] == 0.5
    assert s["questions_by_phase"] == {"capture": 1}
    assert s["events"] == 6


def test_export_contains_only_allowed_strings(tmp_path):
    usage.log("session_started", scenario="speech", mode="self")
    usage.log("question_asked", phase="shape")
    usage.log("self_check", answer="partly", take=2)
    run("version")
    run("analyse", tmp_path / "nowhere_private", "a.wav")
    out = tmp_path / "export.json"
    assert run("usage", "export", "--out", out) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    allowed = (usage.PHASES | usage.SELF_CHECK | usage.MODES | usage.SCENARIO_NAMES | usage.COMMAND_NAMES
               | usage.ERROR_CLASSES | {usage.install_id()})
    spec_keys = {"sessions_by_scenario", "takes_per_session", "questions_by_phase", "questions_per_session",
                 "self_check", "self_check_by_take", "commands", "first_event", "last_event", "events", "install",
                 "runs", "failed"}
    key_ok = allowed | spec_keys

    def walk(v, key=None):
        if isinstance(v, dict):
            for k, x in v.items():
                assert k in key_ok or k.isdigit(), k
                walk(x, k)
        elif isinstance(v, str):
            assert v in allowed or re.fullmatch(r"\d{4}-\d\d-\d\d", v), v
    walk(data)
    assert "nowhere_private" not in out.read_text(encoding="utf-8")
    assert set(SCENARIOS) <= usage.SCENARIO_NAMES


def test_export_stdout_default_writes_no_file(tmp_path, capsys):
    capsys.readouterr()
    assert run("usage", "export") == 0
    assert json.loads(capsys.readouterr().out)["events"] == 0
    assert run("usage", "show") == 0
    assert "events" in capsys.readouterr().out


def test_install_id_is_random_and_stable(tmp_path, monkeypatch):
    a = usage.install_id()
    assert re.fullmatch(r"[0-9a-f]{32}", a) and usage.install_id() == a
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "other"))
    assert usage.install_id() != a


def test_command_names_derived_from_parser():
    names = usage.COMMAND_NAMES
    assert {"new", "analyse", "features", "version", "usage", "memory init", "memory recall"} <= names
    assert "memory" not in names


def test_file_is_ascii_lines_lf():
    usage.log("question_asked", phase="recall")
    raw = (home.usage_dir() / "events.jsonl").read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    raw.decode("ascii")


def test_analyse_logs_take_analysed(tmp_path, tone_wav, monkeypatch):
    from types import SimpleNamespace
    from storycoach import __main__ as m

    class T:
        words = []
        def to_dict(self): return {"text": "", "words": []}
    monkeypatch.setattr("storycoach.transcribe.transcribe", lambda wav: T())
    monkeypatch.setattr("storycoach.acoustics.extract_acoustics",
                        lambda wav: SimpleNamespace(to_dict=lambda: {}))
    assert run("new", "Ada", "--root", tmp_path, "--self", "--people-root", tmp_path / "p") == 0
    sess = next(p for p in tmp_path.iterdir() if p.name != "p")
    assert run("analyse", sess, tone_wav(secs=2.0)) == 0
    t = [e for e in events() if e["type"] == "take_analysed"]
    assert len(t) == 1 and t[0]["take"] == 1 and abs(t[0]["seconds"] - 2.0) < 0.1 and t[0]["focus_set"] is False


# ---- fix round 1 ----
GOOD = {"type": "question_asked", "at": "2026-01-02T03:04:05Z", "install": "a" * 32, "phase": "capture"}


def test_poisoned_install_id_never_reaches_file_or_export(capsys):
    home.data_home().mkdir(parents=True, exist_ok=True)
    home.settings_path().write_text(json.dumps({"install_id": "C:/Users/me/secret story", "keep": 1}), encoding="utf-8")
    assert usage.log("question_asked", phase="capture") is True
    assert run("usage", "export") == 0
    out = capsys.readouterr().out
    raw = (home.usage_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert "secret" not in raw and "secret" not in out
    s = json.loads(home.settings_path().read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{32}", s["install_id"]) and s["keep"] == 1


def _write_events(lines):
    home.usage_dir().mkdir(parents=True, exist_ok=True)
    (home.usage_dir() / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bad_lines_are_dropped_on_read(capsys):
    bad = [
        json.dumps({**GOOD, "phase": "what made you care about it"}),
        json.dumps({k: v for k, v in GOOD.items() if k != "phase"}),
        "garbage {not json",
        json.dumps(["a", "list"]),
        json.dumps({**GOOD, "at": "my private note"}),
        json.dumps({**GOOD, "install": "secret-install"}),
        json.dumps({**GOOD, "extra": "x"}),
        json.dumps({"type": "self_check", "at": GOOD["at"], "install": GOOD["install"], "answer": "yes", "take": "7 free text"}),
        json.dumps({"type": "command", "at": GOOD["at"], "install": GOOD["install"], "name": "/etc/passwd",
                    "seconds": 1.0, "ok": True, "error": None}),
    ]
    _write_events(bad + [json.dumps(GOOD)])
    assert run("usage", "show") == 0
    capsys.readouterr()
    assert run("usage", "export") == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["events"] == 1 and data["questions_by_phase"] == {"capture": 1}
    assert data["first_event"] == "2026-01-02" and data["commands"] == {} and data["self_check"] == {}
    for s in ("what made", "private", "secret", "passwd", "free text"):
        assert s not in out


def test_numeric_bounds():
    for take in (0, -1, 10001, 10 ** 4000):
        with pytest.raises(ValueError):
            usage.validate("self_check", {"answer": "yes", "take": take})
    usage.validate("self_check", {"answer": "yes", "take": 1})
    usage.validate("self_check", {"answer": "yes", "take": 10000})
    for sec in (-0.1, 1e6 + 1, float("nan"), 10 ** 4000):
        with pytest.raises(ValueError):
            usage.validate("take_analysed", {"take": 1, "seconds": sec, "focus_set": True})
    usage.validate("take_analysed", {"take": 1, "seconds": 0, "focus_set": True})
    usage.validate("take_analysed", {"take": 1, "seconds": 1e6, "focus_set": True})
    assert run("usage", "log", "self_check", "answer=yes", "take=" + "9" * 4000) == 1
    assert events() == []


def test_unreadable_settings_raise_and_stay_untouched(monkeypatch):
    home.data_home().mkdir(parents=True, exist_ok=True)
    p = home.settings_path()
    p.write_text(json.dumps({"usage": False, "x": 1}), encoding="utf-8")
    before = p.read_bytes()
    real = Path.read_text

    def locked(self, *a, **k):
        if self.name == "settings.json":
            raise PermissionError("locked")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", locked)
    with pytest.raises(OSError):
        home.update_settings(usage=True)
    assert usage.enabled() is False  # (d) unreadable never reverts an opt-out
    assert usage.log("question_asked", phase="capture") is False
    monkeypatch.setattr(Path, "read_text", real)
    assert p.read_bytes() == before
    assert not list(p.parent.glob("settings.json.*"))


@pytest.mark.parametrize("content", ["{}", '{"a": 1}'])
def test_valid_object_is_not_damaged(content):
    home.data_home().mkdir(parents=True, exist_ok=True)
    home.settings_path().write_text(content, encoding="utf-8")
    home.update_settings(usage=True)
    assert not list(home.data_home().glob("settings.json.damaged*"))
    assert usage.enabled() is True


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", '"str"', ""])
def test_damaged_settings_move_aside_uniquely_and_disable(content):
    home.data_home().mkdir(parents=True, exist_ok=True)
    p = home.settings_path()
    p.write_text(content, encoding="utf-8")
    assert usage.enabled() is False  # (d)
    home.update_settings(usage=True)
    first = list(home.data_home().glob("settings.json.damaged*"))
    assert len(first) == 1 and first[0].read_text(encoding="utf-8") == content
    p.write_text("{second damage", encoding="utf-8")
    home.update_settings(usage=True)
    both = list(home.data_home().glob("settings.json.damaged*"))
    assert len(both) == 2 and first[0].read_text(encoding="utf-8") == content
    assert json.loads(p.read_text(encoding="utf-8")) == {"usage": True}


def test_version_and_commands_leave_no_trace(tmp_path, monkeypatch):
    empty = tmp_path / "fresh_home"
    monkeypatch.setenv("STORYCOACH_HOME", str(empty))
    assert run("version") == 0
    assert run("commands", "--json") == 0
    assert not empty.exists()


def test_usage_show_and_export_do_not_create_install_id(tmp_path, capsys):
    assert run("usage", "show") == 0
    assert run("usage", "export", "--out", tmp_path / "out.json") == 0
    assert usage.summary()["install"] is None
    assert not home.settings_path().exists() or "install_id" not in home.read_settings()
