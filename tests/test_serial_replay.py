"""Run the source script through pySerial and a local terminal, never a meter.

Replies follow the manufacturer's M5/D111/B examples. Complete spectra are
constructed test data, not device captures. This test does not use FakePort.
"""

import csv
import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pty = pytest.importorskip("pty", reason="Local serial replay needs a POSIX pseudo-terminal")
SCRIPT = Path(__file__).resolve().parents[1] / "pr_meter.py"


@pytest.mark.parametrize("model,step", [("PR-655", 4), ("PR-670", 2)])
@pytest.mark.parametrize("mode", ["record", "check"])
def test_direct_script_replays_documented_protocol_through_pyserial(tmp_path, model, step, mode):
    master, slave = pty.openpty()
    port_name = os.ttyname(slave)
    guard = tmp_path / "guard"
    guard.mkdir()
    # The child uses real pySerial, but can open only the terminal created above.
    (guard / "sitecustomize.py").write_text(
        "import serial\n"
        "original_serial = serial.Serial\n"
        "def local_serial(*args, **kwargs):\n"
        "    port = kwargs.get('port', args[0] if args else None)\n"
        f"    if port != {port_name!r}:\n"
        "        raise AssertionError('Serial replay attempted a physical port')\n"
        "    return original_serial(*args, **kwargs)\n"
        "serial.Serial = local_serial\n"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment["PYTHONPATH"] = str(guard)
    wavelengths = list(range(380, 781, step))
    values = [(-1 if index % 3 == 0 else 1) * (index + 1) * 1e-7
              for index in range(len(wavelengths))]
    # The header is the manual's exact example; remaining rows are synthetic.
    spectrum = "00000,0,0.000e+000,1.827e-01,5.147e+01\r\n"
    spectrum += "".join(f"{w},{value:.6e}\r\n" for w, value in zip(wavelengths, values))
    commands = []
    errors = []
    stopping = threading.Event()
    # Diagnostic examples from Rev. B, printed pages 117–121. The PR-655
    # configuration and aperture count are constructed variants for that model.
    reports = {
        "I": "00000",
        "D110": "00000,67065106",
        "D114": "00000,2.22D",
        "D112": "00000,1,4" if model == "PR-670" else "00000,1,1",
        "D116": "00000,0,MS-75,Primary,Luminance,Radiance",
        "D117": "00000,0,1 deg,0.00",
        "D120": ("00000,201,0.00,380,780,2,256,7,247" if model == "PR-670"
                 else "00000,101,0.00,380,780,4,128,0,127"),
        "D601": "00000,0,-1,-1,-1,0,0,0,0,0,1,2,0,0,0,60.00",
        "D602": ("00000,MS-75,None,None,None,1 deg,English,Adaptive,0 msec,Normal,"
                 "1 cycles,2 deg,No Smart Dark,No Sync,Standard Sensitivity,60.00 Hertz"),
        "D13": "00000,Fast,16500 msec",
        "D14": "00000,User Sync,120.00 Hertz",
    }
    if model == "PR-670":
        reports["D117"] += ("\r\n00000,1,1/2 deg,0.00\r\n00000,2,1/4 deg,0.00"
                            "\r\n00000,3,1/8 deg,0.00")
    setup_commands = ["SN1", "SO2", "SS0", "SU0"]
    if model == "PR-670":
        setup_commands += ["SD0", "SF0", "SG0", "SH0"]

    def send(data):
        while data:
            count = os.write(master, data)
            assert count > 0
            data = data[count:]

    def replay():
        command = bytearray()
        try:
            while not stopping.is_set():
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                data = os.read(master, 1024)
                if not data:
                    break
                for byte in data:
                    if not command and byte == ord("Q"):
                        commands.append("Q")
                        continue
                    command.append(byte)
                    if command == b"PHOTO":
                        commands.append("PHOTO")
                        send(b"REMOTE MODE\r\n")
                        command.clear()
                    elif byte == 13:
                        text = command[:-1].decode("ascii")
                        commands.append(text)
                        command.clear()
                        # Echo each terminated command before its response.
                        send(text.encode("ascii") + b"\r\n\n")
                        if text == "D111":
                            send(f"00000,{model}\r\n".encode("ascii"))
                        elif text in ("B00", "B100"):
                            send(f"Backlight set to {int(text[1:])} %\r\n".encode("ascii"))
                        elif text in reports:
                            response = (reports[text] + "\r\n").encode("ascii")
                            if text == "D117":
                                for line in response.splitlines(keepends=True):
                                    send(line)
                                    time.sleep(0.12)
                            else:
                                send(response)
                        elif text in setup_commands:
                            send(b"00000\r\n")
                        elif text == "M5":
                            response = spectrum.encode("ascii")
                            for chunk in (response[:17], response[17:113], response[113:]):
                                send(chunk)
                                # Gaps exceed the idle period used by older examples.
                                time.sleep(0.12)
                        else:
                            raise AssertionError(f"Unexpected command: {text!r}")
        except BaseException as error:
            errors.append(error)

    server = threading.Thread(target=replay, daemon=True)
    server.start()
    arguments = (["record", "--port", port_name, "--timeout", "2", "--name", "serial-replay"]
                 if mode == "record" else ["check", "--port", port_name, "--timeout", "2"])
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=tmp_path,
            env=environment,
            input="measure\nReference\nTrial\n\n\n\n\nquit\n" if mode == "record" else "y\n",
            text=True,
            capture_output=True,
            timeout=20,
        )
    finally:
        stopping.set()
        server.join(timeout=2)
        os.close(slave)
        os.close(master)
    assert not server.is_alive()
    assert not errors, errors
    assert result.returncode == 0, result.stderr
    log_path, = tmp_path.glob("support-*.log")
    text = log_path.read_text(encoding="utf-8")
    assert "RX" in text and "TX complete" in text and model in text
    assert "Command finished with exit status 0" in text
    assert str(log_path) in result.stderr
    if mode == "check":
        expected = ["Q", "PHOTO", "D111", "I", "D110", "D114", "D112", "D116", "D117",
                    "D120", "D601", "D602", "D13", "D14", "D601"]
        for command in setup_commands:
            expected += [command, "D601"]
        assert commands == expected + ["Q"]
        assert "67065106" in text and "2.22D" in text
        assert not list(tmp_path.glob("*.jsonl")) and not list(tmp_path.glob("*.csv"))
        return
    assert commands == ["Q", "PHOTO", "D111", "B00", "M5", "B100", "Q"] * 2
    records = [
        json.loads(line) for line in (tmp_path / "serial-replay.jsonl").read_text().splitlines()
    ]
    assert [record["sample_name"] for record in records] == ["Reference", "Sample 002"]
    for record in records:
        assert record["model"] == model
        assert record["wavelengths_nm"] == wavelengths
        assert record["spectral_values"] == pytest.approx(values)
        assert record["raw_m5_response"] == "M5\r\n\n" + spectrum
        assert record["units_code"] == 0 and record["peak_wavelength_nm"] == 0
        assert record["instrument_integrated_reading"] == 0.1827
        assert record["integrated_photon_reading"] == 51.47
        assert record["warnings"] == []
    with (tmp_path / "serial-replay.csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 2 * len(wavelengths)
    assert result.stderr.count("Command [measure / help / quit]:") == 1
