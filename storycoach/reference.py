"""Typical ranges across a corpus of skilled tellers. Placements, never scores."""
import json
from pathlib import Path

import numpy as np

MIN_N = 5
POSITIONS = ("opening", "key_lines", "ending", "overall")


def _numeric(d: dict) -> dict[str, float]:
    out = {}
    for k, v in d.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
        elif isinstance(v, dict):
            out.update({f"{k}.{kk}": vv for kk, vv in _numeric(v).items()})
    return out


def build_reference(feature_files: list[Path]) -> dict:
    values: dict[str, dict[str, list[float]]] = {p: {} for p in POSITIONS}
    for path in feature_files:
        f = json.loads(Path(path).read_text(encoding="utf-8"))
        for pos in POSITIONS:
            items = f.get(pos) or []
            for item in items if pos == "key_lines" else [items]:
                for m, v in _numeric(item).items():
                    values[pos].setdefault(m, []).append(v)
    ref = {}
    for pos, metrics in values.items():
        ref[pos] = {}
        for m, vs in metrics.items():
            if len(vs) >= MIN_N:
                ref[pos][m] = {
                    "p25": round(float(np.percentile(vs, 25)), 3),
                    "p50": round(float(np.percentile(vs, 50)), 3),
                    "p75": round(float(np.percentile(vs, 75)), 3),
                    "n": len(vs),
                }
    return ref


def place(value: float | None, position: str, metric: str, ref: dict | None) -> str | None:
    if value is None or ref is None:
        return None
    band = ref.get(position, {}).get(metric)
    if band is None:
        return None
    if value < band["p25"]:
        return "below_typical"
    if value > band["p75"]:
        return "above_typical"
    return "typical"
