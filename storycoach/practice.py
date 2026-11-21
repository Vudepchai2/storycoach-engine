"""Practice cases: a made-up story, with made-up voice measurements, run through the whole coaching loop."""
import json
import shutil
from pathlib import Path

from storycoach import home

SYNTHETIC_NOTE = "Made-up practice take, no real voice\n"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def paths_for(case: dict) -> tuple[Path, Path]:
    """(session folder, memory folder), both inside practice_dir()."""
    from storycoach.memory import bank_slug
    from storycoach.session import Session

    root = home.practice_dir()
    return Session.folder(root, case["name"]), root / "people" / bank_slug(case["founder"])


def reset_paths(paths: list[Path]) -> None:
    """Remove practice folders, and only folders strictly inside practice_dir()."""
    root = home.practice_dir().resolve()
    resolved = [p.resolve() for p in paths]
    for p in resolved:
        if p == root or not p.is_relative_to(root):
            raise ValueError(f"refusing to remove {p}: it is not inside {root}")
    for p in resolved:
        if p.exists():
            shutil.rmtree(p)


def build(case_dir: Path, reset: bool, features_fn) -> Path | None:
    """Create the practice session and memory from a case folder. Returns the session folder,
    or None (after printing why) when it already exists and reset was not asked for."""
    from storycoach.memory import create_bank, open_bank
    from storycoach.memory.cli import _regen, _retain
    from storycoach.models import Transcript
    from storycoach.session import Session
    from storycoach.synth import synthesize_acoustics

    case_dir = Path(case_dir)
    case = _read(case_dir / "case.json")
    home.ensure_home()
    session_dir, bank_dir = paths_for(case)
    existing = [p for p in (session_dir, bank_dir) if p.exists()]
    if existing and not reset:
        raise FileExistsError(f"Practice folder {existing[0]} already exists. Run again with --reset to start it over.")
    reset_paths([session_dir, bank_dir])

    s = Session.create(home.practice_dir(), case["name"], None, self_mode=True, scenario=case["scenario"])
    s.data["founder"] = case["founder"]
    s.data["person"] = bank_dir.name  # the slug of the practice bank, under practice_dir()/people
    s.data["practice"] = True
    s.save()
    if (case_dir / "context.md").exists():
        shutil.copyfile(case_dir / "context.md", s.dir / "context.md")

    takes = sorted(p for p in (case_dir / "takes").iterdir() if p.is_dir())
    for src in takes:
        out = s.dir / src.name
        out.mkdir()
        raw = _read(src / "transcript.json")
        t = Transcript.from_dict(raw)
        _write(out / "transcript.json", t.to_dict())
        shutil.copyfile(src / "beats.json", out / "beats.json")
        _write(out / "acoustics.json", synthesize_acoustics(t, _read(src / "delivery.json")).to_dict())
        (out / "words.txt").write_text("".join(f"{i}\t{w.text}\n" for i, w in enumerate(t.words)),
                                       encoding="utf-8", newline="\n")
        (out / "SYNTHETIC.txt").write_text(SYNTHETIC_NOTE, encoding="utf-8", newline="\n")
    for src in takes:
        features_fn(s.dir / src.name)

    bank = create_bank(home.practice_dir() / "people", case["founder"])
    store, _ = open_bank(bank)
    _retain(store, _read(case_dir / "memory_batch.json"))
    _regen(bank)
    return s.dir
