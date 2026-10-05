"""The source script runs without installing the project or an application launcher."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "pr_meter.py"


@pytest.mark.parametrize("mode", ["help", "empty", "demo"])
def test_direct_script_runs_from_another_folder_without_hardware(tmp_path, mode):
    guard = tmp_path / "guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import serial\n"
        "def forbidden(*args, **kwargs):\n"
        '    raise AssertionError("Direct script attempted physical serial access")\n'
        "serial.Serial = forbidden\n"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    # No project import path or installed project is needed. Only the hardware
    # guard is placed on PYTHONPATH for this separate interpreter.
    environment["PYTHONPATH"] = str(guard)
    arguments = {
        "help": ["--help"],
        "empty": ["record", "--port", "SOFTWARE_TEST", "--name", "empty"],
        "demo": ["record", "--demo", "--name", "my-demo"],
    }[mode]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=tmp_path,
        env=environment,
        input="measure\nMy demo\nTrial\n\n\n\n\nquit\n" if mode == "demo" else "quit\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    if mode == "empty":
        assert "0 complete reading(s)" in result.stderr
        assert (tmp_path / "empty.jsonl").read_bytes() == b""
        assert (tmp_path / "empty.csv").read_text().startswith("sequence,sample_name,")
    elif mode == "demo":
        assert "Saved demo reading 2" in result.stderr
        assert result.stderr.count("Command [measure / help / quit]:") == 1
        records = [
            json.loads(line) for line in (tmp_path / "my-demo.jsonl").read_text().splitlines()
        ]
        assert records[0]["port"] == "DEMO" and records[0]["sample_name"] == "My demo"
        assert records[1]["sample_name"] == "Sample 002"
        assert len((tmp_path / "my-demo.csv").read_text().splitlines()) == 403
    else:
        assert "python pr_meter.py" in result.stdout
