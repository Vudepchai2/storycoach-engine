# storycoach engine

A local engine for coaching the core story inside a pitch, application or talk. It transcribes a recorded take, measures the voice (pauses, pace, pitch movement, loudness), keeps per-person memory, and prints plain facts for a coach to work from. It gives no scores.

It is the engine behind a Claude Code storytelling-coach skill, but it is a normal command line tool and runs on its own.

## Install

Using the Claude Code plugin? Don't install the engine yourself: the plugin manages it.

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and Git.

```
uv tool install git+https://github.com/Vudepchai2/storycoach-engine
storycoach setup
```

`storycoach setup` checks the install, downloads the speech model (once, about 500 MB), checks the microphone and prints a `next:` line with the one thing left to do, such as showing you the privacy note. On Linux, recording needs PortAudio (`sudo apt-get install libportaudio2`).

## Where your data lives

All personal data is in one folder: `~/StorytellingCoach/` (on Windows `%USERPROFILE%\StorytellingCoach`). Set the `STORYCOACH_HOME` environment variable to put it somewhere else.

It holds `sessions/`, `people/` and `usage/`, plus a `README.txt` saying what is in each. Nothing in it is uploaded.

To bring data over from an older project folder, run `storycoach import-legacy <folder>`. It copies `sessions/` and `people/` in and leaves the originals untouched.

## Commands

Run `storycoach commands --json` for the exact list with options.

| Command | What it does |
| --- | --- |
| `new` | Start a session (scenario, occasion, person, memory) |
| `status` | List sessions |
| `record <session>` | Record from the default microphone to a 16 kHz mono WAV; `--stop` ends it |
| `analyse <session> [audio]` | Transcribe and measure a take; `--latest` uses the newest recording |
| `features`, `clip`, `compare` | Inspect a take, cut a clip, compare two takes |
| `focus` | Set or clear what the next take should work on |
| `practice <case>` | Run a synthetic practice case, no microphone needed |
| `reference-add`, `reference-build` | Build voice reference measurements |
| `blind`, `blind-tally` | Blind listener rounds |
| `close` | Close a session (`--delete` removes it) |
| `memory init/retain/import/brief/recall/gaps/pages/forget/delete/link` | Per-person memory |
| `import-legacy <folder>` | Copy older `sessions/` and `people/` into the data home |
| `setup` | Check the install, fetch the model, acknowledge privacy |
| `usage show` | Readable summary of local usage |
| `usage export [--out file]` | Write that summary as JSON and print it in full |
| `usage on` / `usage off` | Turn local usage stats on or off |
| `usage log <type> [key=value ...]` | Record a skill-side usage event |
| `version`, `commands` | Version and command list |

## What is measured

Pauses, pace, pitch movement and loudness come from the audio. Fillers ("um", "like") come from the transcript, so treat the count as a low estimate: the speech model tends to drop them. The coach reads these measurements; it never hears the audio.

## Privacy

Everything runs on your machine. Audio, transcripts and memory stay in the data home. The only network use is the one-time speech-model download (about 500 MB) during `setup`, or on the first transcription if setup was skipped. Recordings, transcripts, memory and usage stats never leave the machine.

Usage stats are local too. They are written to `usage/events.jsonl` as events with a type, a UTC timestamp and a random install id, never a name, account or hardware id, and never the text of a question or story. `storycoach usage off` stops all writing. `storycoach usage export` shows exactly what you would share; nothing is sent for you.

## Development

```
pip install -e . pytest
pytest -q -m "not slow"
```

The dependency bounds in `pyproject.toml` are the majors tested for a release and move with engine releases.

Tests marked `slow` need the Whisper model, and some also need Windows speech synthesis; they skip elsewhere. A scrub test checks that no private terms or email addresses ship.

## Licence

Apache-2.0, see `LICENSE` and `NOTICE`. The `praat-parselmouth` dependency is GPLv3+ and is installed separately from PyPI.
