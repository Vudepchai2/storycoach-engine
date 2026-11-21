from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class MemoryStore(Protocol):
    def append(self, events: list[dict]) -> None: ...
    def events(self) -> list[dict]: ...


class FileStore:
    """Append-only JSONL event log: the single source of truth for a bank."""

    def __init__(self, directory: Path):
        self.path = Path(directory) / "log.jsonl"
        self.warnings: list[str] = []

    def events(self) -> list[dict]:
        self.warnings = []
        if not self.path.exists():
            return []
        # Bytes, decoded per line: a write cut inside a multi-byte character is still just a truncated tail.
        data = self.path.read_bytes()
        if not data:
            return []
        lines = data.split(b"\n")
        # Data not ending in a newline means the last write may have been cut short.
        partial_tail = not data.endswith(b"\n")
        if not partial_tail:
            lines.pop()
        out = []
        for n, line in enumerate(lines, start=1):
            try:
                out.append(json.loads(line.decode("utf-8")))
            except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError
                if partial_tail and n == len(lines):
                    self.warnings.append(f"log.jsonl line {n} is truncated and was ignored")
                    break
                raise ValueError(f"log.jsonl line {n} is corrupt: {exc}") from exc
        return out

    def next_seq(self) -> int:
        events = self.events()
        return (events[-1]["seq"] + 1) if events else 1

    def _repair_tail(self) -> None:
        """Drop a partial last line so new events start on a clean line.

        next_seq() has just read the log, so the truncation warning is already recorded.
        """
        if not self.path.exists():
            return
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        try:
            json.loads(data[cut:].decode("utf-8"))
        except ValueError:  # partial line (JSONDecodeError and UnicodeDecodeError both qualify)
            with open(self.path, "r+b") as f:
                f.truncate(cut)
        else:  # a complete event that only lacks its newline: keep it
            with open(self.path, "ab") as f:
                f.write(b"\n")

    def append(self, events: list[dict]) -> None:
        if not events:
            return
        seq = self.next_seq()
        self._repair_tail()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = []
        for i, e in enumerate(events):
            lines.append(json.dumps({**e, "seq": seq + i, "at": now}, ensure_ascii=False) + "\n")
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write("".join(lines))
            f.flush()
            os.fsync(f.fileno())
