import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

LABELS = {"hook", "context", "complication", "turn", "resolution", "ask", "other"}


class BeatsError(ValueError):
    pass


@dataclass
class Beat:
    label: str
    start_word: int
    end_word: int  # inclusive


@dataclass
class KeyLine:
    start_word: int
    end_word: int  # inclusive
    note: str = ""


@dataclass
class Beats:
    beats: list[Beat]
    key_lines: list[KeyLine] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"beats": [asdict(b) for b in self.beats], "key_lines": [asdict(k) for k in self.key_lines]}


def validate(beats: Beats, n_words: int) -> list[str]:
    errors: list[str] = []
    last = n_words - 1

    def is_index(v) -> bool:
        return isinstance(v, int) and not isinstance(v, bool)

    bad = [v for b in beats.beats for v in (b.start_word, b.end_word) if not is_index(v)]
    bad += [v for k in beats.key_lines for v in (k.start_word, k.end_word) if not is_index(v)]
    if bad:
        return [f"word index {v!r} must be a whole number (no quotes, decimals or true/false)" for v in bad]

    def in_range(i: int) -> bool:
        if not 0 <= i <= last:
            errors.append(f"word index {i} out of range (0-{last})")
            return False
        return True

    for b in beats.beats:
        if b.label not in LABELS:
            errors.append(f"unknown label '{b.label}' (allowed: {', '.join(sorted(LABELS))})")
        in_range(b.start_word)
        in_range(b.end_word)
        if b.end_word < b.start_word:
            errors.append(f"beat '{b.label}' ends (word {b.end_word}) before it starts (word {b.start_word})")

    ordered = sorted(beats.beats, key=lambda b: b.start_word)
    if not ordered or ordered[0].start_word != 0 or max(b.end_word for b in ordered) != last:
        errors.append(f"beats must cover all words 0-{last}")
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start_word <= prev.end_word:
            errors.append(f"overlap at word {nxt.start_word}")
        elif nxt.start_word > prev.end_word + 1:
            errors.append(f"gap: words {prev.end_word + 1}-{nxt.start_word - 1} not in any beat")

    for k in beats.key_lines:
        if not (0 <= k.start_word <= k.end_word <= last):
            errors.append(f"key line {k.start_word}-{k.end_word} is outside words 0-{last} or reversed")
    return errors


def load_beats(path: Path, n_words: int) -> Beats:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        beats = Beats(
            beats=[Beat(**b) for b in raw["beats"]],
            key_lines=[KeyLine(**k) for k in raw.get("key_lines", [])],
        )
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise BeatsError(f"beats.json is malformed: {e}") from e
    errors = validate(beats, n_words)
    if errors:
        raise BeatsError("beats.json problems:\n- " + "\n- ".join(errors))
    return beats
