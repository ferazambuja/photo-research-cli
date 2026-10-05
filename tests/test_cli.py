import csv
import json
from types import SimpleNamespace

import pytest
from conftest import FakePort

from photo_research_cli import cli, logging


def answers(monkeypatch, values):
    values = iter(values)
    monkeypatch.setattr("builtins.input", lambda: next(values))


def record_args(path):
    return ["record", "--port", "COM3", "--name", path.stem, "--timeout", "1"]


@pytest.fixture(autouse=True)
def session_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_help_explains_starting_and_does_not_open_hardware(capsys):
    assert cli.main([]) == 0
    text = capsys.readouterr().out
    assert "ports" in text and "record" in text and "export-csv" in text
    with pytest.raises(SystemExit) as caught:
        cli.main(["record", "--help"])
    assert caught.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "both output files" in text


def test_ports_lists_metadata_without_opening_hardware(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.list_ports,
        "comports",
        lambda: [
            SimpleNamespace(device="COM3", description="USB meter", hwid="USB VID:PID=1234:5678")
        ],
    )
    assert cli.main(["ports"]) == 0
    text = capsys.readouterr().err
    assert "COM3" in text and "USB meter" in text
    assert "port that reappears" in text


def test_missing_ports_has_actionable_guidance(monkeypatch, capsys):
    monkeypatch.setattr(cli.list_ports, "comports", lambda: [])
    assert cli.main(["ports"]) == 0
    assert "check cable" in capsys.readouterr().err.lower()


def test_guided_session_saves_both_files_after_each_reading(
    tmp_path, monkeypatch, scripted_session, capsys
):
    connections, scripts = scripted_session
    scripts.append(FakePort("PR-670"))
    path = tmp_path / "named readings.jsonl"
    values = iter(
        ["help", "measure", 'White, "reference"', "Répétition", "", "help", "", "", "", "quit"]
    )

    def input_with_save_check():
        value = next(values)
        if value == "help" and path.stat().st_size:
            assert len(path.read_text().splitlines()) == 1
            with path.with_suffix(".csv").open(newline="") as file:
                assert len(list(csv.DictReader(file))) == 201
        if value == "quit":
            assert len(path.read_text().splitlines()) == 2
            with path.with_suffix(".csv").open(newline="") as file:
                assert len(list(csv.DictReader(file))) == 302
        return value

    monkeypatch.setattr("builtins.input", input_with_save_check)
    assert cli.main(record_args(path)) == 0
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["sample_name"] for r in records] == ['White, "reference"', "Sample 002"]
    assert records[0]["notes"] == "Répétition"
    assert records[0]["model"] == "PR-670"
    assert all(port.closed for port in connections)
    assert len(connections) == 2
    capture = capsys.readouterr()
    assert capture.out == ""
    assert capture.err.count("Command [measure / help / quit]:") == 2
    assert "Sample name [Enter for Sample 002; help / quit]" in capture.err
    for instruction in (
        "wait for startup",
        "Aim and focus",
        "Press Enter to measure",
        "Reposition",
        "CSV (open in Excel)",
        "JSONL (complete readings)",
        "already saved",
    ):
        assert instruction in capture.err


def test_cancel_and_quit_do_not_open_meter(tmp_path, monkeypatch, scripted_session):
    connections, _ = scripted_session
    answers(monkeypatch, ["measure", "", "", "cancel", "quit"])
    path = tmp_path / "empty.jsonl"
    assert cli.main(record_args(path)) == 0
    assert path.read_bytes() == b""
    assert len(path.with_suffix(".csv").read_text().splitlines()) == 1
    assert connections == []


@pytest.mark.parametrize("outcome", ["cancel", "failure"])
def test_unsaved_next_reading_returns_to_commands_and_keeps_sequence(
    tmp_path, monkeypatch, scripted_session, capsys, outcome
):
    connections, scripts = scripted_session
    scripts.append(FakePort())
    if outcome == "failure":
        scripts.append(FakePort(frames=[b"-8\r\n"]))
    confirmation = "cancel" if outcome == "cancel" else ""
    answers(
        monkeypatch,
        ["measure", "First", "", "", "Second", "", confirmation,
         "measure", "", "", "", "quit"],
    )
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == (1 if outcome == "failure" else 0)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [(r["sequence"], r["sample_name"]) for r in records] == [
        (1, "First"), (2, "Sample 002")
    ]
    assert len(connections) == (3 if outcome == "failure" else 2)
    assert all(port.closed for port in connections)
    with path.with_suffix(".csv").open(newline="") as file:
        assert len(list(csv.DictReader(file))) == 202
    assert capsys.readouterr().err.count("Command [measure / help / quit]:") == 2


@pytest.mark.parametrize("suffix", [".jsonl", ".csv"])
def test_existing_output_refused_before_hardware(tmp_path, suffix, capsys):
    path = tmp_path / "readings.jsonl"
    existing = path.with_suffix(suffix)
    existing.write_text("keep")
    assert cli.main(record_args(path)) == 1
    assert existing.read_text() == "keep"
    text = capsys.readouterr().err
    assert str(existing) in text and "automatic filenames" in text


@pytest.mark.parametrize("extra", [["--timeout", "nan"], ["--timeout", "0"]])
def test_invalid_arguments_refused_before_output_creation(tmp_path, extra):
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path) + extra) == 1
    assert not path.exists()


def test_failed_acquisition_requires_another_operator_command(
    tmp_path, monkeypatch, scripted_session, capsys
):
    connections, scripts = scripted_session
    scripts.append(FakePort(frames=[b"-8\r\n"]))
    answers(monkeypatch, ["measure", "", "", "", "help", "measure", "", "", "", "quit"])
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 1
    assert len(connections) == 2
    assert len(path.read_text().splitlines()) == 1
    record = json.loads(path.read_text())
    assert record["sample_name"] == "Sample 001"
    assert record["sequence"] == 1
    text = capsys.readouterr().err
    assert "Insufficient signal" in text
    assert "Earlier readings stay saved" in text


def test_jsonl_save_failure_recovers_without_another_measurement(
    tmp_path, monkeypatch, scripted_session, capsys
):
    connections, _ = scripted_session
    answers(monkeypatch, ["measure", "", "", ""])
    original = logging._append_durable

    def fail_jsonl(file, data, path):
        if path.suffix == ".jsonl":
            raise OSError("Disk full")
        original(file, data, path)

    monkeypatch.setattr(logging, "_append_durable", fail_jsonl)
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 2
    assert len(connections) == 1 and connections[0].closed
    assert path.read_bytes() == b""
    capture = capsys.readouterr()
    recovery = json.loads(capture.out)
    recovery_files = list(tmp_path.glob("*.recovery-*.json"))
    assert len(recovery_files) == 1
    assert json.loads(recovery_files[0].read_text()) == recovery
    assert recovery["spectral_values"][0] == -0.125


def test_csv_save_failure_preserves_jsonl_and_reports_rebuild_command(
    tmp_path, monkeypatch, scripted_session, capsys
):
    connections, _ = scripted_session
    answers(monkeypatch, ["measure", "", "", ""])
    original = logging._append_durable

    def fail_csv(file, data, path):
        if path.suffix == ".csv":
            raise OSError("CSV full")
        original(file, data, path)

    monkeypatch.setattr(logging, "_append_durable", fail_csv)
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 2
    assert len(connections) == 1
    assert len(path.read_text().splitlines()) == 1
    capture = capsys.readouterr()
    assert capture.out == ""
    assert "reading is saved in JSONL" in capture.err
    assert "export-csv" in capture.err


@pytest.mark.parametrize("stage", ["exposure", "backlight", "exit"])
def test_interruption_preserves_only_complete_readings(
    tmp_path, monkeypatch, scripted_session, capsys, stage
):
    _, scripts = scripted_session
    port = FakePort()
    if stage == "exposure":
        port.interrupt_prefix = b"M5"
    elif stage == "backlight":
        port.interrupt_prefix = b"B1"
    else:
        port.interrupt_close = True
    scripts.append(port)
    answers(monkeypatch, ["measure", "", "", ""])
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 130
    assert port.closed
    count = 0 if stage == "exposure" else 1
    assert len(path.read_text().splitlines()) == count
    capture = capsys.readouterr()
    assert "interrupted" in capture.err.lower()


def test_cleanup_warning_is_saved_with_complete_reading(tmp_path, monkeypatch, scripted_session):
    _, scripts = scripted_session
    port = FakePort()
    port.overrides["B100"] = b"WRONG\r\n"
    scripts.append(port)
    answers(monkeypatch, ["measure", "", "", "", "quit"])
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 0
    record = json.loads(path.read_text())
    assert record["warnings"] and "backlight" in record["warnings"][0]
    assert len(record["spectral_values"]) == 101


def test_export_command_requires_no_meter(tmp_path, reading, capsys):
    source = tmp_path / "readings.jsonl"
    source.write_bytes(logging.encode_record(logging.make_record(reading, 1, "White", "", [])))
    destination = tmp_path / "export.csv"
    assert cli.main(["export-csv", str(source), "--name", destination.stem]) == 0
    assert "Exported 1" in capsys.readouterr().err


def test_recovery_is_saved_even_with_a_broken_stdout(tmp_path, reading, monkeypatch, capsys):
    record = logging.make_record(reading, 1, "White", "Unicode: 色", [])

    class BrokenOutput:
        def write(self, text):
            raise BrokenPipeError("Output pipe closed")

        def flush(self):
            pass

    monkeypatch.setattr(cli.sys, "stdout", BrokenOutput())
    cli._recover(record, tmp_path / "readings.jsonl", OSError("Disk full"))
    files = list(tmp_path.glob("*.recovery-*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["notes"] == "Unicode: 色"
    assert "Output pipe closed" in capsys.readouterr().err


def test_failed_reading_also_reports_backlight_cleanup_problem(
    tmp_path, monkeypatch, scripted_session, capsys
):
    _, scripts = scripted_session
    port = FakePort(frames=[b"-8\r\n"])
    port.overrides["B100"] = b"WRONG\r\n"
    scripts.append(port)
    answers(monkeypatch, ["measure", "", "", "", "quit"])
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 1
    assert path.read_bytes() == b""
    assert "Could not restore backlight" in capsys.readouterr().err


def test_interrupted_second_measurement_keeps_first_save(tmp_path, monkeypatch, scripted_session):
    connections, scripts = scripted_session
    interrupted = FakePort()
    interrupted.interrupt_prefix = b"M5"
    scripts.extend([FakePort(), interrupted])
    answers(monkeypatch, ["measure", "", "", "", "", "", ""])
    path = tmp_path / "readings.jsonl"
    assert cli.main(record_args(path)) == 130
    assert len(path.read_text().splitlines()) == 1
    with path.with_suffix(".csv").open(newline="") as file:
        assert len(list(csv.DictReader(file))) == 101
    assert len(connections) == 2 and all(port.closed for port in connections)


def test_default_output_creates_a_fresh_csv_and_jsonl_pair_for_each_session(
    tmp_path, monkeypatch, scripted_session
):
    connections, _ = scripted_session
    monkeypatch.chdir(tmp_path)
    for _ in range(2):
        answers(monkeypatch, ["measure", "White", "", "", "quit"])
        assert cli.main(["record", "--port", "COM3"]) == 0
    logs = list(tmp_path.glob("readings-*.jsonl"))
    tables = list(tmp_path.glob("readings-*.csv"))
    assert len(logs) == len(tables) == 2
    assert {path.stem for path in logs} == {path.stem for path in tables}
    for path in logs:
        record = json.loads(path.read_text())
        assert record["sample_name"] == "White" and record["sequence"] == 1
        assert len(record["spectral_values"]) == 101
        with path.with_suffix(".csv").open(newline="") as file:
            assert len(list(csv.DictReader(file))) == 101
    assert len(connections) == 2 and all(port.closed for port in connections)


@pytest.mark.parametrize("custom_name", [False, True])
def test_demo_saves_labeled_data_after_each_command_without_hardware(
    tmp_path, monkeypatch, scripted_session, capsys, custom_name
):
    connections, _ = scripted_session

    def forbidden_discovery():
        pytest.fail("Demo attempted serial port discovery")

    monkeypatch.setattr(cli.list_ports, "comports", forbidden_discovery)
    values = iter(["measure", "Demo white", "Trial", "", "help", "", "", "", "quit"])

    def input_with_save_check():
        value = next(values)
        if value == "help":
            path, = tmp_path.glob("*.jsonl")
            assert len(path.read_text().splitlines()) == 1
            with path.with_suffix(".csv").open(newline="") as file:
                assert len(list(csv.DictReader(file))) == 201
        if value == "quit":
            path, = tmp_path.glob("*.jsonl")
            assert len(path.read_text().splitlines()) == 2
            with path.with_suffix(".csv").open(newline="") as file:
                assert len(list(csv.DictReader(file))) == 402
        return value

    monkeypatch.setattr("builtins.input", input_with_save_check)
    arguments = ["record", "--demo"]
    if custom_name:
        arguments += ["--name", "my-demo"]
    assert cli.main(arguments) == 0
    assert connections == []
    path, = tmp_path.glob("*.jsonl")
    assert path.stem == "my-demo" if custom_name else path.stem.startswith("demo-")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [record["sequence"] for record in records] == [1, 2]
    assert [record["sample_name"] for record in records] == ["Demo white", "Sample 002"]
    assert records[0]["notes"] == "Trial"
    assert records[0]["spectral_values"] == records[1]["spectral_values"]
    for record in records:
        assert record["model"] == "PR-670"
        assert record["port"] == "DEMO"
        assert record["spectral_quantity"] == "synthetic"
        assert record["spectral_units"] == "arbitrary demo units"
        assert record["wavelengths_nm"] == list(range(380, 781, 2))
        assert len(record["spectral_values"]) == 201
        assert record["peak_wavelength_nm"] == 550
        assert max(record["spectral_values"]) == 1.0
        assert record["raw_m5_response"] == ""
        assert record["warnings"] == ["Synthetic demo data; no meter was connected."]
        assert record["acquisition_settings"] == "demo; no meter settings"
        assert record["calibration_status"] == "not_applicable"
    with path.with_suffix(".csv").open(newline="") as file:
        rows = list(csv.DictReader(file))
    assert all(row["port"] == "DEMO" for row in rows)
    assert all(row["spectral_units"] == "arbitrary demo units" for row in rows)
    text = capsys.readouterr().err
    assert "DEMO: generated sample data" in text
    assert "Saved demo reading 2" in text
    assert text.count("Command [measure / help / quit]:") == 1
    assert text.count("Sample name [Enter for Sample 002; help / quit]:") == 2
    assert "CSV (open in Excel)" in text and "JSONL (complete readings)" in text
    assert "Aim and focus" not in text and "Wait for the meter" not in text
    assert cli.main(["export-csv", str(path), "--name", "recreated-demo"]) == 0
    assert (tmp_path / "recreated-demo.csv").read_bytes() == path.with_suffix(".csv").read_bytes()


def test_demo_cancel_does_not_generate_or_save_a_reading(tmp_path, monkeypatch):
    def forbidden_generation(*args):
        pytest.fail("Cancelled demo generated a reading")

    monkeypatch.setattr(cli, "make_demo_record", forbidden_generation)
    answers(monkeypatch, ["measure", "", "", "cancel", "quit"])
    assert cli.main(["record", "--demo", "--name", "cancelled"]) == 0
    assert (tmp_path / "cancelled.jsonl").read_bytes() == b""
    assert len((tmp_path / "cancelled.csv").read_text().splitlines()) == 1


def test_demo_interrupt_keeps_saved_reading_without_meter_instructions(
    tmp_path, monkeypatch, capsys
):
    values = iter(["measure", "", "", ""])

    def interrupted_input():
        try:
            return next(values)
        except StopIteration:
            raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted_input)
    assert cli.main(["record", "--demo", "--name", "interrupted"]) == 130
    assert len((tmp_path / "interrupted.jsonl").read_text().splitlines()) == 1
    with (tmp_path / "interrupted.csv").open(newline="") as file:
        assert len(list(csv.DictReader(file))) == 201
    text = capsys.readouterr().err
    assert "Session interrupted" in text
    assert "Wait for the meter" not in text


@pytest.mark.parametrize("arguments", [[], ["--demo", "--port", "COM3"]])
def test_record_requires_either_demo_or_port_before_creating_files(tmp_path, arguments):
    with pytest.raises(SystemExit) as caught:
        cli.main(["record", *arguments])
    assert caught.value.code == 2
    assert not list(tmp_path.glob("*.jsonl"))
    assert not list(tmp_path.glob("*.csv"))
