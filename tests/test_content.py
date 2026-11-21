import json

import pytest

from storycoach.beats import Beat, Beats
from storycoach.content import content_counts, word_shares
from storycoach.features import compute_features, observations
from storycoach.models import Acoustics, Transcript, Word


def _t(text):
    words = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(text.split())]
    return Transcript(words=words, text=text)


def test_pronouns_ignore_case_and_punctuation():
    c = content_counts(_t("I built it. We shipped, and my team, our users and I'm proud. Us too, me."))
    assert c["first_person_singular"] == 4  # I, my, I'm, me
    assert c["first_person_plural"] == 3  # We, our, Us


def test_numbers_digits_and_words():
    c = content_counts(_t("We got 100 leads, 30 testers, €1m raised and ten companies in two weeks."))
    assert c["number_mentions"] == 5


def test_connectives_counted_by_word():
    c = content_counts(_t("But then, because it failed, so we pivoted. Instead we built, but slowly."))
    assert c["connectives"] == {"but": 2, "because": 1, "so": 1, "instead": 1}


def test_habitual_and_hypothetical():
    c = content_counts(_t("I usually start. Whenever it breaks I'd fix it. I would always ask."))
    assert c["habitual_or_hypothetical"] == 5  # usually, whenever, I'd, would, always


def test_word_count():
    assert content_counts(_t("one two three"))["word_count"] == 3


def test_word_shares_sum_to_one():
    beats = Beats([Beat("hook", 0, 1), Beat("context", 2, 7), Beat("turn", 8, 9)])
    assert word_shares(beats, 10) == [0.2, 0.6, 0.2]


def _ac(end):
    n = int(end * 100) + 1
    return Acoustics(times=[i * 0.01 for i in range(n)], f0_hz=[180.0] * n, intensity_db=[65.0] * n)


def test_features_include_content_and_beat_share():
    t = _t("I needed help but nobody came so I built it in 3 days")
    beats = Beats([Beat("hook", 0, 3), Beat("turn", 4, 12)])
    f = compute_features(t, _ac(6), beats, None)
    assert f["content"]["first_person_singular"] == 2
    assert [b["word_share"] for b in f["beats"]] == pytest.approx([4 / 13, 9 / 13], abs=0.01)
    json.dumps(f, allow_nan=False)


def test_observation_names_biggest_beat_share():
    t = _t(" ".join(["w"] * 20))
    beats = Beats([Beat("hook", 0, 1), Beat("context", 2, 15), Beat("turn", 16, 19)])
    obs = observations(compute_features(t, _ac(9), beats, None))
    share = [o for o in obs if "of your words" in o]
    assert share and "context" in share[0] and "70%" in share[0]
