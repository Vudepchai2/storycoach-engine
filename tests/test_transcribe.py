import sys

import pytest

from storycoach.transcribe import NoSpeechError, transcribe


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows System.Speech")
def test_transcribe_returns_timed_words(tts_wav):
    t = transcribe(tts_wav("The first customer called me at midnight."))
    assert "customer" in t.text.lower()
    assert all(w.end >= w.start for w in t.words)
    assert t.words == sorted(t.words, key=lambda w: w.start)


@pytest.mark.slow
def test_no_speech_raises(silence_wav):
    with pytest.raises(NoSpeechError):
        transcribe(silence_wav(3.0))


def test_model_is_resolved_offline_first(monkeypatch):
    import faster_whisper.utils as fw
    from storycoach import transcribe as tr

    calls = []

    def fake(size, **kw):
        calls.append(kw)
        return "/cache/model"

    monkeypatch.setattr(fw, "download_model", fake)
    assert tr.resolve_model("small.en") == "/cache/model"
    assert len(calls) == 1 and calls[0]["local_files_only"] is True and calls[0]["use_auth_token"] is False


def test_network_download_only_after_cache_miss(monkeypatch):
    import faster_whisper.utils as fw
    from storycoach import transcribe as tr

    calls = []

    def fake(size, **kw):
        calls.append(kw)
        if kw.get("local_files_only"):
            raise RuntimeError("not cached")
        return "/fresh/model"

    monkeypatch.setattr(fw, "download_model", fake)
    assert tr.resolve_model("small.en") == "/fresh/model"
    assert [bool(c.get("local_files_only")) for c in calls] == [True, False]
    assert all(c["use_auth_token"] is False for c in calls)


def test_hub_token_and_telemetry_are_off(monkeypatch):
    from storycoach import transcribe as tr

    monkeypatch.delenv("HF_HUB_DISABLE_IMPLICIT_TOKEN", raising=False)
    monkeypatch.delenv("HF_HUB_DISABLE_TELEMETRY", raising=False)
    tr.quiet_hub()
    import os

    assert os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1" and os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
