import pytest

from storycoach.memory import create_bank, open_bank
from storycoach.memory.recall import GAP_SECTIONS, brief, gaps, recall
from storycoach.memory.retain import retain

SAID = {"kind": "said", "ref": "sessions/a"}
COACH = {"kind": "coach", "ref": "sessions/a"}


def run(store, items, source=SAID):
    return retain(store, {"source": source, "items": items})


@pytest.fixture
def fixture(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    run(store, [
        {"type": "entity", "name": "Lee", "kind": "person", "relation": "co-founder"},
        {"type": "moment", "title": "Pilot launch", "when": "May 2025", "date": "2025-05",
         "where": "Leeds", "who": ["Lee"], "what_happened": "We convert 30 builders",
         "what_changed": "Trust grew", "meaning": "Proof"},
        {"type": "moment", "title": "Early doubts", "what_happened": "Nobody replied", "meaning": "Doubt"},
        {"type": "claim", "about": "m1", "key": "leads", "statement": "100 leads",
         "value": 100, "quote": "100"},
    ])
    run(store, [{"type": "claim", "about": "m1", "key": "leads", "statement": "60 leads",
                 "value": 60, "quote": "60"}])
    run(store, [{"type": "observation", "about": "person",
                 "statement": "Starts with numbers"}], COACH)
    run(store, [{"type": "occasion", "name": "Demo day", "uses": ["m1"]}])
    return open_bank(directory)[1]


def test_brief_sections_and_timeline_order(fixture):
    out = brief(fixture, "Ana")
    heads = ["# Ana", "## Themes", "## Timeline", "## People", "## Open conflicts", "## Gaps"]
    pos = [out.index(h) for h in heads]
    assert pos == sorted(pos)
    assert out.index("[m1]") < out.index("[m2]")
    assert "(coach's reading)" in out
    assert "open_conflict: 1" in out
    assert "- [x1] m1.leads: c1=100 vs c2=60" in out


def test_brief_lines_are_capped(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    run(store, [{"type": "moment", "title": "T" * 300, "what_happened": "w"}])
    out = brief(open_bank(directory)[1], "Ana")
    assert all(len(line) <= 120 for line in out.splitlines())


def test_recall_query_matches_word_stems(fixture):
    res = recall(fixture, query="converted builders")
    assert res[0]["id"] == "m1" and res[0]["status"] == "told"


def test_recall_by_entity_name(fixture):
    ids = {r["id"] for r in recall(fixture, entity="lee")}
    assert {"m1", "e1"} <= ids
    assert "m2" not in ids


def test_recall_since_and_type(fixture):
    assert [r["id"] for r in recall(fixture, type="moment", since="2025-01")] == ["m1"]


def test_gaps_order_and_sections(fixture):
    gs = gaps(fixture)
    assert gs[0]["gap"] == "open_conflict"
    assert gs[0]["question_section"] == "Recall: checking a number"
    assert gs[0]["id"] == "x1"
    m2 = [g["gap"] for g in gs if g["id"] == "m2"]
    assert m2 == ["no_change", "no_scene", "unused_moment"]
    assert GAP_SECTIONS["no_scene"] == "Capture — origin, audience, moments"


def _section(out, head):
    rest = out.split(head + "\n", 1)[1]
    return rest.split("\n## ", 1)[0]


def test_brief_shows_telling_entity_claims_status_and_occasions(tmp_path):
    directory = create_bank(tmp_path, "Ana " + "N" * 200)
    store = open_bank(directory)[0]
    run(store, [
        {"type": "entity", "ref": "@lee", "name": "Lee", "kind": "person", "relation": "co-founder"},
        {"type": "moment", "ref": "@m", "title": "Pilot\nlaunch", "what_happened": "W"},
        {"type": "claim", "about": "@m", "key": "leads", "statement": "100 leads", "value": 100,
         "unit": "leads", "quote": "100 leads"},
        {"type": "claim", "about": "@m", "key": "beta_testers", "statement": "30 testers", "value": 30,
         "unit": "beta testers", "quote": "30 beta testers"},
        {"type": "claim", "about": "@lee", "key": "years_known", "statement": "ten years", "value": 10,
         "unit": "years", "quote": "ten years"},
        {"type": "occasion", "name": "Demo day", "date": "2025-06", "outcome": "got in,\n  next round"},
    ])
    run(store, [{"type": "claim", "about": "m1", "key": "beta_testers", "statement": "30 testers",
                 "value": 30, "unit": "beta testers", "quote": "thirty"}],
        {"kind": "transcript", "ref": "sessions/a/take_02"})
    run(store, [{"type": "observation", "about": "telling", "statement": "Rushes the end"}], COACH)
    out = brief(open_bank(directory)[1], "Ana " + "N" * 200)
    heads = ["## Themes", "## How they tell it", "## Timeline", "## People", "## Occasions",
             "## Open conflicts", "## Gaps"]
    pos = [out.index("\n" + h + "\n") for h in heads]
    assert pos == sorted(pos)
    assert "- [o1] Rushes the end (0 evidence) (coach's reading)" in _section(out, "## How they tell it")
    assert _section(out, "## Themes").strip() == "- none"
    timeline = _section(out, "## Timeline")
    assert "- [m1] Pilot launch · told · leads=100, beta_testers=30 (corroborated)" in timeline
    assert "- [e1] Lee (person) — co-founder · years_known=10 years" in _section(out, "## People")
    assert "- [oc1] Demo day (2025-06) · got in, next round" in _section(out, "## Occasions")
    assert all(len(line) <= 120 for line in out.splitlines())


def test_confirmed_observation_leaves_gaps_and_counts_its_evidence(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    ev = [{"ref": f"sessions/a/take_0{i}", "quote": f"q{i}"} for i in (1, 2, 3)]
    run(store, [{"type": "observation", "about": "person", "statement": "Builds for others",
                 "evidence": ev}], COACH)
    run(store, [{"type": "observation", "about": "person", "statement": "Thin one"}], COACH)
    assert [g["id"] for g in gaps(open_bank(directory)[1]) if g["gap"] == "thin_observation"] == ["o1", "o2"]
    run(store, [{"op": "confirm", "id": "o1", "quote": "yes, that's me"}])
    run(store, [{"op": "cite", "id": "o1", "quote": "again", "ref": "sessions/b"}])
    b = open_bank(directory)[1]
    assert [g["id"] for g in gaps(b) if g["gap"] == "thin_observation"] == ["o2"]
    out = brief(b, "Ana")
    assert "- [o1] Builds for others (4 evidence)\n" in out


def test_long_observation_keeps_its_evidence_and_reading_label(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    run(store, [{"type": "observation", "about": "telling", "statement": "word " * 60}], COACH)
    line = [x for x in brief(open_bank(directory)[1], "Ana").splitlines() if x.startswith("- [o1]")][0]
    assert len(line) <= 120 and line.endswith("… (0 evidence) (coach's reading)")
