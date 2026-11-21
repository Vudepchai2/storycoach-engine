import json
import re
import sys
from pathlib import Path

from storycoach.scenarios import SCENARIOS

CONSENT_MESSAGES = {
    "recording": "Consent to record not given for this session.",
    "blind_listeners": "Consent for blind listeners not given for this session.",
    "research": "Consent for research use not given for this session.",
}


class UnreadableFileError(Exception):
    """A coach file that is not valid JSON, usually after a hand edit. The message is the one line to show."""


def read_json(path: Path):
    """Load a JSON file, or raise UnreadableFileError naming the file and the line."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise UnreadableFileError(f"Couldn't read {path}: not valid JSON (line {e.lineno}). Fix it by hand or restore it.") from e
    except UnicodeDecodeError as e:
        raise UnreadableFileError(f"Couldn't read {path}: not valid text (UTF-8).") from e
    if not isinstance(data, dict):
        raise UnreadableFileError(f"Couldn't read {path}: expected a JSON object.")
    return data


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "founder"


class Session:
    def __init__(self, directory: Path, data: dict):
        self.dir = Path(directory)
        self.data = data

    @classmethod
    def create(cls, root: Path, founder: str, time_limit_s: float | None, self_mode: bool = False,
               occasion: str | None = None, scenario: str | None = None) -> "Session":
        directory = cls.folder(root, founder, occasion)
        cls.check_free(directory)
        directory.mkdir(parents=True, exist_ok=True)
        profile = SCENARIOS.get(scenario)
        if profile and time_limit_s is None:
            time_limit_s = profile["target_s"][1]
        s = cls(directory, {
            "founder": founder,
            "mode": "self" if self_mode else "operator",
            "time_limit_s": time_limit_s,
            **({"occasion": occasion} if occasion else {}),
            **({"scenario": scenario, "target_length_s": list(profile["target_s"])} if profile else {}),
            # Coaching yourself: you consent to recording yourself; blind listeners are still asked per session.
            "consent": {"recording": self_mode, "blind_listeners": False, "research": False},
        })
        s.save()
        (directory / "context.md").write_text(f"# {founder}: context and story bank\n", encoding="utf-8")
        (directory / "questions_log.md").write_text("# Coaching questions asked\n", encoding="utf-8")
        return s

    @staticmethod
    def folder(root: Path, founder: str, occasion: str | None = None) -> Path:
        return Path(root) / (slugify(founder) + (f"-{slugify(occasion)}" if occasion else ""))

    @staticmethod
    def check_free(directory: Path) -> None:
        if (Path(directory) / "session.json").exists():
            raise FileExistsError(
                f"A session already exists at {directory}. Resume it (see `storycoach status`) instead."
            )

    @classmethod
    def load(cls, directory: Path) -> "Session":
        path = Path(directory) / "session.json"
        if not path.exists():
            raise FileNotFoundError(f"No session.json in {directory}. Create one with: storycoach new <name> --self")
        return cls(Path(directory), read_json(path))

    def save(self) -> None:
        (self.dir / "session.json").write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def require_consent(self, kind: str) -> None:
        if self.data.get("consent", {}).get(kind) is not True:
            print(CONSENT_MESSAGES[kind], file=sys.stderr)
            sys.exit(2)

    def takes(self) -> list[Path]:
        return sorted(p for p in self.dir.glob("take_*") if p.is_dir() and p.name[5:].isdigit())

    def next_take_dir(self) -> Path:
        nums = [int(p.name[5:]) for p in self.takes()]
        return self.dir / f"take_{max(nums, default=0) + 1:02d}"
