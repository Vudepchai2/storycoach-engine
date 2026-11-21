import pytest

from storycoach.memory import create_bank, open_bank
from storycoach.memory.retain import retain

SAID = {"kind": "said", "ref": "sessions/a"}
TAKE = {"kind": "transcript", "ref": "sessions/a/take_03"}
BS = "\\"  # a Windows path separator


@pytest.fixture
def bank(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    retain(store, {"source": SAID, "items": [
        {"type": "moment", "title": "T", "what_happened": "W"}]})
    return store, directory


def claim(key, value, quote="q", **kw):
    return {"type": "claim", "about": "m1", "key": key, "statement": f"{key} is {value}",
            "value": value, "quote": quote, **kw}


def run(store, items, source=SAID):
    return retain(store, {"source": source, "items": items})


def state(directory):
    return open_bank(directory)[1]


def test_same_value_from_new_source_cites_existing_claim(bank):
    store, directory = bank
    run(store, [claim("beta_testers", 30)])
    report = run(store, [claim("beta_testers", 30.0, ref="@c")], TAKE)
    b = state(directory)
    assert report["cited"] == ["c1"] and report["added"] == []
    assert "c2" not in b.records and len(b.records["c1"]["sources"]) == 2
    assert b.claim_status("c1") == "corroborated"


def test_same_ref_twice_is_still_said(bank):
    store, directory = bank
    run(store, [claim("beta_testers", 30)])
    run(store, [claim("beta_testers", 30)])
    assert state(directory).claim_status("c1") == "said"


def test_different_value_opens_conflict(bank):
    store, directory = bank
    run(store, [claim("leads", 100)])
    report = run(store, [claim("leads", 60)])
    assert report["conflicts"] == [{"id": "x1", "about": "m1", "key": "leads",
                                    "claims": ["c1", "c2"], "values": [100, 60]}]
    b = state(directory)
    assert b.claim_status("c1") == b.claim_status("c2") == "conflicted"


def test_unit_difference_conflicts_and_batch_local_match(bank):
    store, _ = bank
    report = run(store, [claim("t", 5, unit="min"), claim("t", 5, unit="min"), claim("t", 5, unit="s")])
    assert report["cited"] == ["c1"] and len(report["conflicts"]) == 1
    assert report["conflicts"][0]["claims"] == ["c1", "c2"]


def test_valueless_claims_cite_on_statement_else_store(bank):
    store, _ = bank
    base = {"type": "claim", "about": "m1", "key": "mood", "quote": "q"}
    run(store, [{**base, "statement": "It was Tense"}])
    report = run(store, [{**base, "statement": "it was tense!"}, {**base, "statement": "calm"}])
    assert report["cited"] == ["c1"] and report["conflicts"] == []
    assert [a["id"] for a in report["added"]] == ["c2"]


def test_resolve_closes_conflict(bank):
    store, directory = bank
    run(store, [claim("leads", 100)])
    run(store, [claim("leads", 60)])
    run(store, [{"op": "resolve", "conflict": "x1", "keep": "c2", "quote": "sixty"}])
    b = state(directory)
    assert b.claim_status("c2") == "confirmed" and b.claim_status("c1") == "retracted"
    assert b.keys_for("m1") == ["leads"]


def test_documented_status_and_imported_moment(tmp_path):
    directory = create_bank(tmp_path, "Ana")
    store = open_bank(directory)[0]
    store.append([{"op": "add", "id": "s1", "type": "source",
                   "data": {"filename": "cv.pdf"}, "source": SAID}])
    doc = {"kind": "document", "ref": "s1"}
    run(store, [{"type": "moment", "title": "T", "what_happened": "W"}], doc)
    run(store, [claim("leads", 100)], doc)
    b = state(directory)
    assert b.moment_status("m1") == "imported" and b.claim_status("c1") == "documented"
    run(store, [{"op": "cite", "id": "m1", "quote": "I did"}])
    assert state(directory).moment_status("m1") == "told"


def test_keys_by_about_in_report(bank):
    store, _ = bank
    report = run(store, [claim("leads", 100), claim("beta_testers", 30)])
    assert report["keys_by_about"]["m1"] == ["beta_testers", "leads"]


def test_same_session_relative_and_absolute_stays_said(bank):
    from storycoach.home import data_home

    store, directory = bank
    run(store, [claim("leads", 100)], {"kind": "said", "ref": "sessions/sam-x"})
    run(store, [claim("leads", 100)], {"kind": "said", "ref": str(data_home() / "sessions" / "sam-x")})
    run(store, [claim("leads", 100)], {"kind": "transcript", "ref": BS.join(["Sessions", "Sam-X", ""])})
    b = state(directory)
    assert [s["ref"] for s in b.records["c1"]["sources"]] == [
        "sessions/sam-x", "sessions/sam-x", "Sessions/Sam-X"]
    assert b.claim_status("c1") == "said"
    run(store, [claim("leads", 100)], {"kind": "transcript", "ref": "sessions/sam-x/take_02"})
    assert state(directory).claim_status("c1") == "corroborated"


def test_refs_outside_the_project_and_document_ids_are_kept(bank):
    from storycoach.memory.schema import canonical_ref

    assert canonical_ref("s1") == "s1" and canonical_ref("import") == "import"
    assert canonical_ref("./sessions//a/") == "sessions/a"
    outside = BS.join(["D:", "elsewhere", "take_01"]) if __import__("os").name == "nt" else "/elsewhere/take_01"
    assert canonical_ref(outside) == outside.replace(BS, "/")
