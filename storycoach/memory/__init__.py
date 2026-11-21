from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .bank import Bank
from .schema import normalise_name
from .store import FileStore


def bank_slug(name: str) -> str:
    slug = normalise_name(name).replace(" ", "-")
    if not slug:
        raise ValueError(f"cannot make a bank name from {name!r}")
    return slug


def create_bank(root: Path, name: str) -> Path:
    slug = bank_slug(name)
    directory = Path(root) / slug
    if directory.exists():
        raise FileExistsError(f"bank already exists: {directory}")
    (directory / "sources").mkdir(parents=True)
    (directory / "pages").mkdir()
    person = {"name": name, "slug": slug,
              "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "consent": {"memory": True}}
    (directory / "person.json").write_text(json.dumps(person, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    return directory


def open_bank(directory: Path) -> tuple[FileStore, Bank]:
    directory = Path(directory)
    if not (directory / "person.json").exists():
        raise FileNotFoundError(f"no memory bank at {directory}; run `memory init` first")
    store = FileStore(directory)
    return store, Bank.from_events(store.events())
