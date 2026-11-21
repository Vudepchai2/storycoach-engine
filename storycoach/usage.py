"""Local usage stats: counts only, kept on this machine, under a fixed schema.

The schema admits numbers, booleans and members of fixed sets, so free text, names, paths and
content cannot be stored. Nothing here is uploaded; export is a summary the tester shares by choice.
"""
import json
import re
import sys
import uuid
from datetime import datetime, timezone

from storycoach import home
from storycoach.scenarios import SCENARIOS

PHASES = frozenset({"capture", "shape", "recall", "feedback"})
SELF_CHECK = frozenset({"yes", "partly", "no"})
MODES = frozenset({"self", "operator"})
SCENARIO_NAMES = frozenset(set(SCENARIOS) | {"none"})
ERROR_CLASSES = frozenset({"FileNotFoundError", "FileExistsError", "ValueError", "RuntimeError", "NoSpeechError",
                           "BatchError", "SystemExit", "KeyboardInterrupt", "other"})


class CommandName(str):
    """Schema marker: a command name checked against the parser's commands (see command_names)."""


SCHEMA: dict[str, dict] = {
    "command": {"name": CommandName, "seconds": float, "ok": bool, "error": frozenset(ERROR_CLASSES | {None})},
    "session_started": {"scenario": SCENARIO_NAMES, "mode": MODES},
    "take_analysed": {"take": int, "seconds": float, "focus_set": bool},
    "question_asked": {"phase": PHASES},
    "self_check": {"answer": SELF_CHECK, "take": int},
}

TAKE_MAX = 10000
SECONDS_MAX = 1e6
INSTALL_RE = re.compile(r"[0-9a-f]{32}")
AT_RE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")

_names: frozenset | None = None


def command_names() -> frozenset:
    """Top-level subcommands plus 'memory <sub>', derived from the real parser, never listed by hand."""
    global _names
    if _names is None:
        from storycoach.__main__ import build_parser

        _names = frozenset(name for name, _ in command_table(build_parser()[1]))
    return _names


def command_table(sub):
    """Yield (usage name, fn) for every runnable command of a subparsers action."""
    from argparse import _SubParsersAction

    for name, parser in sub.choices.items():
        nested = [a for a in parser._actions if isinstance(a, _SubParsersAction)]
        if not nested:
            yield name, parser._defaults.get("fn")
            continue
        for n in nested:
            for inner, fn in command_table(n):
                yield (f"{name} {inner}" if name == "memory" else name), fn


def __getattr__(attr):
    if attr == "COMMAND_NAMES":
        return command_names()
    raise AttributeError(attr)


def validate(event_type: str, fields: dict) -> None:
    spec = SCHEMA.get(event_type)
    if spec is None:
        raise ValueError(f"unknown event type: {event_type!r}")
    for k in fields:
        if k not in spec:
            raise ValueError(f"unknown field for {event_type}: {k!r}")
    for k, kind in spec.items():
        if k not in fields:
            raise ValueError(f"missing field for {event_type}: {k!r}")
        v = fields[k]
        if kind is bool:
            ok = isinstance(v, bool)
        elif kind is int:
            ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= TAKE_MAX
        elif kind is float:
            ok = (isinstance(v, (int, float)) and not isinstance(v, bool)
                  and 0 <= v <= SECONDS_MAX)
        elif kind is CommandName:
            ok = isinstance(v, str) and v in command_names()
        else:
            ok = (v is None or isinstance(v, str)) and v in kind
        if not ok:
            raise ValueError(f"bad value for {event_type}.{k}")


def enabled() -> bool:
    """On unless switched off. A settings file that cannot be read counts as off: an opt-out never reverts."""
    state, data = home.settings_state()
    if state in ("unreadable", "damaged"):
        return False
    return data.get("usage", True) is not False


def set_enabled(on: bool) -> None:
    home.update_settings(usage=bool(on))


def install_id() -> str:
    cur = home.read_settings().get("install_id")
    if isinstance(cur, str) and INSTALL_RE.fullmatch(cur):
        return cur
    new = uuid.uuid4().hex
    home.update_settings(install_id=new)
    return new


def _stored_install_id():
    """The id if one was already made, else None. Never writes."""
    cur = home.read_settings().get("install_id")
    return cur if isinstance(cur, str) and INSTALL_RE.fullmatch(cur) else None


def _events_file():
    return home.usage_dir() / "events.jsonl"


def log(event_type: str, **fields) -> bool:
    validate(event_type, fields)
    if not enabled():
        return False
    event = {"type": event_type, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "install": install_id(), **fields}
    line = json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n"
    path = _events_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
    return True


def log_quietly(event_type: str, **fields) -> None:
    """For the engine's own logging: a failure is a warning, never a failed command."""
    try:
        log(event_type, **fields)
    except Exception as e:  # noqa: BLE001
        print(f"usage stats not recorded ({type(e).__name__})", file=sys.stderr)


def _valid_line(e) -> bool:
    """Exactly the schema fields plus type, at and install, each valid; anything else is dropped."""
    if not isinstance(e, dict) or e.get("type") not in SCHEMA:
        return False
    at, inst = e.get("at"), e.get("install")
    if not (isinstance(at, str) and AT_RE.fullmatch(at) and isinstance(inst, str) and INSTALL_RE.fullmatch(inst)):
        return False
    fields = {k: v for k, v in e.items() if k not in ("type", "at", "install")}
    try:
        validate(e["type"], fields)
    except ValueError:
        return False
    return True


def _read_events() -> list[dict]:
    try:
        lines = _events_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if _valid_line(e):
            out.append(e)
    return out


def _count(events, etype, field) -> dict:
    out: dict = {}
    for e in events:
        if e["type"] == etype:
            out[str(e[field])] = out.get(str(e[field]), 0) + 1
    return out


def summary() -> dict:
    ev = _read_events()
    sessions = sum(1 for e in ev if e["type"] == "session_started")
    takes = sum(1 for e in ev if e["type"] == "take_analysed")
    questions = sum(1 for e in ev if e["type"] == "question_asked")
    by_take: dict = {}
    for e in ev:
        if e["type"] == "self_check":
            d = by_take.setdefault(str(e["take"]), {})
            d[e["answer"]] = d.get(e["answer"], 0) + 1
    commands: dict = {}
    for e in ev:
        if e["type"] == "command":
            c = commands.setdefault(e["name"], {"runs": 0, "failed": 0})
            c["runs"] += 1
            c["failed"] += 0 if e["ok"] else 1
    dates = sorted(str(e.get("at", ""))[:10] for e in ev if e.get("at"))
    return {
        "sessions_by_scenario": _count(ev, "session_started", "scenario"),
        "takes_per_session": round(takes / sessions, 2) if sessions else 0,
        "questions_by_phase": _count(ev, "question_asked", "phase"),
        "questions_per_session": round(questions / sessions, 2) if sessions else 0,
        "self_check": _count(ev, "self_check", "answer"),
        "self_check_by_take": by_take,
        "commands": commands,
        "first_event": dates[0] if dates else None,
        "last_event": dates[-1] if dates else None,
        "events": len(ev),
        "install": _stored_install_id() if enabled() else None,
    }


def parse_value(text: str):
    if text == "true":
        return True
    if text == "false":
        return False
    for conv in (int, float):
        try:
            return conv(text)
        except ValueError:
            pass
    return text


def show_lines(s: dict) -> list[str]:
    lines = [f"usage stats: {'on' if enabled() else 'off'}", f"events: {s['events']}"]
    if s["first_event"]:
        lines.append(f"from {s['first_event']} to {s['last_event']}")
    lines.append(f"sessions by scenario: {s['sessions_by_scenario']}")
    lines.append(f"takes per session: {s['takes_per_session']}")
    lines.append(f"questions by phase: {s['questions_by_phase']}")
    lines.append(f"questions per session: {s['questions_per_session']}")
    lines.append(f"self check: {s['self_check']}")
    for name, c in sorted(s["commands"].items()):
        lines.append(f"command {name}: {c['runs']} runs, {c['failed']} failed")
    lines.append(f"file: {_events_file()}")
    return lines
