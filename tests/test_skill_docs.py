from pathlib import Path

import pytest

from storycoach.memory.recall import GAP_SECTIONS

# The skill lives in the plugin; in the engine-only repo it is absent and these checks skip.
SKILL = Path(__file__).resolve().parents[2] / "plugin" / "plugins" / "storytelling-coach" / "skills" / "storytelling-coach"
pytestmark = pytest.mark.skipif(not SKILL.is_dir(), reason="the plugin skill is not in this checkout")


def test_gap_sections_exist_in_questions():
    text = (SKILL / "references" / "questions.md").read_text(encoding="utf-8")
    headings = {line[3:].strip() for line in text.splitlines() if line.startswith("## ")}
    missing = sorted(set(GAP_SECTIONS.values()) - headings)
    assert not missing, f"questions.md lacks headings: {missing}"


def test_skill_mentions_memory_commands():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("memory brief", "memory gaps", "memory retain", "--occasion"):
        assert needle in text, needle


def test_memory_doc_batches_retain_cleanly_in_order(tmp_path):
    import json
    import re

    from storycoach.memory import create_bank, open_bank
    from storycoach.memory.retain import retain

    text = (SKILL / "references" / "memory.md").read_text(encoding="utf-8")
    batches = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.S)]
    assert len(batches) >= 4
    store = open_bank(create_bank(tmp_path, "Sam"))[0]
    reports = [retain(store, b) for b in batches]
    assert reports[1]["conflicts"][0]["id"] == "x1"
    assert reports[1]["conflicts"][0]["claims"] == ["c1", "c3"]
    bank = open_bank(store.path.parent)[1]
    assert not any(c["open"] for c in bank.conflicts.values())
    from storycoach.memory.schema import normalise_name

    for c in bank.records.values():  # a claim's number and unit are the person's own words
        d = c["data"]
        if c["type"] == "claim" and "value" in d:
            quote = normalise_name(d["quote"])
            assert str(d["value"]) in quote and normalise_name(d["unit"]) in quote, d


def test_skill_asks_memory_consent_before_new_in_operator_mode():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    step = text.split("**Operator mode:**", 2)[2].split("\n4.", 1)[0]
    assert step.index("memory") < step.index("`storycoach new ")
    assert "--person" in step
