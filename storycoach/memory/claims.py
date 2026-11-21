from __future__ import annotations

from .schema import normalise_name


def same_value(a, b) -> bool:
    """Numbers compare numerically (30 == 30.0); a missing value only equals a missing value."""
    if a is None or b is None:
        return a is None and b is None
    return a == b


def match(new: dict, live: list[dict]) -> tuple[str | None, list[dict]]:
    """Compare a new claim's data with live claims under the same about and key.

    Returns (id of a claim to cite or None, live claims whose value differs).
    `live` holds {"id", "data"} records."""
    same_key = [c for c in live
                if c["data"].get("about") == new.get("about") and c["data"].get("key") == new.get("key")]
    cite, differing = None, []
    for c in same_key:
        d = c["data"]
        if same_value(d.get("value"), new.get("value")) and (
                new.get("value") is None
                and normalise_name(str(d.get("statement", ""))) == normalise_name(str(new.get("statement", "")))
                or new.get("value") is not None and d.get("unit") == new.get("unit")):
            cite = cite or c["id"]
        elif new.get("value") is not None or d.get("value") is not None:
            differing.append(c)
    return cite, differing
