import json
import shutil
import subprocess
import sys

import pytest


def run_module(*args):
    return subprocess.run([sys.executable, "-m", "storycoach", *args], capture_output=True, text=True)


def test_version_command():
    r = run_module("version")
    assert r.returncode == 0
    assert r.stdout == "storycoach 0.1.0\n"


def test_commands_json_lists_every_subcommand():
    r = run_module("commands", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    for name in ("record", "setup", "usage log", "practice", "import-legacy", "memory brief", "memory retain"):
        assert name in data["commands"]
    assert "--scenario" in data["commands"]["new"]
    assert data["gap_sections"]["open_conflict"] == "Recall: checking a number"


def test_commands_json_shape():
    data = json.loads(run_module("commands", "--json").stdout)
    assert data["version"] == "0.1.0"
    assert "--time-limit" in data["commands"]["new"] and "founder" in data["commands"]["new"]
    assert "memory brief" in data["commands"] and "memory" not in data["commands"]


def test_installed_script_runs():
    exe = shutil.which("storycoach")
    if exe is None:
        pytest.skip("storycoach script not installed")
    r = subprocess.run([exe, "version"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "storycoach 0.1.0\n"
