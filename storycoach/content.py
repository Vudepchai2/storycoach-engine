"""Countable content signals from the transcript. Counts only: no scores, no targets.

What each count is for, and what not to do with it: the plugin skill's references/content.md
"""
import re

from storycoach.beats import Beats
from storycoach.models import Transcript

SINGULAR = {"i", "me", "my", "mine", "myself", "i'm", "i've", "i'd", "i'll"}
PLURAL = {"we", "us", "our", "ours", "ourselves", "we're", "we've", "we'd", "we'll"}
CONNECTIVES = ["because", "so", "but", "therefore", "instead"]
HABITUAL = {"usually", "always", "whenever", "typically", "normally", "often", "would", "i'd", "we'd"}
NUMBER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "hundreds", "thousand", "thousands", "million", "millions", "billion", "dozen", "percent",
}


def _norm(token: str) -> str:
    return token.lower().replace("’", "'").strip(".,!?;:\"()[]-–—…")


def content_counts(t: Transcript) -> dict:
    tokens = [_norm(w.text) for w in t.words]
    conn = {c: tokens.count(c) for c in CONNECTIVES}
    return {
        "word_count": len(t.words),
        "first_person_singular": sum(tok in SINGULAR for tok in tokens),
        "first_person_plural": sum(tok in PLURAL for tok in tokens),
        "number_mentions": sum(bool(re.search(r"\d", tok)) or tok in NUMBER_WORDS for tok in tokens),
        "connectives": {c: n for c, n in conn.items() if n},
        "habitual_or_hypothetical": sum(tok in HABITUAL for tok in tokens),
    }


def word_shares(beats: Beats, n_words: int) -> list[float]:
    return [round((b.end_word - b.start_word + 1) / n_words, 3) for b in beats.beats]
