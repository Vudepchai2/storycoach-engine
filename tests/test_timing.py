from storycoach.models import Word
from storycoach.timing import count_syllables, find_fillers, find_pauses, speech_bounds

W = lambda t, s, e: Word(t, s, e)
words = [W("So,", 1.0, 1.2), W("um", 1.3, 1.5), W("it", 2.0, 2.1), W("started.", 2.15, 2.6)]


def test_speech_bounds():
    assert speech_bounds(words) == (1.0, 2.6)


def test_find_pauses_threshold():
    p = find_pauses(words)
    assert [(x.after_word, round(x.end - x.start, 2)) for x in p] == [(1, 0.5)]


def test_find_fillers_strips_punct():
    assert find_fillers([W("Um,", 0, .1), W("hmm.", .2, .3), W("like", .4, .5)]) == [0, 1]


def test_count_syllables():
    assert [count_syllables(w) for w in ["customer", "the", "midnight", "42"]] == [3, 1, 2, 3]


def test_digits_count_syllables():
    assert count_syllables("2021") >= 3
    assert count_syllables("40%") >= 3
    assert count_syllables("$5M") >= 3
