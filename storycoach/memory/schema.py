from __future__ import annotations

import posixpath
import re
import unicodedata
from pathlib import Path

from storycoach.home import data_home

PREFIX = {
    "entity": "e", "moment": "m", "claim": "c", "observation": "o",
    "occasion": "oc", "source": "s", "conflict": "x",
}
SOURCE_KINDS = ("said", "document", "transcript", "coach")
ENTITY_KINDS = ("person", "org", "place", "event", "project", "other")

FIELDS: dict[str, set[str]] = {
    "entity": {"name", "kind", "aliases", "relation"},
    "moment": {"title", "when", "date", "where", "who", "what_happened",
               "what_changed", "meaning", "quotes"},
    "claim": {"about", "key", "statement", "value", "unit", "quote"},
    "observation": {"about", "statement", "evidence", "moments"},
    "occasion": {"name", "audience", "date", "session", "uses", "outcome", "debrief"},
    "source": {"filename", "sha256", "stored"},
}
REQUIRED: dict[str, set[str]] = {
    "entity": {"name", "kind"},
    "moment": {"title", "what_happened"},
    "claim": {"about", "key", "statement", "quote"},
    "observation": {"about", "statement"},
    "occasion": {"name"},
}
# Value types checked by the write gate. Every other field is a reference, a list of
# references, or checked on its own (`about`, `kind`, `date`, `value`, `evidence`).
TEXT = {"name", "title", "when", "where", "what_happened", "what_changed", "meaning",
        "key", "statement", "unit", "quote", "relation", "audience", "outcome", "session"}
TEXT_LISTS = {"aliases", "quotes", "debrief"}
# A value change is a new claim, never an update; an entity keeps its name.
UPDATABLE: dict[str, set[str]] = {
    t: f - {"about", "key", "value", "unit"} if t == "claim"
    else f - {"name"} if t == "entity" else set(f)
    for t, f in FIELDS.items()
}


def normalise_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r"[\W_]+", " ", s).strip()


def canonical_ref(ref: str, root: Path | None = None) -> str:
    """One spelling per place: a path inside the data home becomes home-relative with forward slashes.

    Refs without a path separator (source ids such as `s1`, `import`, `reflect`) are kept as they are;
    an absolute path outside the data home stays absolute, still traceable."""
    ref = ref.strip()
    if "/" not in ref and "\\" not in ref:
        return ref
    path = Path(ref)
    if path.is_absolute():
        try:
            return path.resolve().relative_to((root or data_home()).resolve()).as_posix()
        except ValueError:
            return path.as_posix()
    return posixpath.normpath(ref.replace("\\", "/"))
