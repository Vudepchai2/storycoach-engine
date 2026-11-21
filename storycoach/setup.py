"""`storycoach setup`: make the data folder, fetch the speech model once, check the microphone."""
import json
import sys
from datetime import date
from pathlib import Path

from storycoach import home, usage
from storycoach.version import __version__

MODEL_NAME = "small.en"
DOWNLOAD_NOTE = "downloading the speech model (about 500 MB, once)..."


def DOWNLOAD_MODEL() -> None:
    """Fetch the model into the local cache. Tests replace this; they never download."""
    from storycoach.transcribe import resolve_model

    resolve_model(MODEL_NAME)


def MODEL_CACHED():
    """The cached snapshot folder, or None. Any problem counts as not cached."""
    try:
        from storycoach.transcribe import quiet_hub

        quiet_hub()
        from faster_whisper import download_model

        return download_model(MODEL_NAME, local_files_only=True, use_auth_token=False)
    except Exception:  # noqa: BLE001
        return None


def _model_complete(path) -> bool:
    """A snapshot folder can exist after an interrupted download: require the real files."""
    try:
        d = Path(path)
        return all((d / n).is_file() and (d / n).stat().st_size > 0 for n in ("model.bin", "config.json"))
    except (OSError, TypeError, ValueError):
        return False


def _default_query_input_devices() -> str:
    """'ok', 'none' or 'portaudio_missing'. The audio library is imported here, never at module load."""
    try:
        import sounddevice
    except (OSError, ImportError):
        return "portaudio_missing"
    try:
        sounddevice.query_devices(kind="input")
    except (sounddevice.PortAudioError, ValueError):
        return "none"
    except OSError:
        return "portaudio_missing"
    except Exception:  # noqa: BLE001  a driver error must never be a traceback
        return "none"
    return "ok"


QUERY_INPUT_DEVICES = _default_query_input_devices


def _mic() -> str:
    try:
        return QUERY_INPUT_DEVICES()
    except (OSError, ImportError):
        return "portaudio_missing"
    except Exception:  # noqa: BLE001
        return "none"


def _model(skip: bool, log) -> str:
    if skip:
        return "skipped"
    cached = MODEL_CACHED()
    if cached and _model_complete(cached):
        return "ok"
    log(DOWNLOAD_NOTE)
    try:
        DOWNLOAD_MODEL()
    except Exception:  # noqa: BLE001  offline or any download failure: report, never a traceback
        return "missing"
    return "ok"


def run(skip_model: bool, as_json: bool, ack_privacy: bool) -> int:
    def log(msg: str) -> None:
        print(msg, file=sys.stderr if as_json else sys.stdout, flush=True)

    try:
        root = home.ensure_home()
    except OSError as e:
        print(f"Could not create the data folder {home.data_home()}: {e}", file=sys.stderr)
        return 1
    if ack_privacy:
        try:
            home.update_settings(privacy_ack=date.today().isoformat())
        except OSError as e:
            print(f"Could not save the privacy note: {e}", file=sys.stderr)
            return 1
        log("noted")
    state = home.settings_state()[0]
    settings_bad = state in ("unreadable", "damaged")
    usage_on = usage.enabled()
    if usage_on:
        try:
            usage.install_id()
        except OSError as e:
            print(f"Could not save the install id ({type(e).__name__}).", file=sys.stderr)
    model = _model(skip_model, log)
    mic = _mic()
    acked = bool(home.read_settings().get("privacy_ack"))
    if as_json:
        print(json.dumps({"home": str(root), "model": model, "mic": mic, "privacy_ack": acked,
                          "version": __version__}))
        return 0
    from storycoach.record import PORTAUDIO_HINT

    linux = sys.platform.startswith("linux")
    mic_words = {"ok": "ok", "none": "none found", "portaudio_missing": "PortAudio missing"}[mic]
    print("home: ok")
    print(f"model: {model}")
    print(f"mic: {mic_words}")
    print(f"privacy note: {'ok' if acked else 'missing'}")
    if settings_bad:
        print("settings: unreadable")
    elif not usage_on:
        print("usage stats: off")
    if mic == "portaudio_missing" and linux:
        print(PORTAUDIO_HINT)
    nxt = None
    if settings_bad:
        nxt = f"check {home.settings_path()} (it can't be read); fix or move it, then run storycoach setup again"
    elif model == "missing":
        nxt = "connect to the internet and run storycoach setup again to fetch the speech model"
    elif model == "skipped":
        nxt = "run storycoach setup (without --skip-model) to fetch the speech model"
    elif mic == "none":
        nxt = "connect a microphone, then run storycoach setup again"
    elif mic == "portaudio_missing":
        nxt = ("install PortAudio (see above), then run storycoach setup again" if linux
               else "reinstall the sounddevice package, then run storycoach setup again")
    elif not acked:
        nxt = "show the first-run privacy note, then run storycoach setup --ack-privacy"
    if nxt:
        print(f"next: {nxt}")
    return 0


def ack_only() -> int:
    try:
        home.ensure_home()
        home.update_settings(privacy_ack=date.today().isoformat())
    except OSError as e:
        print(f"Could not save the privacy note: {e}", file=sys.stderr)
        return 1
    print("noted")
    return 0
