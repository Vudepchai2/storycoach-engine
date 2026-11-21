import re

from storycoach.models import Pause, Word

FILLERS = {"um", "umm", "uh", "uhm", "er", "erm", "ah", "hmm"}
_VOWEL_GROUPS = re.compile(r"[aeiouy]+")


def _clean(text: str) -> str:
    return re.sub(r"[^a-z']", "", text.lower())


def speech_bounds(words: list[Word]) -> tuple[float, float]:
    """Start of the first word and end of the last word (excludes lead/tail silence)."""
    return (words[0].start, words[-1].end)


def find_pauses(words: list[Word], min_gap: float = 0.25) -> list[Pause]:
    pauses = []
    for i in range(len(words) - 1):
        gap = words[i + 1].start - words[i].end
        if gap >= min_gap - 1e-9:
            pauses.append(Pause(after_word=i, start=words[i].end, end=words[i + 1].start))
    return pauses


def find_fillers(words: list[Word]) -> list[int]:
    return [i for i, w in enumerate(words) if _clean(w.text) in FILLERS]


_NUM_SUFFIX = {"%": 2, "$": 2, "k": 1, "m": 2, "b": 2}  # percent, dollars, thousand, million, billion


def _number_syllables(token: str) -> int:
    """Rough spoken-syllable estimate for numerals like 2021, 40,000, 40%, $5M."""
    digits = re.sub(r"\D", "", token)
    n = max(1, round(len(digits) * 1.3)) if digits else 0
    n += sum(_NUM_SUFFIX.get(c, 0) for c in token.lower() if not c.isdigit() and c not in ",.")
    return n


def count_syllables(word: str) -> int:
    if any(c.isdigit() for c in word):
        return _number_syllables(word)
    w = _clean(word).replace("'", "")
    if not w:
        return 0
    n = len(_VOWEL_GROUPS.findall(w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and n > 1:
        n -= 1
    return max(n, 1)
