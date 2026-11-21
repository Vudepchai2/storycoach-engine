import pytest

from storycoach.memory import create_bank, open_bank
from storycoach.memory.retain import BatchError, retain

SAID = {"kind": "said", "ref": "sessions/a"}


@pytest.fixture
def bank(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    return open_bank(directory)[0], directory


def run(store, items, source=SAID):
    return retain(store, {"source": source, "items": items})


def errors_of(store, items, source=SAID):
    with pytest.raises(BatchError) as exc:
        run(store, items, source)
    return exc.value.errors


def test_adds_records_with_handles(bank):
    store, directory = bank
    report = run(store, [
        {"type": "entity", "ref": "@lee", "name": "Lee", "kind": "person"},
        {"type": "moment", "title": "T", "what_happened": "W", "who": ["@lee"]},
    ])
    assert [a["id"] for a in report["added"]] == ["e1", "m1"]
    assert report["cited"] == [] and report["conflicts"] == [] and report["keys_by_about"] == {}
    assert open_bank(directory)[1].records["m1"]["data"]["who"] == ["e1"]


def test_consecutive_ids_within_batch(bank):
    store, _ = bank
    report = run(store, [{"type": "entity", "name": n, "kind": "person"} for n in ("A", "B")])
    assert [a["id"] for a in report["added"]] == ["e1", "e2"]


def test_entity_linking_is_exact_after_normalisation(bank):
    store, directory = bank
    run(store, [{"type": "entity", "name": "Rene", "kind": "person"}])
    report = run(store, [{"type": "entity", "name": "RENE ", "kind": "person",
                          "aliases": ["Rene D."]}])
    assert report["linked"] == [{"name": "RENE ", "id": "e1", "kind": "person", "relation": None}]
    assert report["added"] == []
    b = open_bank(directory)[1]
    assert "e2" not in b.records and "Rene D." in b.records["e1"]["data"]["aliases"]
    assert run(store, [{"type": "entity", "name": "Rena", "kind": "person"}])["added"][0]["id"] == "e2"


def test_linked_handle_resolves_for_later_items(bank):
    store, directory = bank
    run(store, [{"type": "entity", "name": "Rene", "kind": "person"}])
    run(store, [{"type": "entity", "ref": "@f", "name": "rene", "kind": "person"},
                {"type": "moment", "title": "T", "what_happened": "W", "who": ["@f"]}])
    assert open_bank(directory)[1].records["m1"]["data"]["who"] == ["e1"]


def test_who_by_exact_name(bank):
    store, directory = bank
    run(store, [{"type": "entity", "name": "Rene", "kind": "person"}])
    run(store, [{"type": "moment", "title": "T", "what_happened": "W", "who": ["rene"]}])
    assert open_bank(directory)[1].records["m1"]["data"]["who"] == ["e1"]
    assert errors_of(store, [{"type": "moment", "title": "T", "what_happened": "W",
                              "who": ["Bob"]}]) == [
        "item 0: unknown name 'Bob' in who (add the entity first or use its id)"]


def test_bad_batch_writes_nothing_and_lists_all_errors(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"}])
    before = store.events()
    errs = errors_of(store, [
        {"type": "observation", "about": "person", "statement": "s"},
        {"type": "claim", "about": "e1", "key": "k", "statement": "s", "quote": "q"},
        {"type": "moment", "title": "T", "what_happened": "W"},
    ], {"kind": "coach", "ref": "reflect"})
    assert errs == ["item 1: a coach source can only add observations",
                    "item 2: a coach source can only add observations"]
    assert store.events() == before


def test_claim_needs_quote(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"}])
    claim = {"type": "claim", "about": "e1", "key": "k", "statement": "s"}
    assert errors_of(store, [claim]) == ["item 0: claim needs a quote"]
    assert errors_of(store, [{**claim, "quote": "  "}]) == ["item 0: claim needs a quote"]


def test_coach_source_only_adds_observations(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"}])
    coach = {"kind": "coach", "ref": "reflect"}
    run(store, [{"type": "observation", "about": "person", "statement": "s"}], coach)
    assert errors_of(store, [{"type": "moment", "title": "T", "what_happened": "W"}], coach) == [
        "item 0: a coach source can only add observations"]


def test_confirm_needs_said_source(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"}])
    assert errors_of(store, [{"op": "confirm", "id": "e1", "quote": "q"}],
                     {"kind": "transcript", "ref": "takes/1"}) == [
        "item 0: confirm needs a 'said' source"]
    run(store, [{"op": "confirm", "id": "e1", "quote": "q"}])


def test_update_rejects_non_updatable_field(bank):
    store, directory = bank
    run(store, [{"type": "entity", "ref": "@a", "name": "A", "kind": "person"},
                {"type": "claim", "about": "@a", "key": "k", "statement": "s",
                 "value": 1, "quote": "q"}])
    assert errors_of(store, [{"op": "update", "id": "c1", "fields": {"value": 2}}]) == [
        "item 0: unknown field 'value' for claim"]
    run(store, [{"op": "update", "id": "c1", "fields": {"statement": "new"}}])
    assert open_bank(directory)[1].records["c1"]["data"]["statement"] == "new"


def test_other_ops(bank):
    store, directory = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"}])
    run(store, [{"op": "cite", "id": "e1", "quote": "again", "ref": "sessions/b"}])
    run(store, [{"op": "retract", "id": "e1", "reason": "wrong"}])
    rec = open_bank(directory)[1].records["e1"]
    assert rec["sources"][-1]["ref"] == "sessions/b" and rec["retracted"] == "wrong"
    assert errors_of(store, [{"op": "zap", "id": "e1"}]) == ["item 0: unknown op 'zap'"]
    assert errors_of(store, [{"op": "retract", "id": "e9", "reason": "r"}]) == [
        "item 0: unknown id 'e9'"]


def test_required_fields_unknown_type_and_field(bank):
    store, _ = bank
    assert errors_of(store, [{"type": "moment"}, {"type": "blob"},
                             {"type": "entity", "name": "A", "kind": "person", "x": 1}]) == [
        "item 0: moment needs title", "item 0: moment needs what_happened",
        "item 1: unknown type 'blob'", "item 2: unknown field 'x' for entity"]


def test_bad_entity_kind_rejected(bank):
    store, _ = bank
    assert errors_of(store, [{"type": "entity", "name": "A", "kind": "robot"}]) == [
        "item 0: entity kind must be one of event, org, other, person, place, project"]


def test_bad_date_rejected(bank):
    store, _ = bank
    m = {"type": "moment", "title": "T", "what_happened": "W"}
    assert errors_of(store, [{**m, "date": "June 2025"}]) == [
        "item 0: date must be YYYY, YYYY-MM or YYYY-MM-DD"]
    run(store, [{**m, "date": "2025-06"}])


def test_bad_source_kind(bank):
    store, _ = bank
    assert errors_of(store, [], {"kind": "guess", "ref": "x"}) == [
        "source.kind must be one of coach, document, said, transcript"]


def test_document_source_must_be_registered(bank):
    store, directory = bank
    item = {"type": "entity", "name": "A", "kind": "person"}
    doc = {"kind": "document", "ref": "s1"}
    assert errors_of(store, [item], doc) == [
        "source.ref must be a registered source id for a document"]
    store.append([{"op": "add", "id": "s1", "type": "source",
                   "data": {"filename": "cv.pdf", "sha256": "ab", "stored": "sources/ab.pdf"},
                   "source": {"kind": "said", "ref": "import"}}])
    run(store, [item], doc)


def test_malformed_input_is_collected_not_raised(bank):
    store, _ = bank
    ent = {"type": "entity", "name": "A", "kind": "person"}
    for batch, expected in [
        ("x", ["batch must be an object"]),
        ({"source": SAID, "items": "x"}, ["items must be a list"]),
        ({"source": "x", "items": []}, ["source must be an object"]),
        ({"source": {"kind": "document", "ref": ["s1"]}, "items": []},
         ["source.ref must be a registered source id for a document"]),
        ({"source": {"kind": "said", "ref": ["a"]}, "items": []},
         ["source.ref must be a non-empty string"]),
    ]:
        with pytest.raises(BatchError) as exc:
            retain(store, batch)
        assert exc.value.errors == expected
    assert errors_of(store, ["x"]) == ["item 0: must be an object"]
    assert errors_of(store, [{"type": ["a"]}]) == ["item 0: unknown type '['a']'"]
    assert errors_of(store, [{"op": ["a"]}]) == ["item 0: unknown op '['a']'"]
    assert errors_of(store, [{"op": "resolve", "conflict": ["x1"], "keep": "c1", "quote": "q"}]) == [
        "item 0: unknown id '['x1']'"]
    assert errors_of(store, [{**ent, "name": 5}]) == ["item 0: name must be a string"]
    assert errors_of(store, [{**ent, "aliases": [1]}]) == ["item 0: aliases must be strings"]


def test_alias_collisions_rejected(bank):
    store, directory = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"},
                {"type": "entity", "name": "B", "kind": "person"}])
    before = store.events()
    assert errors_of(store, [{"type": "entity", "name": "A", "kind": "person",
                              "aliases": ["B"]}]) == ["item 0: 'B' already names e2"]
    assert errors_of(store, [{"op": "update", "id": "e1", "fields": {"aliases": ["b"]}}]) == [
        "item 0: 'b' already names e2"]
    assert store.events() == before
    run(store, [{"op": "update", "id": "e1", "fields": {"aliases": ["Ay"]}}])


def test_retracted_records_cannot_be_referenced(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "A", "kind": "person"},
                {"type": "entity", "name": "B", "kind": "person"}])
    run(store, [{"op": "retract", "id": "e2", "reason": "oops"}])
    moment = {"type": "moment", "title": "T", "what_happened": "W"}
    assert errors_of(store, [{**moment, "who": ["e2"]}]) == ["item 0: 'e2' was retracted"]
    assert errors_of(store, [
        {"op": "update", "id": "e2", "fields": {"relation": "x"}},
        {"op": "confirm", "id": "e2", "quote": "q"},
        {"op": "cite", "id": "e2", "quote": "q"},
        {"op": "retract", "id": "e2", "reason": "again"},
    ]) == [f"item {i}: 'e2' was retracted" for i in range(4)]


def test_resolve_happy_path(bank):
    store, directory = bank
    run(store, [{"type": "entity", "ref": "@a", "name": "A", "kind": "person"}] + [
        {"type": "claim", "about": "@a", "key": "k", "statement": "s", "value": v, "quote": "q"}
        for v in (1, 2)])
    store.append([{"op": "conflict", "id": "x1", "type": "conflict",
                   "data": {"about": "e1", "key": "k", "claims": ["c1", "c2"]},
                   "source": SAID}])
    run(store, [{"op": "resolve", "conflict": "x1", "keep": "c2", "quote": "it was 2"}])
    b = open_bank(directory)[1]
    assert b.conflicts["x1"]["open"] is False and b.conflicts["x1"]["kept"] == "c2"
    assert b.records["c2"]["confirmed"] == {"quote": "it was 2"}
    assert b.records["c1"]["retracted"] == "superseded by c2"
    assert errors_of(store, [{"op": "resolve", "conflict": "x1", "keep": "c2", "quote": "q"}]) == [
        "item 0: unknown id 'x1'"]


def test_observation_about_is_person_or_telling(bank):
    store, directory = bank
    run(store, [{"type": "moment", "title": "T", "what_happened": "W"}])
    run(store, [{"type": "observation", "about": "person", "statement": "S", "moments": ["m1"]},
                {"type": "observation", "about": "telling", "statement": "S2"}])
    b = open_bank(directory)[1]
    assert b.records["o1"]["data"]["about"] == "person"
    assert b.records["o1"]["data"]["moments"] == ["m1"]
    errs = errors_of(store, [{"type": "observation", "about": "m1", "statement": "S"}])
    assert errs == ["item 0: observation about must be 'person' or 'telling'"]


def test_field_types_are_checked_and_nothing_is_written(bank):
    store, directory = bank
    run(store, [{"type": "moment", "title": "T", "what_happened": "W"}])
    before = store.events()
    claim = {"type": "claim", "about": "m1", "key": "leads", "statement": "s", "quote": "q"}
    moment = {"type": "moment", "title": "T", "what_happened": "W"}
    obs = {"type": "observation", "about": "person", "statement": "s"}
    for item, msg in [
        ({**claim, "key": ["leads"]}, "key must be a string"),
        ({**claim, "statement": 5}, "statement must be a string"),
        ({**claim, "quote": ["q"]}, "quote must be a string"),
        ({**claim, "unit": 5}, "unit must be a string"),
        ({**claim, "value": "100"}, "value must be a number"),
        ({**claim, "value": True}, "value must be a number"),
        ({**claim, "value": float("nan")}, "value must be a number"),
        ({**moment, "title": {"t": 1}}, "title must be a string"),
        ({**moment, "where": ["Leeds"]}, "where must be a string"),
        ({**moment, "quotes": [1]}, "quotes must be strings"),
        ({**moment, "date": 2025}, "date must be YYYY, YYYY-MM or YYYY-MM-DD"),
        ({"type": "entity", "name": "A", "kind": "person", "relation": ["x"]}, "relation must be a string"),
        ({"type": "occasion", "name": "n", "debrief": "it went well"}, "debrief must be a list"),
        ({"type": "occasion", "name": "n", "debrief": [3]}, "debrief must be strings"),
        ({"type": "occasion", "name": "n", "outcome": {"a": 1}}, "outcome must be a string"),
        ({**obs, "evidence": ["q"]}, "evidence must be a list of {ref, quote} strings"),
        ({**obs, "evidence": [{"ref": "r"}]}, "evidence must be a list of {ref, quote} strings"),
        ({"op": "update", "id": "m1", "fields": {"meaning": 3}}, "meaning must be a string"),
        ({"op": "confirm", "id": "m1", "quote": ["q"]}, "quote must be a string"),
        ({"op": "retract", "id": "m1", "reason": 1}, "reason must be a string"),
        ({"op": "cite", "id": "m1", "quote": "q", "ref": ["x"]}, "ref must be a non-empty string"),
    ]:
        assert errors_of(store, [item]) == [f"item 0: {msg}"], item
    assert store.events() == before
    run(store, [{**claim, "value": 100}])
    report = run(store, [{**claim, "value": 100.0}])
    assert report["cited"] == ["c1"] and report["keys_by_about"] == {"m1": ["leads"]}


def test_source_ref_required_for_every_kind(bank):
    store, _ = bank
    moment = {"type": "moment", "title": "T", "what_happened": "W"}
    obs = {"type": "observation", "about": "person", "statement": "s"}
    for source, item in [({"kind": "said"}, moment), ({"kind": "transcript", "ref": " "}, moment),
                         ({"kind": "coach"}, obs), ({"kind": "said", "ref": 3}, moment)]:
        assert errors_of(store, [item], source) == ["source.ref must be a non-empty string"], source


def test_linked_report_names_the_existing_kind_and_relation(bank):
    store, _ = bank
    run(store, [{"type": "entity", "name": "Sam", "kind": "person", "relation": "investor"}])
    report = run(store, [{"type": "entity", "name": "sam", "kind": "person", "relation": "co-founder"}])
    assert report["linked"] == [{"name": "sam", "id": "e1", "kind": "person", "relation": "investor"}]
