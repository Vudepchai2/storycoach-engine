"""Where the coach keeps everything personal: one folder outside any repo."""
import json
import os
from pathlib import Path

README = """This is your Storytelling Coach folder.

sessions   your coaching sessions and recorded takes
people     the memory kept for each person
usage      local counts of how the coach is used
reference  measurements from talks you added for comparison
practice   practice material

Nothing in this folder is uploaded by the coach.
"""


def data_home() -> Path:
    env = os.environ.get("STORYCOACH_HOME")
    return Path(env) if env else Path.home() / "StorytellingCoach"


def sessions_dir() -> Path:
    return data_home() / "sessions"


def people_dir() -> Path:
    return data_home() / "people"


def usage_dir() -> Path:
    return data_home() / "usage"


def reference_dir() -> Path:
    return data_home() / "reference"


def practice_dir() -> Path:
    return data_home() / "practice"


def settings_path() -> Path:
    return data_home() / "settings.json"


def ensure_home() -> Path:
    root = data_home()
    for d in (sessions_dir(), people_dir(), usage_dir(), reference_dir(), practice_dir()):
        d.mkdir(parents=True, exist_ok=True)
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8", newline="\n")
    return root


def settings_state() -> tuple[str, dict]:
    """(state, data): state is missing, ok, unreadable (the file exists but cannot be read) or damaged."""
    try:
        text = settings_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing", {}
    except UnicodeDecodeError:
        return "damaged", {}
    except OSError:
        return "unreadable", {}
    try:
        data = json.loads(text)
    except ValueError:
        return "damaged", {}
    return ("ok", data) if isinstance(data, dict) else ("damaged", {})


def read_settings() -> dict:
    """settings.json as a dict; empty when it is missing, unreadable or damaged."""
    return settings_state()[1]


def update_settings(**changes) -> dict:
    """Merge changes into settings.json, keeping every other key.

    An unreadable file raises and is left untouched. A damaged one is moved aside to a unique
    settings.json.damaged-<timestamp> name, never over an earlier copy.
    """
    import time

    path = settings_path()
    state, current = settings_state()
    if state == "unreadable":
        raise OSError(f"cannot read {path}; leaving it untouched")
    if state == "damaged":
        stamp = time.strftime("%Y%m%d-%H%M%S")
        n = 0
        while True:
            aside = path.with_name(f"settings.json.damaged-{stamp}" + (f"-{n}" if n else ""))
            if not aside.exists():
                break
            n += 1
        path.rename(aside)
    current = {**current, **changes}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"settings.json.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(current, indent=2), encoding="utf-8", newline="\n")
    tmp.replace(path)
    return current
