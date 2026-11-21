from __future__ import annotations

import math
from datetime import datetime

from . import claims
from .bank import Bank
from .schema import (ENTITY_KINDS, FIELDS, PREFIX, REQUIRED, SOURCE_KINDS, TEXT, TEXT_LISTS,
                     UPDATABLE, canonical_ref, normalise_name)
from .store import MemoryStore

OPS = ("add", "update", "confirm", "retract", "cite", "resolve")
LIST_FIELDS = {"who", "moments", "uses", "aliases", "quotes", "debrief", "evidence"}
REF_LISTS = {"who", "moments", "uses"}
DATE_FORMATS = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}


class BatchError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _empty(v) -> bool:
    return v is None or v == [] or (isinstance(v, str) and not v.strip())


def _ref_text(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _evidence(v) -> list[dict] | None:
    """A list of {ref, quote} strings with canonical refs, or None when malformed."""
    if not all(isinstance(e, dict) and set(e) == {"ref", "quote"} and _ref_text(e["ref"])
               and isinstance(e["quote"], str) for e in v):
        return None
    return [{"ref": canonical_ref(e["ref"]), "quote": e["quote"]} for e in v]


def _valid_date(v) -> bool:
    try:
        return isinstance(v, str) and bool(datetime.strptime(v, DATE_FORMATS[len(v)]))
    except (KeyError, ValueError):
        return False


class _Planner:
    """Pass 1: validate every item, resolve handles and links, and plan the writes."""

    def __init__(self, bank: Bank, kind: str | None, errors: list[str]):
        self.bank, self.kind, self.errors = bank, kind, errors
        self.plan: list[dict] = []
        self.pending: dict[str, dict] = {}
        self.handles: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.added: list[dict] = []
        self.linked: list[dict] = []
        self.cited: list[str] = []
        self.conflicts: list[dict] = []
        self.gone: set[str] = set()
        self.pending_conflicts: list[tuple] = []
        self.index: dict[str, str] = {}
        self.aliases: dict[str, list[str]] = {}
        for r in bank.live("entity"):
            self._index_entity(r["id"], r["data"].get("name"), r["data"].get("aliases"))

    def err(self, i: int, msg: str) -> None:
        self.errors.append(f"item {i}: {msg}")

    def _index_entity(self, id_: str, name, aliases) -> None:
        self.aliases[id_] = list(aliases or [])
        for n in [name, *(aliases or [])]:
            if n:
                self.index.setdefault(normalise_name(n), id_)

    def _new_id(self, type: str) -> str:
        if type not in self.counters:
            self.counters[type] = int(self.bank.next_id(type)[len(PREFIX[type]):])
        n = self.counters[type]
        self.counters[type] += 1
        return f"{PREFIX[type]}{n}"

    def _type_of(self, id_: str) -> str | None:
        rec = self.bank.records.get(id_) or self.pending.get(id_)
        return rec["type"] if rec else None

    def _live(self, i: int, id_: str) -> str | None:
        if id_ in self.bank.records and self.bank.records[id_]["retracted"]:
            self.err(i, f"'{id_}' was retracted")
            return None
        return id_

    def _ref(self, i: int, v, names: bool = False) -> str | None:
        if isinstance(v, str) and v.startswith("@") and v in self.handles:
            return self._live(i, self.handles[v])
        if isinstance(v, str) and self._type_of(v):
            return self._live(i, v)
        if names and isinstance(v, str) and not v.startswith("@") and normalise_name(v) in self.index:
            return self.index[normalise_name(v)]
        if names and isinstance(v, str) and not v.startswith("@"):
            self.err(i, f"unknown name '{v}' in who (add the entity first or use its id)")
        else:
            self.err(i, f"unknown id '{v}'")
        return None

    def _data(self, i: int, type: str, fields: dict) -> dict:
        """Check values and turn references into ids."""
        out = {}
        for f, v in fields.items():
            if f not in FIELDS[type] or _empty(v):
                continue
            if f in LIST_FIELDS and not isinstance(v, list):
                self.err(i, f"{f} must be a list")
            elif f in TEXT and not isinstance(v, str):
                self.err(i, f"{f} must be a string")
            elif f in TEXT_LISTS and not all(isinstance(a, str) for a in v):
                self.err(i, f"{f} must be strings")
            elif f == "value" and not _number(v):
                self.err(i, "value must be a number")
            elif f == "evidence":
                if (ev := _evidence(v)) is None:
                    self.err(i, "evidence must be a list of {ref, quote} strings")
                else:
                    out[f] = ev
            elif f == "session":
                out[f] = canonical_ref(v)
            elif f in REF_LISTS:
                ids = [self._ref(i, x, names=(f == "who")) for x in v]
                out[f] = [x for x in ids if x]
            elif f == "about" and type == "observation":
                if v in ("person", "telling"):
                    out[f] = v
                else:
                    self.err(i, "observation about must be 'person' or 'telling'")
            elif f == "about":
                out[f] = self._ref(i, v)
            elif f == "date" and not _valid_date(v):
                self.err(i, "date must be YYYY, YYYY-MM or YYYY-MM-DD")
            elif f == "kind" and type == "entity" and v not in ENTITY_KINDS:
                self.err(i, f"entity kind must be one of {', '.join(sorted(ENTITY_KINDS))}")
            else:
                out[f] = v
        return out

    def run(self, items: list) -> None:
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                self.err(i, "must be an object")
                continue
            op = it.get("op", "add")
            if op not in OPS:
                self.err(i, f"unknown op '{op}'")
            elif self.kind == "coach" and not (op == "add" and it.get("type") == "observation"):
                self.err(i, "a coach source can only add observations")
            elif op in ("confirm", "resolve") and self.kind in SOURCE_KINDS and self.kind != "said":
                self.err(i, f"{op} needs a 'said' source")
            else:
                getattr(self, f"_op_{op}")(i, it)

    def _op_add(self, i: int, it: dict) -> None:
        type = it.get("type")
        if not isinstance(type, str) or type not in REQUIRED:
            return self.err(i, f"unknown type '{type}'")
        fields = {k: v for k, v in it.items() if k not in ("op", "type", "ref")}
        before = len(self.errors)
        for f in sorted(fields):
            if f not in FIELDS[type]:
                self.err(i, f"unknown field '{f}' for {type}")
        for f in sorted(REQUIRED[type]):
            if _empty(fields.get(f)):
                self.err(i, "claim needs a quote" if (type, f) == ("claim", "quote")
                         else f"{type} needs {f}")
        data = self._data(i, type, fields)
        ref = it.get("ref")
        if ref is not None and (not isinstance(ref, str) or not ref.startswith("@")
                                or ref in self.handles):
            self.err(i, f"ref '{ref}' must be a new @handle")
        if len(self.errors) > before:
            return
        if type == "entity" and self._link(i, data, ref):
            return
        if type == "claim" and self._claim(i, data, ref):
            return
        id_ = self._new_id(type)
        entry = {"op": "add", "id": id_, "type": type, "data": data}
        self.plan.append(entry)
        self.pending[id_] = entry
        self.added.append({"ref": ref, "id": id_, "type": type})
        if ref:
            self.handles[ref] = id_
        if type == "entity":
            self._index_entity(id_, data["name"], data.get("aliases"))
        if type == "claim":
            self._after_claim(id_, data)

    def _live_claims(self) -> list[dict]:
        found = [r for r in self.bank.live("claim")] + [
            e for e in self.pending.values() if e["type"] == "claim"]
        return [c for c in found if c["id"] not in self.gone]

    def _claim(self, i: int, data: dict, ref) -> bool:
        """Same value: plan a cite and return True. Different value: add, then conflict."""
        cite, differing = claims.match(data, self._live_claims())
        if cite:
            self.plan.append({"op": "cite", "id": cite, "type": "claim",
                              "data": {"quote": data["quote"]}})
            self.cited.append(cite)
            if ref:
                self.handles[ref] = cite
            return True
        self.pending_conflicts = [(c["id"], c["data"].get("value")) for c in differing]
        return False

    def _after_claim(self, id_: str, data: dict) -> None:
        for old_id, old_value in self.pending_conflicts:
            x = self._new_id("conflict")
            self.plan.append({"op": "conflict", "id": x, "type": "conflict",
                              "data": {"about": data["about"], "key": data["key"],
                                       "claims": [old_id, id_]}})
            self.conflicts.append({"id": x, "about": data["about"], "key": data["key"],
                                   "claims": [old_id, id_], "values": [old_value, data.get("value")]})
        self.pending_conflicts = []

    def _link(self, i: int, data: dict, ref) -> bool:
        owners = [(n, self.index.get(normalise_name(n))) for n in [data["name"], *data.get("aliases", [])]]
        id_ = next((o for _, o in owners if o), None)
        if id_ is None:
            return False
        clashes = [(n, o) for n, o in owners if o and o != id_]
        for n, o in clashes:
            self.err(i, f"'{n}' already names {o}")
        if clashes:
            return True
        known = {normalise_name(n) for n in self.aliases[id_]}
        known.add(normalise_name(self._name_of(id_)))
        for n in [data["name"], *data.get("aliases", [])]:
            if normalise_name(n) not in known:
                known.add(normalise_name(n))
                self.aliases[id_].append(n)
                self.index.setdefault(normalise_name(n), id_)
        if id_ in self.pending:
            self.pending[id_]["data"]["aliases"] = list(self.aliases[id_])
        elif self.aliases[id_] != (self.bank.records[id_]["data"].get("aliases") or []):
            self.plan.append({"op": "update", "id": id_, "type": "entity",
                              "data": {"aliases": list(self.aliases[id_])}})
        old = (self.pending.get(id_) or self.bank.records[id_])["data"]
        # The existing record's kind and relation, so a homonym (another Sam) is easy to spot.
        self.linked.append({"name": data["name"], "id": id_, "kind": old.get("kind"),
                            "relation": old.get("relation")})
        if ref:
            self.handles[ref] = id_
        return True

    def _name_of(self, id_: str) -> str:
        return (self.pending.get(id_) or self.bank.records[id_])["data"]["name"]

    def _op_update(self, i: int, it: dict) -> None:
        id_ = self._ref(i, it.get("id"))
        fields = it.get("fields")
        if not isinstance(fields, dict) or not fields:
            return self.err(i, "update needs fields")
        if id_ is None:
            return
        type = self._type_of(id_)
        before = len(self.errors)
        for f in sorted(fields):
            if f not in UPDATABLE.get(type, ()):
                self.err(i, f"unknown field '{f}' for {type}")
        data = self._data(i, type, fields)
        if type == "entity":
            for a in data.get("aliases", []):
                other = self.index.get(normalise_name(a))
                if other and other != id_:
                    self.err(i, f"'{a}' already names {other}")
            if len(self.errors) == before and "aliases" in data:
                self.aliases[id_] = list(data["aliases"])
                for a in data["aliases"]:
                    self.index.setdefault(normalise_name(a), id_)
        if len(self.errors) == before:
            self.plan.append({"op": "update", "id": id_, "type": type, "data": data})

    def _op_confirm(self, i: int, it: dict) -> None:
        self._simple(i, it, "confirm", "quote")

    def _op_retract(self, i: int, it: dict) -> None:
        self._simple(i, it, "retract", "reason")

    def _op_cite(self, i: int, it: dict) -> None:
        ref = it.get("ref")
        if ref is not None and not _ref_text(ref):
            return self.err(i, "ref must be a non-empty string")
        entry = self._simple(i, it, "cite", "quote")
        if entry and ref is not None:
            entry["source"] = {"ref": canonical_ref(ref)}  # merged over the batch source in pass 2

    def _simple(self, i: int, it: dict, op: str, field: str) -> dict | None:
        id_ = self._ref(i, it.get("id"))
        if _empty(it.get(field)):
            self.err(i, f"{op} needs {field}")
        elif not isinstance(it[field], str):
            self.err(i, f"{field} must be a string")
        elif id_:
            entry = {"op": op, "id": id_, "type": self._type_of(id_), "data": {field: it[field]}}
            if op == "retract":
                self.gone.add(id_)
            self.plan.append(entry)
            return entry
        return None

    def _op_resolve(self, i: int, it: dict) -> None:
        cid = it.get("conflict")
        conflict = self.bank.conflicts.get(cid) if isinstance(cid, str) else None
        if conflict is None or not conflict["open"]:
            return self.err(i, f"unknown id '{it.get('conflict')}'")
        keep = self._ref(i, it.get("keep"))
        if _empty(it.get("quote")):
            self.err(i, "resolve needs quote")
        elif not isinstance(it["quote"], str):
            self.err(i, "quote must be a string")
        elif keep and keep not in conflict["claims"]:
            self.err(i, f"'{keep}' is not part of conflict '{conflict['id']}'")
        elif keep:
            self.gone.update(c for c in conflict["claims"] if c != keep)
            self.plan.append({"op": "resolve", "id": conflict["id"], "type": "conflict",
                              "data": {"keep": keep, "quote": it["quote"]}})


def _build(bank: Bank, plan: list[dict], source: dict, report: dict) -> list[dict]:
    """Pass 2: turn the plan into events. Claim matching (cite or conflict) slots in here."""
    return [{"op": p["op"], "id": p["id"], "type": p["type"], "data": p["data"],
             "source": {**source, **p["source"]} if "source" in p else dict(source)}
            for p in plan]


def retain(store: MemoryStore, batch: dict) -> dict:
    if not isinstance(batch, dict):
        raise BatchError(["batch must be an object"])
    bank = Bank.from_events(store.events())
    source = batch.get("source")
    items = batch.get("items", [])
    errors: list[str] = []
    if not isinstance(items, list):
        errors.append("items must be a list")
        items = []
    kind = None
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    elif (kind := source.get("kind")) not in SOURCE_KINDS:
        errors.append(f"source.kind must be one of {', '.join(sorted(SOURCE_KINDS))}")
    elif kind == "document":
        ref = source.get("ref")
        rec = bank.records.get(ref) if isinstance(ref, str) else None
        if not rec or rec["type"] != "source" or rec["retracted"]:
            errors.append("source.ref must be a registered source id for a document")
    elif not _ref_text(source.get("ref")):
        errors.append("source.ref must be a non-empty string")
    else:
        source = {**source, "ref": canonical_ref(source["ref"])}
    planner = _Planner(bank, kind, errors)
    planner.run(items)
    if errors:
        raise BatchError(errors)
    report = {"added": planner.added, "linked": planner.linked, "cited": planner.cited,
              "conflicts": planner.conflicts, "keys_by_about": {}}
    store.append(_build(bank, planner.plan, source, report))
    after = Bank.from_events(store.events())
    abouts = {c["data"]["about"] for c in after.live("claim")}
    report["keys_by_about"] = {a: after.keys_for(a) for a in sorted(abouts)}
    return report
