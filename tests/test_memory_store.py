import json

import pytest

from storycoach.memory import create_bank, open_bank
from storycoach.memory.bank import Bank
from storycoach.memory.schema import normalise_name
from storycoach.memory.store import FileStore

SRC = {"kind": "said", "ref": "sessions/a", "at": "2026-01-01"}


def ev(seq, op, id, type=None, data=None, source=SRC):
    return {"seq": seq, "at": "t", "op": op, "id": id, "type": type,
            "data": data or {}, "source": source}


def test_normalise_name():
    assert normalise_name("  RENÉ  Dupont. ") == "rene dupont"


def test_append_assigns_seq_and_roundtrips(tmp_path):
    FileStore(tmp_path).append([ev(0, "add", "e1", "entity"), ev(0, "add", "e2", "entity")])
    events = FileStore(tmp_path).events()
    assert [e["seq"] for e in events] == [1, 2]
    assert all(e["at"].endswith("+00:00") for e in events)


def test_truncated_last_line_is_ignored_with_warning(tmp_path):
    good = json.dumps(ev(1, "add", "e1", "entity"))
    (tmp_path / "log.jsonl").write_text(good + '\n{"seq": 2, "op": "ad', encoding="utf-8")
    store = FileStore(tmp_path)
    assert len(store.events()) == 1
    assert "truncated" in store.warnings[0]


def test_corrupt_middle_line_raises(tmp_path):
    good = json.dumps(ev(1, "add", "e1", "entity"))
    (tmp_path / "log.jsonl").write_text(good + "\ngarbage\n" + good + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        FileStore(tmp_path).events()


def test_bank_rebuilds_records_and_ids():
    bank = Bank.from_events([
        ev(1, "add", "e1", "entity", {"name": "Lee", "kind": "person"}),
        ev(2, "add", "m1", "moment", {"title": "A", "what_happened": "x"}),
    ])
    assert bank.next_id("entity") == "e2"
    assert bank.next_id("occasion") == "oc1"
    assert bank.records["m1"]["sources"] == [SRC]


def test_update_keeps_history():
    bank = Bank.from_events([
        ev(1, "add", "m1", "moment", {"title": "A", "what_happened": "x"}),
        ev(2, "update", "m1", None, {"title": "B"}),
    ])
    assert bank.records["m1"]["data"]["title"] == "B"
    assert bank.records["m1"]["history"][0]["title"] == "A"


def test_cite_and_occasion_numbering():
    bank = Bank.from_events([
        ev(1, "add", "o1", "observation", {"about": "person", "statement": "s"}),
        ev(2, "add", "oc1", "occasion", {"name": "n"}),
        ev(3, "cite", "o1", None, {"quote": "q", "ref": "r2"}),
    ])
    assert bank.next_id("observation") == "o2"
    assert bank.next_id("occasion") == "oc2"
    assert bank.records["o1"]["sources"][1] == {"kind": "said", "ref": "r2", "at": "2026-01-01", "quote": "q"}


def test_resolve_confirms_kept_and_retracts_others():
    claim = {"about": "m1", "key": "k", "statement": "s", "quote": "q"}
    bank = Bank.from_events([
        ev(1, "add", "c1", "claim", {**claim, "value": 100}),
        ev(2, "add", "c2", "claim", {**claim, "value": 60}),
        ev(3, "conflict", "x1", None, {"about": "m1", "key": "k", "claims": ["c1", "c2"]}),
        ev(4, "resolve", "x1", None, {"keep": "c2", "quote": "sixty"}),
    ])
    assert bank.records["c1"]["retracted"] == "superseded by c2"
    assert bank.records["c1"]["superseded_by"] == "c2"
    assert bank.records["c2"]["confirmed"]["quote"] == "sixty"
    assert bank.conflicts["x1"]["open"] is False
    assert bank.conflicts["x1"]["kept"] == "c2"
    assert [r["id"] for r in bank.live("claim")] == ["c2"]


def test_open_bank_without_person_json_names_init(tmp_path):
    with pytest.raises(FileNotFoundError, match="memory init"):
        open_bank(tmp_path)


def test_create_and_open_bank(tmp_path):
    d = create_bank(tmp_path, "Sam Rivera")
    assert (d / "person.json").exists() and (d / "sources").is_dir() and (d / "pages").is_dir()
    with pytest.raises(FileExistsError):
        create_bank(tmp_path, "Sam Rivera")
    store, bank = open_bank(d)
    assert bank.records == {}


def test_cut_inside_multibyte_char_is_a_truncation(tmp_path):
    from storycoach.memory.retain import retain

    directory = create_bank(tmp_path, "Ana")
    FileStore(directory).append([ev(0, "add", "m1", "moment", {"title": "René’s call", "what_happened": "w"})])
    log = directory / "log.jsonl"
    partial = json.dumps(ev(2, "add", "m2", "moment", {"title": "it’s"}), ensure_ascii=False).encode("utf-8")
    log.write_bytes(log.read_bytes() + partial[:partial.index("’".encode("utf-8")) + 1])
    store, bank = open_bank(directory)
    assert list(bank.records) == ["m1"] and "truncated" in store.warnings[0]
    retain(store, {"source": {"kind": "said", "ref": "sessions/a"},
                   "items": [{"type": "moment", "title": "T", "what_happened": "W"}]})
    events = FileStore(directory).events()
    assert [e["id"] for e in events] == ["m1", "m2"] and [e["seq"] for e in events] == [1, 2]
    assert events[0]["data"]["title"] == "René’s call"


def test_bad_bytes_in_middle_line_raise(tmp_path):
    good = json.dumps(ev(1, "add", "e1", "entity")).encode("utf-8")
    (tmp_path / "log.jsonl").write_bytes(good + b'\n{"x": "\xe2"}\n' + good + b"\n")
    with pytest.raises(ValueError, match="line 2"):
        FileStore(tmp_path).events()


def test_append_after_truncated_tail_recovers(tmp_path):
    good = json.dumps(ev(1, "add", "e1", "entity"))
    (tmp_path / "log.jsonl").write_text(good + '\n{"seq": 2, "op": "ad', encoding="utf-8")
    store = FileStore(tmp_path)
    store.append([ev(0, "add", "e2", "entity")])
    assert "truncated" in store.warnings[0]
    events = FileStore(tmp_path).events()
    assert [e["id"] for e in events] == ["e1", "e2"]
    assert [e["seq"] for e in events] == [1, 2]
