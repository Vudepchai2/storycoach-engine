"""Blind A/B listening test: baseline take vs final take, order randomised per listener."""
import csv
import random
import shutil
from pathlib import Path


def make_blind_set(take_a: Path, take_b: Path, out: Path, listeners: int, seed: int) -> Path:
    """take_a = baseline (cold telling), take_b = final take."""
    out = Path(out)
    results = out / "results.csv"
    if results.exists() and len(results.read_text().strip().splitlines()) > 1:
        raise FileExistsError(f"{results} already has listener answers; move it aside before making a new blind set.")
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    orders = ["baseline", "final"] * ((listeners + 1) // 2)
    orders = orders[:listeners]
    rng.shuffle(orders)
    src = {"baseline": Path(take_a) / "audio.wav", "final": Path(take_b) / "audio.wav"}
    with open(out / "key.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["listener", "A_is"])
        for i, a_is in enumerate(orders, 1):
            d = out / f"listener_{i:02d}"
            d.mkdir(exist_ok=True)
            b_is = "final" if a_is == "baseline" else "baseline"
            shutil.copyfile(src[a_is], d / "A.wav")
            shutil.copyfile(src[b_is], d / "B.wav")
            w.writerow([f"listener_{i:02d}", a_is])
    with open(out / "results.csv", "w", newline="") as fh:
        csv.writer(fh).writerow(["listener", "preferred"])
    return out


def tally_blind(out: Path) -> dict:
    out = Path(out)
    with open(out / "key.csv", newline="") as fh:
        key = {r["listener"]: r["A_is"] for r in csv.DictReader(fh)}
    final = baseline = 0
    seen: set[str] = set()
    with open(out / "results.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            pref = (r.get("preferred") or "").strip().upper()
            listener = (r.get("listener") or "").strip()
            a_is = key.get(listener)
            if pref not in ("A", "B") or a_is is None or listener in seen:
                continue  # first answer per listener counts
            seen.add(listener)
            chose = a_is if pref == "A" else ("final" if a_is == "baseline" else "baseline")
            final += chose == "final"
            baseline += chose == "baseline"
    return {"final_preferred": final, "baseline_preferred": baseline, "n": final + baseline}
