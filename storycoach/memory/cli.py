"""The `memory` subcommands and the session-to-bank linking used by `new`."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import bank_slug, create_bank, open_bank
from .recall import brief, gaps, recall
from .retain import BatchError, retain
from .pages import write_pages
from .sources import import_source


def _fail(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def _utf8() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _warn(store) -> None:
    for w in store.warnings:
        print(w, file=sys.stderr)


def _person(directory: Path) -> dict:
    return json.loads((Path(directory) / "person.json").read_text(encoding="utf-8"))


def _open(directory):
    _utf8()
    store, bank = open_bank(Path(directory))
    _warn(store)
    return store, bank


def _regen(directory: Path) -> None:
    """Rewrite the pages. The log is already written, so a failure here is only a warning."""
    try:
        store, bank = open_bank(directory)
        write_pages(bank, _person(directory)["name"], Path(directory) / "pages")
    except Exception as e:
        print(f"warning: the pages were not updated ({e}). The memory itself was saved; "
              f"run `memory pages {directory}` to retry.", file=sys.stderr)


def _retain(store, batch: dict) -> dict:
    try:
        return retain(store, batch)
    except BatchError as e:
        for err in e.errors:
            print(err, file=sys.stderr)
        sys.exit(1)


def _records(n: int) -> str:
    return f"{n} record" + ("" if n == 1 else "s")


def prepare_bank(founder: str, people_root: Path, self_mode: bool,
                 person: str | None = None) -> tuple[Path, bool]:
    """Find and check, or create, the bank for `new`, before the session exists.

    Returns (bank folder, created by this call). Exits 1, having written nothing, when the bank
    can't be used: two people must never share a bank, so in operator mode reusing one needs
    `--person <slug>`."""
    root = Path(people_root)
    try:
        slug = bank_slug(person or founder)
    except ValueError as e:
        _fail(str(e))
    directory = root / slug
    if (directory / "person.json").exists():
        try:
            store, bank = open_bank(directory)
        except ValueError as e:
            _fail(f"the memory bank at {directory} can't be read: {e}")
        _warn(store)
        n = _records(sum(1 for r in bank.records.values() if not r["retracted"]))
        if not self_mode and not person:
            _fail(f"{directory} already holds a memory bank ({n}), and two people must never share one. "
                  f"If this is the same person, run again with --person {slug}. If it is someone else "
                  f"with the same name, use a distinguishing name, for example \"{founder} <surname>\".")
        print(f"Reusing memory bank {directory} ({n}).", file=sys.stderr)
        return directory, False
    if directory.exists():
        _fail(f"{directory} exists but is not a memory bank (it has no person.json). "
              "Nothing was changed; move that folder aside or use another name.")
    if person:
        _fail(f"no memory bank at {directory}; --person names an existing bank folder under {root}.")
    return create_bank(root, founder), True


def undo_new_bank(directory: Path) -> None:
    """Undo a bank `new` just created, unless something was already written to its log."""
    directory = Path(directory)
    if (directory / "log.jsonl").exists():
        print(f"Kept memory bank {directory}: it already holds records.", file=sys.stderr)
        return
    try:
        (directory / "person.json").unlink()
        for d in (directory / "pages", directory / "sources", directory):
            d.rmdir()  # only when empty
    except OSError:
        print(f"Left memory bank {directory} in place.", file=sys.stderr)


def attach_memory(session, directory: Path, occasion: str | None) -> None:
    """Record the occasion in a bank prepare_bank checked, and link the session to it.

    retain stores the session path in its canonical, project-relative form."""
    store, _ = open_bank(directory)
    report = _retain(store, {
        "source": {"kind": "said", "ref": str(session.dir)},
        "items": [{"type": "occasion", "name": occasion or session.data["founder"],
                   "session": str(session.dir)}]})
    session.data["person"] = _person(directory)["slug"]
    session.data["occasion_id"] = report["added"][0]["id"]
    session.data.setdefault("consent", {})["memory"] = True
    session.save()
    _regen(directory)


def cmd_init(a):
    _utf8()
    print(create_bank(Path(a.root), a.name))


def cmd_retain(a):
    store, _ = _open(a.bank)
    try:
        batch = json.loads(Path(a.batch).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        _fail(f"batch file is not valid JSON: {e}")
    report = _retain(store, batch)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)  # before pages: the write succeeded
    _regen(Path(a.bank))


def cmd_import(a):
    _open(a.bank)
    id_, created = import_source(Path(a.bank), Path(a.file))
    print(f"{id_} {'new' if created else 'already imported'}", flush=True)
    _regen(Path(a.bank))


def cmd_brief(a):
    _, bank = _open(a.bank)
    print(brief(bank, _person(Path(a.bank))["name"]))


def cmd_recall(a):
    _, bank = _open(a.bank)
    out = recall(bank, query=a.query, about=a.about, entity=a.entity, type=a.type,
                 since=a.since, limit=a.limit)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_gaps(a):
    _, bank = _open(a.bank)
    print(json.dumps(gaps(bank), ensure_ascii=False, indent=2))


def cmd_pages(a):
    _, bank = _open(a.bank)
    for p in write_pages(bank, _person(Path(a.bank))["name"], Path(a.bank) / "pages"):
        print(p)


def cmd_forget(a):
    store, _ = _open(a.bank)
    _retain(store, {"source": {"kind": "said", "ref": "forget"},
                    "items": [{"op": "retract", "id": a.id, "reason": a.reason}]})
    print(f"retracted {a.id}", flush=True)
    _regen(Path(a.bank))


def cmd_delete(a):
    _utf8()
    directory = Path(a.bank)
    if not a.yes:
        _fail(f"Refusing to delete {directory} without --yes. "
              "This removes every memory for this person and cannot be undone.", 2)
    if not (directory / "person.json").exists():
        _fail(f"no memory bank at {directory}")
    shutil.rmtree(directory)
    print(f"deleted {directory}")


def cmd_link(a):
    _utf8()
    from storycoach.session import Session

    s = Session.load(Path(a.session_dir))
    if not (Path(a.bank) / "person.json").exists():
        _fail(f"no memory bank at {a.bank}; run `memory init` first")
    s.data["person"] = _person(Path(a.bank))["slug"]
    s.save()
    print(f"linked {s.dir} to {s.data['person']}")


def register(sub) -> None:
    m = sub.add_parser("memory", help="per-person memory bank")
    ms = m.add_subparsers(required=True)

    def add(name, fn, *args):
        c = ms.add_parser(name)
        for arg in args:
            c.add_argument(*arg[0], **arg[1])
        c.set_defaults(fn=fn)
        return c

    pos = lambda n, **k: ((n,), k)
    opt = lambda n, **k: ((n,), k)
    from pathlib import Path as _P
    from storycoach.home import people_dir
    default_root = str(people_dir())
    add("init", cmd_init, pos("name"), opt("--root", default=default_root))
    add("retain", cmd_retain, pos("bank"), pos("batch"))
    add("import", cmd_import, pos("bank"), pos("file"))
    add("brief", cmd_brief, pos("bank"))
    add("recall", cmd_recall, pos("bank"), opt("--query"), opt("--about"), opt("--entity"),
        opt("--type"), opt("--since"), opt("--limit", type=int, default=10))
    add("gaps", cmd_gaps, pos("bank"))
    add("pages", cmd_pages, pos("bank"))
    add("forget", cmd_forget, pos("bank"), pos("id"), opt("--reason", required=True))
    add("delete", cmd_delete, pos("bank"), opt("--yes", action="store_true"))
    add("link", cmd_link, pos("session_dir"), pos("bank"))
