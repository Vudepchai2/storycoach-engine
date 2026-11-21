"""Story scenarios: each kind of story has its own target length and key beats."""

DEFAULT_KEY_BEATS = frozenset({"turn", "ask"})

SCENARIOS: dict[str, dict] = {
    "pitch": {"target_s": (60, 180), "key_beats": frozenset({"turn", "resolution", "ask"})},
    "job": {"target_s": (60, 120), "key_beats": frozenset({"turn", "resolution"})},
    "speech": {"target_s": (120, 300), "key_beats": frozenset({"hook", "turn", "resolution"})},
    "content": {"target_s": (30, 90), "key_beats": frozenset({"hook", "resolution"})},
}


def scenario_for(session_data: dict) -> dict | None:
    """The scenario profile a session was made with, or None for an old or unknown one."""
    name = session_data.get("scenario")
    return SCENARIOS.get(name) if isinstance(name, str) else None
