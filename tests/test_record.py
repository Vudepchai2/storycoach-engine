import json
import os
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from storycoach import record as rec
from storycoach.__main__ import main
from storycoach.session import Session

RATE = 16000


class FakeStream:
    def __init__(self, tone=True, interrupt_on=None, realtime=True):
        self.tone, self.interrupt_on, self.realtime, self.reads, self.pos = tone, interrupt_on, realtime, 0, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, frames):
        self.reads += 1
        if self.interrupt_on == self.reads:
            raise KeyboardInterrupt
        if self.realtime:
            time.sleep(frames / RATE)
        n = np.arange(self.pos, self.pos + frames)
        self.pos += frames
        if not self.tone:
            return np.zeros((frames, 1), dtype=np.int16), False
        return (0.5 * 32767 * np.sin(2 * np.pi * 220 * n / RATE)).astype(np.int16).reshape(-1, 1), False


def _session(tmp_path, **extra):
    s = Session.create(tmp_path / "sessions", "Ada", None, self_mode=True)
    s.data.update(extra)
    s.save()
    return s.dir


def _lock(session, pid, started=None, max_s=60):
    p = rec.lock_path(session)
    p.parent.mkdir(parents=True, exist_ok=True)
    started = started or datetime.now(timezone.utc)
    p.write_text(json.dumps({"pid": pid, "started": started.isoformat(), "max_s": max_s}), encoding="utf-8")
    return p


def test_record_stops_on_stop_file(tmp_path):
    stop = tmp_path / ".stop"
    threading.Timer(0.3, stop.touch).start()
    r = rec.record(tmp_path / "a.wav", stop, 10, stream_factory=FakeStream)
    assert r["stopped_by"] == "stop_file"
    assert 0.2 < r["seconds"] < 1.0
    assert r["peak"] > 0.4


def test_record_stops_at_time_limit(tmp_path):
    r = rec.record(tmp_path / "a.wav", tmp_path / ".stop", 0.5, stream_factory=FakeStream)
    assert r["stopped_by"] == "time_limit"
    assert r["seconds"] == pytest.approx(0.5, abs=0.11)


def test_stop_file_wins_over_time_limit_in_same_block(tmp_path):
    stop = tmp_path / ".stop"
    stop.touch()
    r = rec.record(tmp_path / "a.wav", stop, 0.1, stream_factory=lambda: FakeStream(realtime=False))
    assert r["stopped_by"] == "stop_file"


def test_interrupt_keeps_audio(tmp_path):
    out = tmp_path / "a.wav"
    r = rec.record(out, tmp_path / ".stop", 10, stream_factory=lambda: FakeStream(interrupt_on=4, realtime=False))
    assert r["stopped_by"] == "interrupt"
    with wave.open(str(out)) as w:
        assert w.getframerate() == RATE and w.getnchannels() == 1 and w.getsampwidth() == 2
        assert w.getnframes() / RATE == pytest.approx(0.3, abs=0.01)


def test_silent_recording_prints_permission_hint(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(tone=False, realtime=False))
    assert main(["record", str(session), "--max-seconds", "0.3"]) is None
    out = capsys.readouterr().out
    assert "Microphone" in out
    assert "saved " in out
    assert not rec.lock_path(session).exists() and not rec.stop_path(session).exists()
    assert len(list((session / "recordings").glob("take_*.wav"))) == 1


def test_loud_recording_has_no_hint(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(realtime=False))
    main(["record", str(session), "--max-seconds", "0.3"])
    out = capsys.readouterr().out
    assert "Microphone" not in out and "say \"done\"" in out


def test_stale_lock_is_replaced(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    _lock(session, p.pid)
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(realtime=False))
    main(["record", str(session), "--max-seconds", "0.2"])
    out = capsys.readouterr().out
    assert out.count("replaced a stale recording lock") == 1
    assert not rec.lock_path(session).exists()


def test_old_lock_with_live_pid_is_stale(tmp_path):
    session = _session(tmp_path)
    p = _lock(session, os.getpid(), datetime.now(timezone.utc) - timedelta(seconds=200), max_s=60)
    assert rec.lock_is_stale(p)


def test_live_lock_refuses(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)
    p = _lock(session, os.getpid())
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(realtime=False))
    with pytest.raises(SystemExit) as e:
        main(["record", str(session), "--max-seconds", "0.2"])
    assert e.value.code == 1
    assert p.exists()  # a live recorder's lock is left alone
    assert list((session / "recordings").glob("*.wav")) == []


def test_default_max_uses_target_length(tmp_path, monkeypatch):
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(realtime=False))
    session = _session(tmp_path, target_length_s=[60, 90])
    seen = []
    monkeypatch.setattr(rec, "record", lambda out, stop, max_s, stream_factory=None, rate=16000:
                        seen.append(max_s) or {"path": str(out), "seconds": 0, "stopped_by": "time_limit", "peak": 1})
    main(["record", str(session)])
    session2 = _session(tmp_path / "b", target_length_s=[60, 500])
    main(["record", str(session2)])
    session3 = _session(tmp_path / "c")
    main(["record", str(session3)])
    assert seen == [180, 600, 600]


def test_record_stop_cli(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream())
    t = threading.Thread(target=lambda: main(["record", str(session), "--max-seconds", "30"]))
    t.start()
    deadline = time.time() + 5
    while not rec.lock_path(session).exists() and time.time() < deadline:
        time.sleep(0.05)
    main(["record", "--stop", str(session)])
    t.join(10)
    assert "stopped" in capsys.readouterr().out
    assert not rec.lock_path(session).exists()


def test_stop_with_no_lock_says_so_fast(tmp_path, capsys):
    session = _session(tmp_path)
    t0 = time.monotonic()
    assert main(["record", "--stop", str(session)]) is None
    assert time.monotonic() - t0 < 1
    assert "no recording was running" in capsys.readouterr().out
    assert not rec.stop_path(session).exists()


def test_stop_with_stale_lock_is_fast_and_cleans_up(tmp_path, capsys):
    session = _session(tmp_path)
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    lock = _lock(session, p.pid)
    t0 = time.monotonic()
    main(["record", "--stop", str(session)])
    assert time.monotonic() - t0 < 1
    assert "no recording was running" in capsys.readouterr().out
    assert not lock.exists() and not rec.stop_path(session).exists()


def test_stop_live_lock_removed_says_stopped(tmp_path, capsys):
    session = _session(tmp_path)
    lock = _lock(session, os.getpid())
    threading.Timer(0.5, lock.unlink).start()
    main(["record", "--stop", str(session)])
    assert capsys.readouterr().out.strip() == "stopped"


def test_stop_live_lock_that_stays_keeps_stop_file(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rec, "STOP_WAIT_S", 0.3)
    session = _session(tmp_path)
    lock = _lock(session, os.getpid())
    main(["record", "--stop", str(session)])
    assert "hasn't finished yet" in capsys.readouterr().out
    assert rec.stop_path(session).exists() and lock.exists()


def test_same_second_takes_do_not_overwrite(tmp_path, monkeypatch):
    session = _session(tmp_path)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(rec, "datetime", Frozen)
    a = rec.new_take_path(session)
    a.parent.mkdir(exist_ok=True)
    a.write_bytes(b"first")
    b = rec.new_take_path(session)
    assert b != a and b.name == a.stem + "-2.wav"
    b.write_bytes(b"x")
    assert rec.new_take_path(session).name == a.stem + "-3.wav"


def test_record_never_truncates_an_existing_file(tmp_path):
    out = tmp_path / "a.wav"
    out.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        rec.record(out, tmp_path / ".stop", 0.2, stream_factory=lambda: FakeStream(realtime=False))
    assert out.read_bytes() == b"precious"


def test_no_consent_refuses_and_writes_no_take(tmp_path, monkeypatch):
    session = _session(tmp_path)
    d = json.loads((session / "session.json").read_text(encoding="utf-8"))
    d["consent"]["recording"] = False
    (session / "session.json").write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: FakeStream(realtime=False))
    with pytest.raises(SystemExit) as e:
        main(["record", str(session), "--max-seconds", "0.2"])
    assert e.value.code != 0
    assert not (session / "recordings").exists() or list((session / "recordings").iterdir()) == []


def test_no_microphone_is_friendly_and_cleans_up(tmp_path, monkeypatch, capsys):
    session = _session(tmp_path)

    def broken():
        raise OSError("no default input device")

    monkeypatch.setattr(rec, "STREAM_FACTORY", broken)
    with pytest.raises(SystemExit) as e:
        main(["record", str(session), "--max-seconds", "0.2"])
    assert e.value.code == 1
    assert "Couldn't open a microphone: no default input device" in capsys.readouterr().err
    assert list((session / "recordings").iterdir()) == []  # no empty take, no lock


def test_sigterm_handler_raises_keyboard_interrupt_and_is_restored(tmp_path):
    import signal

    before = signal.getsignal(signal.SIGTERM)
    seen = {}

    class Stream(FakeStream):
        def read(self, frames):
            if self.reads == 1:
                seen["handler"] = signal.getsignal(signal.SIGTERM)
                seen["handler"](signal.SIGTERM, None)  # call it, never send a real signal
            return super().read(frames)

    out = tmp_path / "a.wav"
    r = rec.record(out, tmp_path / ".stop", 10, stream_factory=lambda: Stream(realtime=False))
    assert r["stopped_by"] == "interrupt"
    assert seen["handler"] is not before
    assert signal.getsignal(signal.SIGTERM) is before
    with wave.open(str(out)) as w:
        assert w.getnframes() > 0


def test_lock_is_created_exclusively(tmp_path):
    p = tmp_path / "x" / ".recording.lock"
    rec.write_lock(p, 10)
    with pytest.raises(FileExistsError):
        rec.write_lock(p, 10)


def test_foreign_lock_is_not_removed_by_us(tmp_path, monkeypatch):
    session = _session(tmp_path)
    lock = rec.lock_path(session)

    class Stream(FakeStream):
        def read(self, frames):
            lock.write_text(json.dumps({"pid": os.getpid() + 12345, "started": datetime.now(timezone.utc).isoformat(), "max_s": 9}), encoding="utf-8")
            return super().read(frames)

    monkeypatch.setattr(rec, "STREAM_FACTORY", lambda: Stream(realtime=False))
    main(["record", str(session), "--max-seconds", "0.2"])
    assert lock.exists()


def test_no_test_imports_sounddevice():
    assert "sounddevice" not in sys.modules


def test_latest_prefers_newest_across_folders(tmp_path, monkeypatch, capsys):
    import storycoach.__main__ as m

    session = _session(tmp_path)
    sound = tmp_path / "Sound recordings"
    sound.mkdir()
    (session / "recordings").mkdir(exist_ok=True)
    old = sound / "old.m4a"
    new = session / "recordings" / "take_x.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert m.latest_across([session / "recordings", sound]) == new
    os.utime(old, (3000, 3000))
    assert m.latest_across([session / "recordings", sound]) == old
    assert m.latest_across([session / "recordings", tmp_path / "missing"]) == new


def test_latest_ignores_sound_recordings_off_windows(tmp_path, monkeypatch):
    import storycoach.__main__ as m

    session = _session(tmp_path)
    sound = tmp_path / "Sound recordings"
    sound.mkdir()
    (sound / "a.m4a").write_bytes(b"x")
    monkeypatch.setattr(m, "SOUND_RECORDINGS", sound)
    monkeypatch.setattr(m.sys, "platform", "linux")
    seen = []
    monkeypatch.setattr(m, "latest_across", lambda folders: seen.append(folders) or (_ for _ in ()).throw(FileNotFoundError("none")))
    with pytest.raises(SystemExit):
        main(["analyse", str(session), "--latest"])
    assert seen == [[session / "recordings"]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only code path")
def test_pid_alive_never_signals_on_windows(monkeypatch):
    def boom(*a):
        raise AssertionError("os.kill must not be called on Windows")

    monkeypatch.setattr(os, "kill", boom)
    assert rec._pid_alive(os.getpid()) is True


def test_pid_alive_dead_process():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert rec._pid_alive(p.pid) is False


def test_latest_finds_sound_recordings_redirected_to_onedrive(tmp_path, monkeypatch, capsys):
    import storycoach.__main__ as m

    session = _session(tmp_path)
    home_dir = tmp_path / "home"
    onedrive = home_dir / "OneDrive" / "Documents" / "Sound recordings"
    onedrive.mkdir(parents=True)
    clip = onedrive / "Recording.m4a"
    clip.write_bytes(b"x")
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setattr(m, "SOUND_RECORDINGS", home_dir / "Documents" / "Sound recordings")
    monkeypatch.setattr(m, "_known_documents", lambda: None)
    assert m.latest_across(m.sound_recording_folders()) == clip
    monkeypatch.setattr(m.sys, "platform", "win32")
    seen = []
    monkeypatch.setattr(m, "latest_across", lambda folders: seen.append(folders) or clip)
    monkeypatch.setattr(m, "_analyse_into", lambda audio, take: (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit):
        main(["analyse", str(session), "--latest"])
    assert onedrive in seen[0]


def test_permission_hints_are_ascii():
    for platform in ("darwin", "win32", "linux"):
        assert rec.permission_hint(platform).isascii()
