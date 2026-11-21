import json

import pytest

from storycoach import home, record, usage
from storycoach import setup as setup_mod
from storycoach.__main__ import main
from storycoach.version import __version__


def run(*args):
    try:
        main([str(a) for a in args])
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


@pytest.fixture(autouse=True)
def no_real_audio_or_download(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not download the model")

    monkeypatch.setattr(setup_mod, "DOWNLOAD_MODEL", boom)
    monkeypatch.setattr(setup_mod, "MODEL_CACHED", lambda: False)
    monkeypatch.setattr(setup_mod, "QUERY_INPUT_DEVICES", lambda: "ok")


def test_setup_skip_model_creates_home_and_reports(capsys):
    assert run("setup", "--skip-model", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"home", "model", "mic", "privacy_ack", "version"}
    assert data["model"] == "skipped"
    assert data["mic"] == "ok"
    assert data["privacy_ack"] is False
    assert data["version"] == __version__
    assert (home.data_home() / "sessions").is_dir()
    assert usage.INSTALL_RE.fullmatch(home.read_settings()["install_id"])


def test_ack_privacy_persists(capsys):
    assert run("setup", "--ack-privacy") == 0
    assert capsys.readouterr().out.strip() == "noted"
    ack = home.read_settings()["privacy_ack"]
    assert len(ack) == 10 and ack[4] == "-" and ack[7] == "-"
    assert run("setup", "--skip-model", "--json") == 0
    assert json.loads(capsys.readouterr().out)["privacy_ack"] is True


def test_setup_reports_portaudio_missing(capsys, monkeypatch):
    def missing():
        raise OSError("PortAudio library not found")

    monkeypatch.setattr(setup_mod, "QUERY_INPUT_DEVICES", missing)
    assert run("setup", "--skip-model", "--json") == 0
    assert json.loads(capsys.readouterr().out)["mic"] == "portaudio_missing"
    monkeypatch.setattr(setup_mod.sys, "platform", "linux")
    assert run("setup", "--skip-model") == 0
    out = capsys.readouterr().out
    assert "mic: PortAudio missing" in out
    assert record.PORTAUDIO_HINT in out


def _snapshot(tmp_path, model_bin=True, config=True):
    d = tmp_path / "snap"
    d.mkdir()
    if config:
        (d / "config.json").write_text("{}", encoding="utf-8")
    if model_bin:
        (d / "model.bin").write_bytes(b"x")
    return d


def test_model_complete_needs_model_bin_and_config(tmp_path):
    assert setup_mod._model_complete(_snapshot(tmp_path))
    assert not setup_mod._model_complete(tmp_path / "nope")


def test_model_complete_rejects_partial_snapshot(tmp_path):
    d = _snapshot(tmp_path, model_bin=False)
    assert not setup_mod._model_complete(d)
    (d / "model.bin").write_bytes(b"")
    assert not setup_mod._model_complete(d)


def test_partial_cache_reports_missing(tmp_path, capsys, monkeypatch):
    snap = _snapshot(tmp_path, model_bin=False)
    monkeypatch.setattr(setup_mod, "MODEL_CACHED", lambda: snap)

    def offline(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(setup_mod, "DOWNLOAD_MODEL", offline)
    assert run("setup", "--json") == 0
    assert json.loads(capsys.readouterr().out)["model"] == "missing"
    assert run("setup") == 0
    assert "model: missing" in capsys.readouterr().out


def test_complete_cache_reports_ok(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(setup_mod, "MODEL_CACHED", lambda: _snapshot(tmp_path))
    assert run("setup", "--json") == 0
    assert json.loads(capsys.readouterr().out)["model"] == "ok"


def test_unwritable_home_is_a_clean_error(capsys, monkeypatch):
    def denied():
        raise PermissionError("denied")

    monkeypatch.setattr(home, "ensure_home", denied)
    assert run("setup", "--skip-model") == 1
    err = capsys.readouterr().err
    assert str(home.data_home()) in err and "Traceback" not in err


def test_mic_hook_runtime_error_is_none(capsys, monkeypatch):
    def broken():
        raise RuntimeError("driver")

    monkeypatch.setattr(setup_mod, "QUERY_INPUT_DEVICES", broken)
    assert run("setup", "--skip-model", "--json") == 0
    assert json.loads(capsys.readouterr().out)["mic"] == "none"


def test_default_query_driver_error_is_none(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("sounddevice")

    class PortAudioError(Exception):
        pass

    def query(kind=None):
        raise RuntimeError("driver")

    fake.PortAudioError, fake.query_devices = PortAudioError, query
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert setup_mod._default_query_input_devices() == "none"


def test_damaged_settings_not_reported_as_usage_off(capsys):
    home.ensure_home()
    home.settings_path().write_text("{not json", encoding="utf-8")
    assert run("setup", "--skip-model") == 0
    out = capsys.readouterr().out
    assert "usage stats: off" not in out
    assert "settings: unreadable" in out
    assert "next:" in out


def test_usage_explicitly_off_is_reported(capsys):
    usage.set_enabled(False)
    assert run("setup", "--skip-model") == 0
    assert "usage stats: off" in capsys.readouterr().out


def test_ack_with_flags_prints_noted_first(capsys):
    assert run("setup", "--ack-privacy", "--skip-model") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "noted"
    assert "privacy note: ok" in out


def test_ack_with_json_keeps_stdout_json(capsys):
    assert run("setup", "--ack-privacy", "--skip-model", "--json") == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["privacy_ack"] is True
    assert "noted" in cap.err
