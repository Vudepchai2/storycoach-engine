"""Release hygiene: no private terms or email addresses ship in the engine."""
import os
import re
import unicodedata
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git"}
SKIP_NAMES = {".scrub-list"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
EMAIL_OK = ("@users.noreply.github.com", "@example.com")


def _files():
    for p in sorted(ENGINE.rglob("*")):
        rel = p.relative_to(ENGINE).parts
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel):
            continue
        yield p


def _fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _lines(path):
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    yield from enumerate(text.splitlines(), 1)


def _terms():
    for base in (ENGINE.parent, ENGINE):
        f = base / ".scrub-list"
        if f.is_file():
            return [t.strip() for t in f.read_text(encoding="utf-8").splitlines() if t.strip()]
    return []


def _patterns(terms):
    # Only letters and digits count as word characters, so "_" does not hide a term.
    return [re.compile(rf"(?<![A-Za-z0-9]){re.escape(_fold(t))}(?![A-Za-z0-9])", re.IGNORECASE)
            for t in terms]


def _matches(pats, text):
    return any(p.search(text) or p.search(_fold(text)) for p in pats)


def find_hits(terms, files, root):
    """Return 'file:line' (or 'file (file name)') for every term hit; never the term."""
    pats = _patterns(terms)
    hits = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        if _matches(pats, rel):
            hits.append(f"{rel} (file name)")
        for n, line in _lines(p):
            if _matches(pats, line):
                hits.append(f"{rel}:{n}")
    return hits


def test_no_scrub_terms():
    terms = _terms()
    if not terms:
        if os.environ.get("STORYCOACH_REQUIRE_SCRUB") == "1":
            pytest.fail("STORYCOACH_REQUIRE_SCRUB=1 but no .scrub-list was found")
        pytest.skip("no .scrub-list present")
    hits = find_hits(terms, _files(), ENGINE)
    assert not hits, "scrub-list hits (term not shown):\n" + "\n".join(hits)


def test_matcher_catches_underscore_and_file_name(tmp_path):
    (tmp_path / "test_zorblax.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("ok\nname = 'x_zorblax_y'\nZORBLAXIAN is fine\n", encoding="utf-8")
    files = sorted(tmp_path.iterdir())
    hits = find_hits(["zorblax"], files, tmp_path)
    assert hits == ["b.py:2", "test_zorblax.py (file name)"]


def test_missing_list_skips_or_fails_when_required(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__), "ENGINE", tmp_path / "engine", raising=False)
    monkeypatch.delenv("STORYCOACH_REQUIRE_SCRUB", raising=False)
    with pytest.raises(pytest.skip.Exception):
        test_no_scrub_terms()
    monkeypatch.setenv("STORYCOACH_REQUIRE_SCRUB", "1")
    with pytest.raises(pytest.fail.Exception):
        test_no_scrub_terms()


def test_no_email_addresses():
    hits = []
    for p in _files():
        for n, line in _lines(p):
            for m in EMAIL.finditer(line):
                if not m.group(0).lower().endswith(EMAIL_OK):
                    hits.append(f"{p.relative_to(ENGINE).as_posix()}:{n}")
    assert not hits, "email addresses:\n" + "\n".join(hits)
