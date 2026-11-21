"""Storytelling coach CLI. Run `storycoach --help`."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from storycoach import home
from storycoach.scenarios import SCENARIOS
from storycoach.version import __version__


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def _fail(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def _analyse_into(audio: Path, take: Path) -> Path:
    from storycoach.acoustics import extract_acoustics
    from storycoach.audio import to_wav
    from storycoach.transcribe import NoSpeechError, transcribe

    if take.exists() and any(take.iterdir()):
        _fail(f"{take} already exists; refusing to overwrite it.")
    # Work in a .partial folder and rename only on success, so a killed run never becomes a take.
    work = take.with_name(take.name + ".partial")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        wav = to_wav(audio, work / "audio.wav")
        t = transcribe(wav)
        _dump(work / "transcript.json", t.to_dict())
        _dump(work / "acoustics.json", extract_acoustics(wav).to_dict())
        (work / "words.txt").write_text("".join(f"{i}\t{w.text}\n" for i, w in enumerate(t.words)), encoding="utf-8")
    except (FileNotFoundError, RuntimeError, NoSpeechError) as e:
        shutil.rmtree(work, ignore_errors=True)
        hint = " Check the file and microphone, then record again." if isinstance(e, NoSpeechError) else ""
        _fail(f"{e}{hint}")
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    if take.exists():
        take.rmdir()
    work.rename(take)
    return take


AUDIO_EXTS = {".m4a", ".wav", ".mp3", ".aac", ".ogg", ".flac", ".webm", ".mp4"}
SOUND_RECORDINGS = Path.home() / "Documents" / "Sound recordings"


def _known_documents() -> Path | None:
    """The real Documents folder on Windows (it moves when OneDrive backs it up), or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        guid = ctypes.c_byte * 16
        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = guid(*bytes.fromhex("D09AD3FD8F23AF46ADB46C85480369C7"))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) != 0:
            return None
        path = Path(out.value)
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except Exception:  # noqa: BLE001  a lookup problem just means one folder fewer
        return None


def sound_recording_folders() -> list[Path]:
    """Where Windows Sound Recorder saves: Documents, or Documents redirected into OneDrive."""
    found = [SOUND_RECORDINGS, Path.home() / "OneDrive" / "Documents" / "Sound recordings"]
    docs = _known_documents()
    if docs:
        found.append(docs / "Sound recordings")
    return list(dict.fromkeys(found))


def latest_audio(folder: Path) -> Path:
    files = [p for p in Path(folder).glob("*") if p.suffix.lower() in AUDIO_EXTS and p.is_file()]
    if not files:
        raise FileNotFoundError(f"No audio files found in {folder}. Record a take first.")
    return max(files, key=lambda p: p.stat().st_mtime)


# Only length-independent metrics are compared with reference talks, which are much longer than a 1-3 min story.
PLACEABLE = {
    "syll_per_s", "rate_vs_overall", "fillers_per_min", "mean_pause_s", "intensity_slope_db_per_s",
    "pitch.range_st_p10_p90", "pitch.sd_st", "pause_before_s", "pause_after_s", "pitch_sd_vs_overall",
    "loudness.range_db_p10_p90", "loudness.sd_db", "loudness_vs_overall_db",
}


def _placements(features: dict, ref: dict) -> dict:
    from storycoach.reference import _numeric, place

    def placed(d: dict, pos: str) -> dict:
        return {m: p for m, v in _numeric(d).items() if m in PLACEABLE and (p := place(v, pos, m, ref))}

    out = {pos: placed(features[pos], pos) for pos in ("opening", "ending", "overall")}
    out["key_lines"] = [placed(k, "key_lines") for k in features["key_lines"]]
    return out


SESSION_FILES = ("session.json", "context.md", "questions_log.md")  # what Session.create writes


def _undo_new_session(folder: Path, before: set[str] | None) -> None:
    """Remove only what this run wrote: never a file or folder that was there before it."""
    for name in SESSION_FILES:
        if before is None or name not in before:
            try:
                (folder / name).unlink()
            except OSError:
                pass
    if before is None:
        try:
            folder.rmdir()  # only when empty
        except OSError:
            pass
    if folder.exists():
        print(f"Left {folder} in place: it held files before this run.", file=sys.stderr)


def cmd_new(a):
    from storycoach.session import Session

    with_memory = a.self_mode or a.memory or bool(a.person)
    folder = Session.folder(Path(a.root), a.founder, a.occasion)
    if with_memory:
        from storycoach.memory.cli import attach_memory, prepare_bank, undo_new_bank

        # The bank is found, checked or created before the session exists: a failure here writes nothing.
        Session.check_free(folder)
        bank, bank_is_new = prepare_bank(a.founder, Path(a.people_root), a.self_mode, a.person)
    before = {p.name for p in folder.iterdir()} if folder.is_dir() else None
    s = None
    try:
        s = Session.create(Path(a.root), a.founder, a.time_limit, self_mode=a.self_mode, occasion=a.occasion,
                           scenario=a.scenario)
        if with_memory:
            attach_memory(s, bank, a.occasion)
    except BaseException:
        if with_memory:
            if s is not None and "occasion_id" in s.data:  # the bank already records this session
                print(f"Left {s.dir} in place: {bank} records it as an occasion.", file=sys.stderr)
            else:
                _undo_new_session(folder, before)
                if bank_is_new:
                    undo_new_bank(bank)
        raise
    from storycoach import usage

    usage.log_quietly("session_started", scenario=s.data.get("scenario") or "none",
                      mode="self" if a.self_mode else "operator")
    print(s.dir)


def latest_across(folders: list[Path]) -> Path:
    found = []
    for f in folders:
        try:
            found.append(latest_audio(f))
        except FileNotFoundError:
            pass
    if not found:
        raise FileNotFoundError(f"No audio files found in {', '.join(str(f) for f in folders)}. Record a take first.")
    return max(found, key=lambda p: p.stat().st_mtime)


def cmd_analyse(a):
    from storycoach.session import Session

    s = Session.load(Path(a.session_dir))
    s.require_consent("recording")
    if a.latest:
        if a.from_dir:
            folders = [Path(a.from_dir)]
        else:
            folders = [s.dir / "recordings"] + (sound_recording_folders() if sys.platform == "win32" else [])
        audio = latest_across(folders)
        print(f"Using newest recording: {audio}", file=sys.stderr)
    elif a.audio:
        audio = Path(a.audio)
    else:
        _fail("Give an audio file, or --latest to use the newest recording.")
    take = _analyse_into(audio, s.next_take_dir())
    _log_take(take, bool(s.data.get("focus")))
    print(take)


def _log_take(take: Path, focus_set: bool) -> None:
    """Count one analysed take: its number, its length in seconds and whether it had a focus. Nothing else."""
    import wave

    from storycoach import usage

    n = _take_number(take)
    try:
        with wave.open(str(take / "audio.wav")) as w:
            seconds = w.getnframes() / w.getframerate()
    except (OSError, EOFError, wave.Error, ZeroDivisionError):
        return
    if n is not None:
        usage.log_quietly("take_analysed", take=n, seconds=round(seconds, 2), focus_set=focus_set)


def cmd_record(a):
    import time

    from storycoach import record as rec
    from storycoach.session import Session

    try:  # a legacy console codepage must not crash on the dash or arrows in our messages
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    s = Session.load(Path(a.session))
    lock, stop = rec.lock_path(s.dir), rec.stop_path(s.dir)
    if a.stop:
        if not lock.exists():
            print("no recording was running")
            return
        if rec.lock_is_stale(lock):
            lock.unlink(missing_ok=True)  # record's own file, left by a recorder that is gone
            print("no recording was running")
            return
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("stop", encoding="utf-8")
        deadline = time.monotonic() + rec.STOP_WAIT_S
        while lock.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if lock.exists():
            print("the recorder hasn't finished yet; it will stop shortly")
        else:
            print("stopped")
        return
    s.require_consent("recording")
    if a.max_seconds is not None:
        max_s = a.max_seconds
    else:
        target = s.data.get("target_length_s")
        max_s = min(600, 2 * target[1]) if target else 600
    if lock.exists():
        if not rec.lock_is_stale(lock):
            _fail(f"A recording is already running for {s.dir}. Stop it first with: storycoach record --stop {s.dir}")
        lock.unlink(missing_ok=True)
        print("replaced a stale recording lock")
    factory = rec.STREAM_FACTORY
    if factory is None:
        try:
            import sounddevice  # noqa: F401
        except OSError:
            if sys.platform.startswith("linux"):
                _fail(rec.PORTAUDIO_HINT)
            raise
    out = rec.new_take_path(s.dir)
    stop.unlink(missing_ok=True)
    try:
        rec.write_lock(lock, max_s)
    except FileExistsError:
        _fail(f"A recording is already running for {s.dir}. Stop it first with: storycoach record --stop {s.dir}")
    print(f'recording to {out} \u2014 say "done" when you finish', flush=True)
    try:
        result = rec.record(out, stop, max_s, stream_factory=factory)
    except FileExistsError:
        _fail(f"{out} already exists; refusing to overwrite it. Try again.")  # not ours: leave it alone
    except Exception as e:
        _drop_empty_take(out)
        _fail(f"Couldn't open a microphone: {e}. Check that one is connected and that this terminal is allowed to use it.")
    finally:
        if rec.lock_is_ours(lock):
            lock.unlink(missing_ok=True)
        stop.unlink(missing_ok=True)
    print(f"saved {result['path']} ({result['seconds']:.1f} s)")
    if result["peak"] < 0.01:
        print(rec.permission_hint(sys.platform))


def _drop_empty_take(path: Path) -> None:
    """Remove a take this run created only if it holds no audio frames."""
    import wave

    try:
        with wave.open(str(path)) as w:
            empty = w.getnframes() == 0
    except (OSError, EOFError, wave.Error):
        empty = path.is_file() and path.stat().st_size <= 44
    if empty:
        path.unlink(missing_ok=True)


def cmd_status(a):
    from storycoach.session import Session

    root = Path(a.root)
    found = sorted(p.parent for p in root.glob("*/session.json"))
    if not found:
        print(f"No sessions in {root}. Start one with: storycoach new <name> --self")
        return
    for d in found:
        s = Session.load(d)
        print(f"{d.name}  ({s.data.get('mode', 'operator')} mode)  {d}")
        if s.data.get("person"):
            print(f"  person: {s.data['person']}")
        for t in s.takes():
            parts = ["analysed"]  # takes only exist once analysis finished (see .partial)
            if (t / "features.json").exists():
                parts.append("features")
            print(f"  {t.name} ({', '.join(parts)})")


def compute_take_features(take: Path, reference: str | None = None) -> Path:
    """Write features.json for one take folder; the shared core of `features` and `practice`."""
    from storycoach.beats import BeatsError, load_beats
    from storycoach.candidates import select_candidates
    from storycoach.features import compute_features, observations
    from storycoach.models import Acoustics, Transcript
    from storycoach.scenarios import scenario_for

    if not (take / "beats.json").exists():
        _fail(f"beats.json not found in {take}. Label the beats and key lines first (see references/beats.md).")
    for needed in ("transcript.json", "acoustics.json"):
        if not (take / needed).exists():
            _fail(f"{needed} not found in {take}; this take was not analysed. Run `analyse` again.")
    t = Transcript.from_dict(json.loads((take / "transcript.json").read_text(encoding="utf-8")))
    ac = Acoustics.from_dict(json.loads((take / "acoustics.json").read_text(encoding="utf-8")))
    try:
        beats = load_beats(take / "beats.json", len(t.words))
    except BeatsError as e:
        _fail(str(e))
    session = {}
    session_file = take.parent / "session.json"
    if session_file.exists():
        from storycoach.session import read_json

        session = read_json(session_file)
    f = compute_features(t, ac, beats, session.get("time_limit_s"))
    f["focus"] = session.get("focus")
    prev_dir = _previous_take(take)
    prev = json.loads((prev_dir / "features.json").read_text(encoding="utf-8")) if prev_dir else None
    profile = scenario_for(session)
    f["scenario"] = session.get("scenario") if profile else None
    f["candidates"] = {"previous_take": prev_dir.name if prev_dir else None,
                       **select_candidates(f, prev, f["focus"], profile["key_beats"] if profile else None)}
    f["observations"] = observations(f)  # the details layer: shown on request, not read out
    stats = Path(reference) if reference else home.reference_dir() / "stats.json"
    if stats.exists():
        f["placements"] = _placements(f, json.loads(stats.read_text(encoding="utf-8")))
    _dump(take / "features.json", f)
    return take / "features.json"


def cmd_features(a):
    print(compute_take_features(Path(a.take_dir), a.reference))


def cmd_practice(a):
    from storycoach import practice
    from storycoach.session import Session

    case_dir = Path(a.case_dir)
    if not (case_dir / "case.json").exists():
        _fail(f"{case_dir} is not a practice case (no case.json).")
    try:
        session = practice.build(case_dir, a.reset, compute_take_features)
    except FileExistsError as e:
        _fail(str(e))
    print(session)
    print(f"memory: {home.practice_dir() / 'people' / Session.load(session).data['person']}")


def _take_number(d: Path) -> int | None:
    tail = d.name.rsplit("_", 1)[-1]
    return int(tail) if d.name.startswith("take_") and tail.isdigit() else None


def _previous_take(take: Path) -> Path | None:
    """The closest earlier take in the same session that already has features."""
    n = _take_number(take)
    if n is None:
        return None
    earlier = [(k, d) for d in take.parent.glob("take_*")
               if (k := _take_number(d)) is not None and k < n and (d / "features.json").exists()]
    return max(earlier)[1] if earlier else None


def cmd_focus(a):
    from storycoach.beats import LABELS
    from storycoach.session import Session

    s = Session.load(Path(a.session_dir))
    if a.clear:
        s.data["focus"] = None
        s.save()
        print("Focus cleared.")
        return
    if not a.text:
        _fail("Give the focus in the speaker's own words, or --clear.")
    if a.beat and a.beat not in LABELS:
        _fail(f"unknown beat '{a.beat}' (allowed: {', '.join(sorted(LABELS))})")
    focus = {"text": a.text, "beat": a.beat, "line": a.line,
             "set_before_take": _take_number(s.next_take_dir())}
    s.data["focus"] = focus
    s.data.setdefault("focus_history", []).append(focus)
    s.save()
    print(json.dumps(focus, ensure_ascii=False))


def cmd_clip(a):
    import wave

    take = Path(a.take_dir)
    src = take / "audio.wav"
    if not src.exists():
        _fail(f"{src} not found; this take has no local audio.")
    if a.end <= a.start or a.start < 0:
        _fail("The end time must be after the start time, and the start must be 0 or more.")
    out_dir = take.parent / "clips"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{take.name}_{a.start:.2f}-{a.end:.2f}.wav"
    with wave.open(str(src)) as r:
        rate, total = r.getframerate(), r.getnframes()
        first = min(int(a.start * rate), total)
        last = min(int(a.end * rate), total)
        r.setpos(first)
        frames = r.readframes(last - first)
        params = r.getparams()
    with wave.open(str(out), "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    print(out)


def cmd_compare(a):
    from storycoach.compare import compare_takes

    ta, tb = Path(a.take_a), Path(a.take_b)
    for d in (ta, tb):
        if not (d / "features.json").exists():
            _fail(f"{d / 'features.json'} not found. Label beats and run `features {d}` first.")
    load = lambda d, n: json.loads((d / n).read_text(encoding="utf-8"))
    d = compare_takes(load(ta, "features.json"), load(tb, "features.json"),
                      load(ta, "transcript.json")["text"], load(tb, "transcript.json")["text"])
    out = tb.parent / f"compare_{ta.name[-2:]}_{tb.name[-2:]}.json"
    _dump(out, d)
    print(out)


def cmd_reference_add(a):
    from storycoach.session import slugify

    audio = Path(a.audio)
    take = home.reference_dir() / "_local" / slugify(a.name or audio.stem)
    _analyse_into(audio, take)
    n = len((take / "words.txt").read_text(encoding="utf-8").splitlines())
    _dump(take / "beats.json", {"beats": [{"label": "other", "start_word": 0, "end_word": n - 1}], "key_lines": []})
    print(take)


def cmd_reference_build(a):
    from storycoach.reference import build_reference

    ref = home.reference_dir()
    files = sorted((ref / "_local").glob("*/features.json"))
    if not files:
        _fail(f"No analysed reference talks found in {ref / '_local'}/*/features.json")
    _dump(ref / "stats.json", build_reference(files))
    print(f"{ref / 'stats.json'} built from {len(files)} talks")


def cmd_import_legacy(a):
    src = Path(a.folder)
    if not src.is_dir():
        _fail(f"{src} is not a folder.")
    if not any((src / k).is_dir() for k in ("sessions", "people", "reference")):
        print(f"nothing to import in {src}")
        return
    dest_home = home.ensure_home()
    copied = skipped = 0
    for kind in ("sessions", "people", "reference"):
        kind_src = src / kind
        if not kind_src.is_dir():
            continue
        for child in sorted(p for p in kind_src.iterdir() if p.is_dir()):
            dest = dest_home / kind / child.name
            if dest.exists():
                print(f"skipped {child.name} (already in {dest_home})")
                skipped += 1
                continue
            tmp = dest.with_name(f"{dest.name}.importing-{os.getpid()}")
            try:
                shutil.copytree(child, tmp)
                tmp.rename(dest)
            except OSError as e:
                shutil.rmtree(tmp, ignore_errors=True)  # only the temp copy this run made
                _fail(f"Could not import {child}: {e}. Nothing was left half-copied; fix the problem and run it again.")
            copied += 1
    stats = src / "reference" / "stats.json"
    stats_dest = dest_home / "reference" / "stats.json"
    if stats.is_file() and not stats_dest.exists():
        try:
            shutil.copy2(stats, stats_dest)
        except OSError as e:
            _fail(f"Could not import {stats}: {e}")
        print("copied reference/stats.json")
    print(f"copied {copied}, skipped {skipped}")


def cmd_blind(a):
    from storycoach.blind import make_blind_set
    from storycoach.session import Session

    s = Session.load(Path(a.session_dir))
    s.require_consent("blind_listeners")
    takes = s.takes()
    if len(takes) < 2:
        _fail("Need at least two takes (the cold baseline and a final take).")
    print(make_blind_set(takes[0], takes[-1], s.dir / "blind", a.listeners, a.seed))


def cmd_blind_tally(a):
    from storycoach.blind import tally_blind

    print(json.dumps(tally_blind(Path(a.blind_dir))))


def cmd_usage_show(a):
    from storycoach import usage

    print("\n".join(usage.show_lines(usage.summary())))


def cmd_usage_export(a):
    from storycoach import usage

    text = json.dumps(usage.summary(), indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)


def cmd_usage_set(on: bool):
    from storycoach import usage

    usage.set_enabled(on)
    print(f"usage stats {'on' if on else 'off'}")


def cmd_usage_log(a):
    from storycoach import usage

    fields = {}
    for pair in a.pairs:
        k, sep, v = pair.partition("=")
        if not sep:
            _fail(f"expected key=value, got a value without '=' ({len(pair)} characters)")
        fields[k] = usage.parse_value(v)
    try:
        usage.log(a.type, **fields)
    except ValueError as e:
        _fail(f"not logged: {e}")


def cmd_setup(a):
    from storycoach import setup as setup_mod

    if a.ack_privacy and not a.skip_model and not a.json:
        sys.exit(setup_mod.ack_only())  # run alone: just record it
    code = setup_mod.run(a.skip_model, a.json, a.ack_privacy)
    if code:
        sys.exit(code)


def cmd_close(a):
    from storycoach.session import Session

    s = Session.load(Path(a.session_dir))
    keep = s.data.get("mode") == "self" or s.data.get("consent", {}).get("research") is True
    if keep and not a.delete:
        print(f"Keeping all takes and measurements in {s.dir} (use --delete to remove them).")
        return
    removed = [p for p in s.takes()] + sorted(s.dir.glob("compare_*.json"))
    if (s.dir / "blind").exists():
        removed.append(s.dir / "blind")
    for p in removed:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    print(f"Removed {len(removed)} take/comparison/blind items from {s.dir}")


def _flags(parser: argparse.ArgumentParser) -> list[str]:
    """Long option strings and positional names of one parser."""
    out = []
    for act in parser._actions:
        if isinstance(act, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        if act.option_strings:
            out.extend(o for o in act.option_strings if o.startswith("--"))
        else:
            out.append(act.dest)
    return out


def _command_table(sub, prefix: str = "") -> dict[str, list[str]]:
    table = {}
    for name, parser in sub.choices.items():
        nested = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        if nested:
            for n in nested:
                table.update(_command_table(n, f"{prefix}{name} "))
        else:
            table[f"{prefix}{name}"] = _flags(parser)
    return table


def build_parser():
    p = argparse.ArgumentParser(prog="storycoach")
    sub = p.add_subparsers(required=True)
    sessions = str(home.sessions_dir())
    c = sub.add_parser("new"); c.add_argument("founder"); c.add_argument("--time-limit", type=float); c.add_argument("--root", default=sessions)
    c.add_argument("--scenario", choices=sorted(SCENARIOS), help="kind of story: sets the target length and key beats")
    c.add_argument("--occasion", help="what this session is for; becomes part of the folder name")
    c.add_argument("--memory", action="store_true", help="keep a per-person memory bank for this session")
    c.add_argument("--person", help="reuse this existing memory bank (its folder name under people/); implies --memory")
    c.add_argument("--people-root", default=str(home.people_dir()))
    c.add_argument("--self", dest="self_mode", action="store_true", help="coaching yourself: recording consent on, takes kept"); c.set_defaults(fn=cmd_new)
    c = sub.add_parser("status"); c.add_argument("--root", default=sessions); c.set_defaults(fn=cmd_status)
    c = sub.add_parser("analyse"); c.add_argument("session_dir"); c.add_argument("audio", nargs="?")
    c.add_argument("--latest", action="store_true", help="use the newest recording (the session's recordings folder, plus Sound recordings on Windows)"); c.add_argument("--from", dest="from_dir"); c.set_defaults(fn=cmd_analyse)
    c = sub.add_parser("record"); c.add_argument("session"); c.add_argument("--max-seconds", type=float); c.add_argument("--stop", action="store_true"); c.set_defaults(fn=cmd_record)
    c = sub.add_parser("features"); c.add_argument("take_dir"); c.add_argument("--reference"); c.set_defaults(fn=cmd_features)
    c = sub.add_parser("practice", help="try the coaching loop on a made-up story"); c.add_argument("case_dir"); c.add_argument("--reset", action="store_true"); c.set_defaults(fn=cmd_practice)
    c = sub.add_parser("focus"); c.add_argument("session_dir"); c.add_argument("text", nargs="?"); c.add_argument("--beat"); c.add_argument("--line"); c.add_argument("--clear", action="store_true"); c.set_defaults(fn=cmd_focus)
    c = sub.add_parser("clip"); c.add_argument("take_dir"); c.add_argument("start", type=float); c.add_argument("end", type=float); c.set_defaults(fn=cmd_clip)
    c = sub.add_parser("compare"); c.add_argument("take_a"); c.add_argument("take_b"); c.set_defaults(fn=cmd_compare)
    c = sub.add_parser("reference-add"); c.add_argument("audio"); c.add_argument("--name"); c.set_defaults(fn=cmd_reference_add)
    c = sub.add_parser("reference-build"); c.set_defaults(fn=cmd_reference_build)
    c = sub.add_parser("blind"); c.add_argument("session_dir"); c.add_argument("--listeners", type=int, default=5); c.add_argument("--seed", type=int, default=0); c.set_defaults(fn=cmd_blind)
    c = sub.add_parser("close"); c.add_argument("session_dir"); c.add_argument("--delete", action="store_true"); c.set_defaults(fn=cmd_close)
    c = sub.add_parser("blind-tally"); c.add_argument("blind_dir"); c.set_defaults(fn=cmd_blind_tally)
    from storycoach.memory.cli import register

    register(sub)

    def cmd_version(a):
        print(f"storycoach {__version__}")

    def cmd_commands(a):
        from storycoach.memory.recall import GAP_SECTIONS

        print(json.dumps({"version": __version__, "commands": _command_table(sub),
                          "gap_sections": GAP_SECTIONS}, indent=2))

    c = sub.add_parser("import-legacy"); c.add_argument("folder"); c.set_defaults(fn=cmd_import_legacy)
    c = sub.add_parser("setup", help="create the data folder, fetch the speech model, check the microphone")
    c.add_argument("--skip-model", action="store_true"); c.add_argument("--json", action="store_true")
    c.add_argument("--ack-privacy", action="store_true", help="record that the privacy note was shown"); c.set_defaults(fn=cmd_setup)
    c = sub.add_parser("version"); c.set_defaults(fn=cmd_version)
    c = sub.add_parser("commands"); c.add_argument("--json", action="store_true", required=True); c.set_defaults(fn=cmd_commands)
    c = sub.add_parser("usage", help="local usage counts: show, export, on, off")
    us = c.add_subparsers(required=True)
    u = us.add_parser("show"); u.set_defaults(fn=cmd_usage_show)
    u = us.add_parser("export"); u.add_argument("--out"); u.set_defaults(fn=cmd_usage_export)
    u = us.add_parser("on"); u.set_defaults(fn=lambda a: cmd_usage_set(True))
    u = us.add_parser("off"); u.set_defaults(fn=lambda a: cmd_usage_set(False))
    u = us.add_parser("log"); u.add_argument("type"); u.add_argument("pairs", nargs="*"); u.set_defaults(fn=cmd_usage_log)
    return p, sub


QUIET_COMMANDS = {"usage", "version", "commands"}  # the launcher calls version on every run: never logged


def _timed(a, name: str):
    """Run the command; log one counts-only 'command' event (name, seconds, ok, error class), then carry on."""
    import time

    from storycoach import usage

    start = time.monotonic()
    ok, error = True, None
    try:
        a.fn(a)
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code in (0, None):
            pass
        else:
            ok = False
            n = type(e).__name__
            error = n if n in usage.ERROR_CLASSES else "other"
        raise
    finally:
        if name not in QUIET_COMMANDS:  # reading or managing the stats, or asking for the version, is not itself usage
            try:
                usage.log("command", name=name, seconds=round(time.monotonic() - start, 3), ok=ok, error=error)
            except Exception as e:  # noqa: BLE001
                print(f"usage stats not recorded ({type(e).__name__})", file=sys.stderr)


def main(argv=None):
    from storycoach import usage
    from storycoach.session import UnreadableFileError

    p, sub = build_parser()
    a = p.parse_args(argv)
    name = next((n for n, fn in usage.command_table(sub) if fn is a.fn), "other")
    try:
        _timed(a, name)
    except (FileExistsError, FileNotFoundError, UnreadableFileError) as e:
        _fail(str(e))


if __name__ == "__main__":
    main()
