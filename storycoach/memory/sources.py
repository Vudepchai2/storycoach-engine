from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from .bank import Bank
from .store import FileStore


def _sha256(file: Path) -> str:
    h = hashlib.sha256()
    with open(file, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def import_source(bank_dir: Path, file: Path) -> tuple[str, bool]:
    """Copy a document into the bank and register it; the same content is stored once."""
    file = Path(file)
    if not file.is_file():
        raise FileNotFoundError(f"no such file to import: {file}")
    digest = _sha256(file)
    store = FileStore(bank_dir)
    bank = Bank.from_events(store.events())
    for rec in bank.live("source"):
        if rec["data"].get("sha256") == digest:
            return rec["id"], False
    stored = f"sources/{digest[:12]}-{file.name}"
    target = Path(bank_dir) / stored
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(file, target)
    id_ = bank.next_id("source")
    store.append([{"op": "add", "id": id_, "type": "source",
                   "data": {"filename": file.name, "sha256": digest, "stored": stored},
                   "source": {"kind": "said", "ref": "import"}}])
    return id_, True
