from __future__ import annotations

from .bank import Bank
from .schema import normalise_name

GAP_ORDER = ("open_conflict", "imported_only", "no_change", "no_meaning",
             "no_scene", "thin_observation", "unused_moment")
GAP_SECTIONS = {
    "open_conflict": "Recall: checking a number",
    "imported_only": "Recall: from a document to a moment",
    "no_change": "Content: action, result, stakes",
    "no_meaning": "Content: pruning and the point",
    "no_scene": "Capture — origin, audience, moments",
    "thin_observation": "Recall: connecting moments",
    "unused_moment": "Recall: connecting moments",
}
TEXT_FIELDS = {
    "moment": ("title", "when", "where", "what_happened", "what_changed", "meaning", "quotes"),
    "claim": ("statement", "quote", "key"),
    "entity": ("name", "aliases", "relation"),
    "observation": ("statement",),
    "occasion": ("name", "audience", "outcome"),
}
LINE_CAP = 120


def _cap(line: str) -> str:
    line = " ".join(line.split())  # a newline inside a field must not break the one-line shape
    return line if len(line) <= LINE_CAP else line[:LINE_CAP - 1] + "…"


def _stems(text: str) -> set[str]:
    return {w[:5] for w in normalise_name(text).split() if len(w) >= 3}


def _text(rec: dict) -> str:
    parts = []
    for f in TEXT_FIELDS.get(rec["type"], ()):
        v = rec["data"].get(f)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif v:
            parts.append(str(v))
    return " ".join(parts)


def _status(bank: Bank, rec: dict) -> str:
    if rec["type"] == "claim":
        return bank.claim_status(rec["id"])
    if rec["type"] == "moment":
        return bank.moment_status(rec["id"])
    return "retracted" if rec["retracted"] else ("confirmed" if rec["confirmed"] else "live")


def _live(bank: Bank) -> list[dict]:
    return [r for r in bank.records.values() if not r["retracted"]]


def _by_date(recs: list[dict]) -> list[dict]:
    dated = sorted((r for r in recs if r["data"].get("date")),
                   key=lambda r: r["data"]["date"])
    return dated + [r for r in recs if not r["data"].get("date")]


def _key_claims(bank: Bank, about: str) -> list[str]:
    """`key=value unit (status)`: the unit is dropped when it repeats the key, the status when it's `said`."""
    out = []
    for c in bank.live("claim"):
        d = c["data"]
        if d.get("about") == about and d.get("value") not in (None, ""):
            unit = d.get("unit")
            unit = f" {unit}" if unit and normalise_name(str(unit)) != normalise_name(str(d["key"])) else ""
            status = bank.claim_status(c["id"])
            out.append(f"{d['key']}={d['value']}{unit}" + (f" ({status})" if status != "said" else ""))
    return out


def _with_claims(bank: Bank, line: str, about: str) -> str:
    claims = _key_claims(bank, about)
    return line + (" · " + ", ".join(claims) if claims else "")


def evidence_count(o: dict) -> int:
    """The evidence quotes plus the distinct places outside the coach that back it."""
    refs = {str(s.get("ref")).casefold() for s in o["sources"] if s.get("kind") != "coach"}
    return len(o["data"].get("evidence") or []) + len(refs)


def observation_line(o: dict) -> str:
    srcs = o["sources"]
    reading = (" (coach's reading)"
               if srcs and all(s.get("kind") == "coach" for s in srcs) and not o["confirmed"]
               else "")
    # Cap the statement, not the line: the evidence count and the reading label must survive.
    head, tail = f"- [{o['id']}] ", f" ({evidence_count(o)} evidence){reading}"
    statement = " ".join(str(o["data"].get("statement", "")).split())
    room = LINE_CAP - len(head) - len(tail)
    if len(statement) > room:
        statement = statement[:room - 1].rstrip() + "…"
    return head + statement + tail


def brief(bank: Bank, name: str) -> str:
    gap_list = gaps(bank)
    lines = [_cap(f"# {name}")]
    for about, head in (("person", "Themes"), ("telling", "How they tell it")):
        lines += ["", f"## {head}"]
        obs = [r for r in bank.live("observation") if r["data"].get("about") == about]
        lines += [observation_line(o) for o in obs] or ["- none"]
    lines += ["", "## Timeline"]
    moments = _by_date(bank.live("moment"))
    for m in moments:
        d = m["data"]
        when = f" ({d['when']})" if d.get("when") else ""
        line = f"- [{m['id']}] {d.get('title', '')}{when} · {bank.moment_status(m['id'])}"
        lines.append(_cap(_with_claims(bank, line, m["id"])))
    if not moments:
        lines.append("- none")
    lines += ["", "## People"]
    people = bank.live("entity")
    for e in people:
        d = e["data"]
        rel = f" — {d['relation']}" if d.get("relation") else ""
        line = f"- [{e['id']}] {d.get('name', '')} ({d.get('kind', '')}){rel}"
        lines.append(_cap(_with_claims(bank, line, e["id"])))
    if not people:
        lines.append("- none")
    lines += ["", "## Occasions"]
    occasions = _by_date(bank.live("occasion"))
    for oc in occasions:
        d = oc["data"]
        date = f" ({d['date']})" if d.get("date") else ""
        outcome = f" · {d['outcome']}" if d.get("outcome") else ""
        lines.append(_cap(_with_claims(bank, f"- [{oc['id']}] {d.get('name', '')}{date}{outcome}", oc["id"])))
    if not occasions:
        lines.append("- none")
    lines += ["", "## Open conflicts"]
    open_ = [c for c in bank.conflicts.values() if c["open"]]
    for c in open_:
        vals = " vs ".join(f"{cid}={bank.records[cid]['data'].get('value')}" for cid in c["claims"])
        lines.append(_cap(f"- [{c['id']}] {c['about']}.{c['key']}: {vals}"))
    if not open_:
        lines.append("- none")
    lines += ["", "## Gaps"]
    counts = {g: sum(1 for x in gap_list if x["gap"] == g) for g in GAP_ORDER}
    shown = [f"- {g}: {n}" for g, n in counts.items() if n]
    lines += shown or ["- none"]
    return "\n".join(lines) + "\n"


def recall(bank: Bank, query: str | None = None, about: str | None = None,
           entity: str | None = None, type: str | None = None,
           since: str | None = None, limit: int = 10) -> list[dict]:
    recs = _live(bank)
    if type:
        recs = [r for r in recs if r["type"] == type]
    if about:
        recs = [r for r in recs if r["data"].get("about") == about]
    if entity:
        key = normalise_name(entity)
        ids = {r["id"] for r in bank.live("entity")
               if r["id"] == entity or key in {normalise_name(n) for n in
                                               [r["data"].get("name") or "",
                                                *(r["data"].get("aliases") or [])]}}
        recs = [r for r in recs if r["id"] in ids
                or (r["type"] == "moment" and ids & set(r["data"].get("who") or []))]
    if since:
        recs = [r for r in recs if r["data"].get("date") and r["data"]["date"] >= since]
    scored = [(1.0, r) for r in recs]
    if query:
        words = _stems(query)
        scored = []
        for r in recs:
            score = len(words & _stems(_text(r))) / len(words) if words else 0
            if score > 0:
                scored.append((score, r))
    # date descending (undated last), stable so log order breaks ties
    scored.sort(key=lambda t: t[1]["data"].get("date") or "", reverse=True)
    scored.sort(key=lambda t: t[1]["data"].get("date") is None)
    scored.sort(key=lambda t: -t[0])
    return [{**r["data"], "id": r["id"], "type": r["type"], "data": r["data"],
             "sources": r["sources"], "status": _status(bank, r)} for _, r in scored[:limit]]


def gaps(bank: Bank) -> list[dict]:
    out: list[dict] = []

    def add(gap: str, id_: str, detail: str) -> None:
        out.append({"gap": gap, "id": id_, "question_section": GAP_SECTIONS[gap], "detail": detail})

    for c in bank.conflicts.values():
        if c["open"]:
            vals = " vs ".join(f"{cid}={bank.records[cid]['data'].get('value')}" for cid in c["claims"])
            add("open_conflict", c["id"], f"{c['key']}: {vals}")
    used = {u for o in bank.live("occasion") for u in o["data"].get("uses") or []}
    has_occasion = bool(bank.live("occasion"))
    for m in bank.live("moment"):
        d, title = m["data"], m["data"].get("title", m["id"])
        if bank.moment_status(m["id"]) == "imported":
            add("imported_only", m["id"], title)
        if not d.get("what_changed"):
            add("no_change", m["id"], title)
        if not d.get("meaning"):
            add("no_meaning", m["id"], title)
        if not d.get("where") or not d.get("who"):
            add("no_scene", m["id"], title)
        if has_occasion and m["id"] not in used:
            add("unused_moment", m["id"], title)
    for o in bank.live("observation"):
        if not o["confirmed"] and len(o["sources"]) < 2:
            add("thin_observation", o["id"], o["data"].get("statement", o["id"]))

    def num(id_: str) -> tuple[str, int]:
        return id_.rstrip("0123456789"), int(id_[len(id_.rstrip("0123456789")):] or 0)

    out.sort(key=lambda g: (GAP_ORDER.index(g["gap"]), num(g["id"])))
    return out
