import subprocess
import sys
from pathlib import Path

from storycoach import home


def run(*args):
    return subprocess.run([sys.executable, "-m", "storycoach", *map(str, args)],
                          capture_output=True, text=True, encoding="utf-8")


def test_default_home_is_storytellingcoach_in_user_home(monkeypatch):
    monkeypatch.delenv("STORYCOACH_HOME", raising=False)
    assert home.data_home() == Path.home() / "StorytellingCoach"


def test_env_overrides_home(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    assert home.data_home() == tmp_path / "h"
    assert home.sessions_dir() == tmp_path / "h" / "sessions"
    assert home.settings_path() == tmp_path / "h" / "settings.json"
    assert not (tmp_path / "h").exists()  # the getters create nothing


def test_ensure_home_creates_folders_and_readme(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    assert home.ensure_home() == tmp_path / "h"
    for name in ("sessions", "people", "usage", "reference", "practice"):
        assert (tmp_path / "h" / name).is_dir()
    readme = (tmp_path / "h" / "README.txt").read_text(encoding="utf-8")
    assert "Nothing in this folder is uploaded by the coach." in readme
    (tmp_path / "h" / "README.txt").write_text("mine", encoding="utf-8")
    home.ensure_home()
    assert (tmp_path / "h" / "README.txt").read_text(encoding="utf-8") == "mine"


def test_tests_never_see_the_real_home():
    assert not home.data_home().is_relative_to(Path.home() / "StorytellingCoach")


def test_new_and_memory_default_to_home(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    r = run("new", "Sam", "--self")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "h" / "sessions" / "sam" / "session.json").exists()
    assert (tmp_path / "h" / "people" / "sam" / "person.json").exists()


def _legacy(tmp_path):
    src = tmp_path / "legacy"
    (src / "sessions" / "a").mkdir(parents=True)
    (src / "sessions" / "a" / "session.json").write_bytes(b'{"x": 1}\r\n')
    (src / "people" / "p").mkdir(parents=True)
    (src / "people" / "p" / "person.json").write_bytes(b"{}")
    return src


def test_import_legacy_copies_and_leaves_originals(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    src = _legacy(tmp_path)
    r = run("import-legacy", src)
    assert r.returncode == 0, r.stderr
    assert "copied 2, skipped 0" in r.stdout
    assert (tmp_path / "h" / "sessions" / "a" / "session.json").read_bytes() == b'{"x": 1}\r\n'
    assert (src / "sessions" / "a" / "session.json").read_bytes() == b'{"x": 1}\r\n'
    assert (src / "people" / "p" / "person.json").exists()


def test_import_legacy_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    src = _legacy(tmp_path)
    run("import-legacy", src)
    sentinel = tmp_path / "h" / "sessions" / "a" / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    r = run("import-legacy", src)
    assert r.returncode == 0
    assert "skipped a (already in" in r.stdout and "copied 0, skipped 2" in r.stdout
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_import_legacy_failure_leaves_no_partial_copy_and_can_retry(tmp_path, monkeypatch, capsys):
    import shutil

    from storycoach.__main__ import main

    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    src = _legacy(tmp_path)
    real = shutil.copytree

    def boom(s, d, *a, **k):
        Path(d).mkdir(parents=True)
        (Path(d) / "half.txt").write_text("partial", encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copytree", boom)
    try:
        main(["import-legacy", str(src)])
        raise AssertionError("expected exit")
    except SystemExit as e:
        assert e.code == 1
    err = capsys.readouterr().err
    assert "disk full" in err and "Traceback" not in err
    assert not (tmp_path / "h" / "sessions" / "a").exists()
    assert not list((tmp_path / "h").rglob("*.importing-*"))
    assert (src / "sessions" / "a" / "session.json").read_bytes() == b'{"x": 1}\r\n'
    monkeypatch.setattr(shutil, "copytree", real)
    main(["import-legacy", str(src)])
    assert "copied 2, skipped 0" in capsys.readouterr().out
    assert (tmp_path / "h" / "sessions" / "a" / "session.json").exists()


def test_import_legacy_copies_reference_stats_without_overwriting(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    src = _legacy(tmp_path)
    (src / "reference").mkdir()
    (src / "reference" / "stats.json").write_text('{"new": 1}', encoding="utf-8")
    r = run("import-legacy", src)
    assert r.returncode == 0, r.stderr
    dest = tmp_path / "h" / "reference" / "stats.json"
    assert dest.read_text(encoding="utf-8") == '{"new": 1}'
    dest.write_text("mine", encoding="utf-8")
    assert run("import-legacy", src).returncode == 0
    assert dest.read_text(encoding="utf-8") == "mine"


def test_import_legacy_with_nothing_to_import(tmp_path, monkeypatch):
    monkeypatch.setenv("STORYCOACH_HOME", str(tmp_path / "h"))
    (tmp_path / "empty").mkdir()
    r = run("import-legacy", tmp_path / "empty")
    assert r.returncode == 0 and "nothing to import in" in r.stdout
