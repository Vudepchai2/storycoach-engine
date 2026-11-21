from __future__ import annotations

import re

from .schema import PREFIX


class Bank:
    """State rebuilt from the event log on every load."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.conflicts: dict[str, dict] = {}

    @classmethod
    def from_events(cls, events: list[dict]) -> "Bank":
        bank = cls()
        for e in events:
            bank._apply(e)
        return bank

    def _apply(self, e: dict) -> None:
        op, id_, data = e["op"], e["id"], e.get("data") or {}
        if op == "add":
            self.records[id_] = {
                "id": id_, "type": e["type"], "data": dict(data),
                "sources": [e["source"]] if e.get("source") else [],
                "history": [], "retracted": None, "confirmed": None,
                "added_seq": e["seq"],
            }
        elif op == "conflict":
            self.conflicts[id_] = {"id": id_, "about": data["about"], "key": data["key"],
                                   "claims": list(data["claims"]), "open": True, "kept": None}
        elif op == "resolve":
            self._resolve(id_, data)
        elif op == "cite":
            self.records[id_]["sources"].append({**e["source"], **data})
        elif op == "update":
            rec = self.records[id_]
            rec["history"].append({k: rec["data"].get(k) for k in data})
            rec["data"].update(data)
        elif op == "confirm":
            self.records[id_]["confirmed"] = dict(data)
        elif op == "retract":
            rec = self.records[id_]
            rec["retracted"] = data.get("reason") or "retracted"
            if data.get("superseded_by"):
                rec["superseded_by"] = data["superseded_by"]

    def _resolve(self, id_: str, data: dict) -> None:
        conflict = self.conflicts[id_]
        keep = data["keep"]
        conflict["open"], conflict["kept"] = False, keep
        self.records[keep]["confirmed"] = {"quote": data["quote"]}
        for cid in conflict["claims"]:
            if cid != keep:
                self.records[cid]["retracted"] = f"superseded by {keep}"
                self.records[cid]["superseded_by"] = keep

    def next_id(self, type: str) -> str:
        prefix = PREFIX[type]
        if type == "conflict":
            ids = self.conflicts
        else:
            ids = [i for i, r in self.records.items() if r["type"] == type]
        nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", i))]
        return f"{prefix}{max(nums, default=0) + 1}"

    def live(self, type: str) -> list[dict]:
        return [r for r in self.records.values() if r["type"] == type and not r["retracted"]]

    def claim_status(self, id: str) -> str:
        rec = self.records[id]
        if rec["retracted"]:
            return "retracted"
        if any(c["open"] and id in c["claims"] for c in self.conflicts.values()):
            return "conflicted"
        if rec["confirmed"]:
            return "confirmed"
        sources = rec["sources"]
        # Refs are canonical since retain normalises them; case still never makes a second source.
        if len({str(s["ref"]).casefold() for s in sources if s.get("ref")}) >= 2:
            return "corroborated"
        if sources and all(s.get("kind") == "document" for s in sources):
            return "documented"
        return "said"

    def moment_status(self, id: str) -> str:
        told = any(s.get("kind") in ("said", "transcript") for s in self.records[id]["sources"])
        return "told" if told else "imported"

    def keys_for(self, about: str) -> list[str]:
        return sorted({r["data"]["key"] for r in self.live("claim") if r["data"].get("about") == about})
