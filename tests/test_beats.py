import json

import pytest

from storycoach.beats import BeatsError, load_beats


def _write(tmp_path, beats, key_lines=()):
    p = tmp_path / "beats.json"
    p.write_text(json.dumps({"beats": beats, "key_lines": list(key_lines)}))
    return p


B = lambda label, s, e: {"label": label, "start_word": s, "end_word": e}


@pytest.mark.parametrize(
    "beats,key_lines,fragment",
    [
        ([B("hook", 0, 4), B("turn", 7, 29)], [], "gap: words 5-6 not in any beat"),
        ([B("hook", 0, 7), B("turn", 7, 29)], [], "overlap at word 7"),
        ([B("hook", 0, 9), B("turn", 10, 40)], [], "word index 40 out of range (0-29)"),
        ([B("climax", 0, 29)], [], "unknown label 'climax'"),
        ([B("hook", 2, 29)], [], "beats must cover all words"),
        ([B("hook", 0, 29)], [{"start_word": 25, "end_word": 31, "note": ""}], "key line"),
    ],
)
def test_beats_validation_errors(tmp_path, beats, key_lines, fragment):
    with pytest.raises(BeatsError) as e:
        load_beats(_write(tmp_path, beats, key_lines), n_words=30)
    assert fragment in str(e.value)


def test_valid_beats_load(tmp_path):
    p = _write(tmp_path, [B("hook", 0, 9), B("turn", 10, 19), B("resolution", 20, 29)],
               [{"start_word": 12, "end_word": 15, "note": "the moment"}])
    b = load_beats(p, n_words=30)
    assert [x.label for x in b.beats] == ["hook", "turn", "resolution"]
    assert b.key_lines[0].start_word == 12 and b.key_lines[0].note == "the moment"


@pytest.mark.parametrize("bad", ["5", 5.0, True])
def test_non_integer_indices_rejected(tmp_path, bad):
    with pytest.raises(BeatsError, match="must be a whole number"):
        load_beats(_write(tmp_path, [B("hook", 0, bad), B("turn", 6, 29)]), n_words=30)


def test_nested_beat_reports_overlap_not_coverage(tmp_path):
    with pytest.raises(BeatsError) as e:
        load_beats(_write(tmp_path, [B("hook", 0, 29), B("turn", 2, 4)]), n_words=30)
    assert "overlap at word 2" in str(e.value) and "cover all words" not in str(e.value)
