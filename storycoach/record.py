"""Record a take from the default microphone, stopped by a stop file, a time limit or Ctrl+C."""
import json
import os
import signal
import sys
import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

BLOCK_S = 0.1
STALE_GRACE_S = 30
LOCK_NAME = ".recording.lock"
STOP_NAME = ".stop"
STOP_WAIT_S = 5.0  # how long `record --stop` waits for the recorder to finish
STREAM_FACTORY = None  # tests replace this; None means the real microphone


def default_factory(rate: int = 16000):
    import sounddevice  # lazy: importing this module must work without PortAudio

    return sounddevice.InputStream(samplerate=rate, channels=1, dtype="int16")


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt


def _install_signal_handlers() -> dict:
    """Best effort: turn termination signals into KeyboardInterrupt so the wav is closed properly."""
    old = {}
    if threading.current_thread() is not threading.main_thread():
        return old
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            old[sig] = signal.signal(sig, _raise_interrupt)
        except (OSError, ValueError):
            pass
    return old


def record(out: Path, stop_file: Path, max_s: float, stream_factory=None, rate: int = 16000) -> dict:
    out, stop_file = Path(out), Path(stop_file)
    factory = stream_factory or (lambda: default_factory(rate))
    block = max(1, int(rate * BLOCK_S))
    limit = int(max_s * rate)
    frames = 0
    peak = 0
    stopped_by = "time_limit"
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = open(out, "xb")  # exclusive: never truncate an existing take
    w = wave.open(raw, "wb")  # open before the first read; closed in finally so the header is valid
    old_handlers = _install_signal_handlers()
    try:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        try:
            with factory() as stream:
                while True:
                    data, _overflowed = stream.read(block)
                    data = np.asarray(data, dtype=np.int16).reshape(-1)
                    w.writeframes(data.tobytes())
                    frames += len(data)
                    if len(data):
                        peak = max(peak, int(np.abs(data.astype(np.int32)).max()))
                    if stop_file.exists():
                        stopped_by = "stop_file"
                        break
                    if frames >= limit:
                        stopped_by = "time_limit"
                        break
        except KeyboardInterrupt:
            stopped_by = "interrupt"
    finally:
        for sig, handler in old_handlers.items():
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass
        w.close()
        raw.close()
    return {"path": str(out), "seconds": frames / rate, "stopped_by": stopped_by, "peak": peak / 32768}


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(session: Path) -> Path:
    return Path(session) / "recordings" / LOCK_NAME


def stop_path(session: Path) -> Path:
    return Path(session) / "recordings" / STOP_NAME


def write_lock(path: Path, max_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"pid": os.getpid(), "started": datetime.now().astimezone().isoformat(), "max_s": max_s})
    with open(path, "x", encoding="utf-8", newline="\n") as f:  # exclusive: losing a race raises FileExistsError
        f.write(text)


def lock_is_ours(path: Path) -> bool:
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["pid"]) == os.getpid()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def lock_is_stale(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        pid, started, max_s = int(d["pid"]), datetime.fromisoformat(d["started"]), float(d["max_s"])
    except (OSError, ValueError, KeyError, TypeError):
        return True  # unreadable lock: nothing a live recorder would have written
    if not _pid_alive(pid):
        return True
    now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
    return (now - started).total_seconds() > max_s + STALE_GRACE_S


def new_take_path(session: Path) -> Path:
    base = f"take_{datetime.now():%Y%m%d-%H%M%S}"
    folder = Path(session) / "recordings"
    path, n = folder / f"{base}.wav", 1
    while path.exists():
        n += 1
        path = folder / f"{base}-{n}.wav"
    return path


PORTAUDIO_HINT = ("PortAudio is missing. Install it with: sudo apt install libportaudio2 (Debian/Ubuntu), "
                  "sudo dnf install portaudio (Fedora) or sudo pacman -S portaudio (Arch).")


def permission_hint(platform: str) -> str:
    if platform == "darwin":
        return ("The recording was silent. Allow Microphone access for this terminal app in "
                "System Settings > Privacy & Security > Microphone, then record again.")
    if platform == "win32":
        return ("The recording was silent. Allow Microphone access in "
                "Settings > Privacy & security > Microphone, then record again.")
    return "The recording was silent. Check that a Microphone is connected, selected and not muted."
