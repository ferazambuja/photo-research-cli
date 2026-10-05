"""Support logs and device checks use documented replies, without physical ports."""

import logging

import pytest
import serial
from conftest import FakePort

from photo_research_cli import cli, diagnostics
from photo_research_cli.driver import PRError, PRMeter, UnexpectedReport


@pytest.fixture(autouse=True)
def local_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.list_ports, "comports", lambda: [])


def support_text(tmp_path):
    path, = tmp_path.glob("support-*.log")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("model", ["PR-655", "PR-670"])
@pytest.mark.parametrize("setup_tests", [False, True])
def test_check_reports_manual_examples_and_optional_model_specific_commands(
    tmp_path, monkeypatch, scripted_session, capsys, model, setup_tests
):
    connections, scripts = scripted_session
    port = FakePort(model, echo=True)
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "y" if setup_tests else "n")
    assert cli.main(["check", "--port", "COM3"]) == 0
    text = support_text(tmp_path)
    assert "Python:" in text and "System:" in text and "pySerial:" in text
    assert "115200 baud, 8N1" in text
    assert "TX command b'PHOTO'" in text and "RX" in text and "REMOTE MODE" in text
    assert "67065106" in text and "2.22D" in text
    assert "Command finished with exit status 0" in text
    assert "Device model: " + model in capsys.readouterr().err
    assert connections == [port] and port.closed
    assert not list(tmp_path.glob("*.jsonl")) and not list(tmp_path.glob("*.csv"))
    assert "M5" not in port.commands
    if setup_tests:
        assert {"SN1", "SO2", "SS0", "SU0"} <= set(port.commands)
        exclusive = {"SD0", "SF0", "SG0", "SH0"}
        assert (exclusive <= set(port.commands)) == (model == "PR-670")
        assert "D601 values unchanged" in text
    else:
        assert not any(command.startswith("S") for command in port.commands)


@pytest.mark.parametrize("failure", ["open", "query", "interrupt"])
def test_check_keeps_a_shareable_log_on_failure(
    tmp_path, monkeypatch, scripted_session, capsys, failure
):
    _, scripts = scripted_session
    port = FakePort()
    if failure == "open":
        def refused(*args):
            raise serial.SerialException("Port could not be opened")
        monkeypatch.setattr(cli, "PRMeter", refused)
    elif failure == "query":
        port.overrides["D110"] = b"unfinished"
        scripts.append(port)
    else:
        port.interrupt_prefix = b"D11"
        scripts.append(port)
    assert cli.main(["check", "--port", "COM3", "--timeout", "0.2"]) == (
        130 if failure == "interrupt" else 1
    )
    text = support_text(tmp_path)
    assert "Traceback" in text
    if failure == "query":
        assert "unfinished" in text and "Timed out waiting for D110" in text
        assert "D114" not in port.commands
    assert "Send this support log to Fernando" in capsys.readouterr().err


def test_rejected_query_is_retained_and_later_complete_queries_are_checked(
    tmp_path, monkeypatch, scripted_session
):
    _, scripts = scripted_session
    port = FakePort()
    port.overrides["D114"] = b"-1000\r\n"
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(["check", "--port", "COM3"]) == 1
    text = support_text(tmp_path)
    assert "-1000" in text and "Device software version: unavailable" in text
    assert "D601" in port.commands and port.closed


def test_counted_aperture_report_waits_for_all_fragmented_rows():
    port = FakePort("PR-670")
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        original = port.respond

        def fragmented(command):
            if command == "D117":
                port.commands.append(command)
                for index in range(4):
                    port.pending.append((port.clock.monotonic() + index * 0.12,
                                         f"00000,{index},aperture,0.00\r\n".encode()))
            else:
                original(command)

        port.respond = fragmented
        assert len(meter.query("D117", 4)) == 4


@pytest.mark.parametrize("reply", [b"00000,1,-1\r\n", b"00000,1,1.5\r\n", b"00000,1,nan\r\n"])
def test_complete_invalid_list_counts_allow_other_queries(reply):
    port = FakePort()
    port.overrides["D112"] = reply
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        with pytest.raises(UnexpectedReport):
            meter.query("D112")
        assert meter.query("D114") == [["00000", "2.22D"]]
    assert "D116" not in port.commands and "D117" not in port.commands


def test_query_refuses_state_changing_commands_before_writing():
    port = FakePort()
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        for command in ("M5", "ZResetSetup", "C", "SD1"):
            with pytest.raises(ValueError):
                meter.query(command)
    assert port.commands == ["Q", "PHOTO", "D111", "Q"]


def test_invalid_snapshot_cannot_send_any_setup_command():
    port = FakePort("PR-670")
    port.overrides["D601"] = b"00000,0,-1,-1,-1,0,0,0,0,0,1,2,9,0,0,60.00\r\n"
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        with pytest.raises(PRError, match="Cannot test SD"):
            list(meter.test_current_settings())
    assert not any(command.startswith("S") for command in port.commands)


@pytest.mark.parametrize("command,reply", [
    ("D110", b"00000,\r\n"),
    ("D120", b"00000,201,0,380,780,2,256,7,247\r\n"),
])
def test_complete_unexpected_identity_or_grid_allows_other_diagnostics(command, reply):
    port = FakePort()
    port.overrides[command] = reply
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        with pytest.raises(UnexpectedReport, match="Raw report"):
            meter.query(command)
        assert meter.query("I") == [["00000"]]


@pytest.mark.parametrize("reply", [b"00000,0,1 deg,0\r\n", b"00000,0,bad,comma,0\r\n"])
def test_incomplete_list_still_stops_the_connection_even_with_unexpected_fields(reply):
    port = FakePort()
    port.overrides["D117"] = reply
    with PRMeter("TEST", 0.2, transport=port, clock=port.clock) as meter:
        with pytest.raises(PRError, match="Timed out"):
            meter.query("D117", 2)
        with pytest.raises(PRError, match="reconnect"):
            meter.query("I")


@pytest.mark.parametrize("command,reply", [
    ("D601", b"00000,0,0\r\n"),
    ("D116", b"00000,0,Lens, with comma,Primary,Luminance,Radiance\r\n"),
    ("D112", b"00000,1,nan\r\n"),
    ("D114", b"unknown firmware format\r\n"),
])
def test_check_keeps_complete_unexpected_reports_and_continues(
    tmp_path, monkeypatch, scripted_session, capsys, command, reply
):
    _, scripts = scripted_session
    port = FakePort()
    port.overrides[command] = reply
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(["check", "--port", "COM3"]) == 1
    assert "D602" in port.commands and "D13" in port.commands and "D14" in port.commands
    assert not any(command.startswith("S") for command in port.commands)
    if command == "D112":
        assert "D116" not in port.commands and "D117" not in port.commands
    assert reply.decode().strip() in support_text(tmp_path)
    assert "continuing with the other checks" in capsys.readouterr().err
    assert port.closed


def test_unexpected_list_row_is_drained_before_next_query():
    port = FakePort("PR-670")
    original = port.respond

    def fragmented(command):
        if command == "D117":
            port.commands.append(command)
            for index in range(4):
                name = "with,comma" if index == 0 else "aperture"
                port.pending.append((port.clock.monotonic() + index * 0.12,
                                     f"0,{index},{name},0\r\n".encode()))
        else:
            original(command)

    port.respond = fragmented
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        with pytest.raises(UnexpectedReport, match="with,comma"):
            meter.query("D117", 4)
        assert meter.query("D114") == [["00000", "2.22D"]]
    assert port.pending == []


def test_text_report_preserves_non_ascii_bytes_without_guessing_encoding(
    tmp_path, monkeypatch, scripted_session, capsys
):
    _, scripts = scripted_session
    port = FakePort()
    port.overrides["D117"] = b"00000,0,1\xb0,0.00\r\n"
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(["check", "--port", "COM3"]) == 0
    assert "1\\xb0" in capsys.readouterr().err
    assert "\\xb0" in support_text(tmp_path)
    assert "D14" in port.commands and port.closed


def test_numeric_reports_still_refuse_non_ascii_values():
    port = FakePort()
    port.overrides["D112"] = b"00000,1,\xb2\r\n"
    with PRMeter("TEST", transport=port, clock=port.clock) as meter:
        with pytest.raises(UnexpectedReport, match="Invalid numeric"):
            meter.query("D112")
        assert meter.query("D114") == [["00000", "2.22D"]]


def test_stored_instrument_error_is_reported_without_failing_or_clearing_check(
    tmp_path, monkeypatch, scripted_session, capsys
):
    _, scripts = scripted_session
    port = FakePort()
    port.overrides["I"] = b"-8\r\n"
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert cli.main(["check", "--port", "COM3"]) == 0
    text = capsys.readouterr().err
    assert "stored error -8 (reported, not cleared)" in text
    assert "Instrument status: unavailable" not in text
    assert "Stored instrument error" in support_text(tmp_path)
    assert "C" not in port.commands and "D14" in port.commands


def test_log_failure_cannot_prevent_spectrum_saving(
    tmp_path, monkeypatch, scripted_session, capsys
):
    original = diagnostics._SupportHandler

    class BrokenStream:
        def write(self, text):
            raise OSError("Support volume full")

        def flush(self):
            pass

        def close(self):
            pass

    def broken_log(path):
        handler = original(path)
        handler.stream.close()
        handler.stream = BrokenStream()
        return handler

    monkeypatch.setattr(diagnostics, "_SupportHandler", broken_log)
    replies = iter(["measure", "", "", "", "quit"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert cli.main(["record", "--port", "COM3", "--name", "saved"]) == 0
    assert len((tmp_path / "saved.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert len((tmp_path / "saved.csv").read_text(encoding="utf-8").splitlines()) == 102
    assert "Support log is incomplete" in capsys.readouterr().err


def test_unhandled_interruption_is_logged_before_handler_is_removed(tmp_path):
    logger = logging.getLogger("photo_research_cli")
    before = list(logger.handlers)
    with pytest.raises(KeyboardInterrupt):
        with diagnostics.SupportLog():
            raise KeyboardInterrupt
    assert "KeyboardInterrupt" in support_text(tmp_path)
    assert logger.handlers == before


def test_setup_test_stops_when_report_changes_and_preserves_both_reports(
    tmp_path, scripted_session, monkeypatch, capsys
):
    _, scripts = scripted_session
    port = FakePort("PR-670")
    original = port.respond

    def changed(command):
        original(command)
        if command == "SN1":
            port.overrides["D601"] = b"00000,0,-1,-1,-1,0,0,0,0,0,2,2,0,0,0,60.00\r\n"

    port.respond = changed
    scripts.append(port)
    monkeypatch.setattr("builtins.input", lambda: "y")
    assert cli.main(["check", "--port", "COM3"]) == 1
    assert "SO2" not in port.commands and port.closed
    assert "before=" in support_text(tmp_path) and "after=" in support_text(tmp_path)
    assert "Check the meter settings before measuring" in capsys.readouterr().err


def test_record_keeps_protocol_and_failure_details_without_changing_measurements(
    tmp_path, monkeypatch, scripted_session
):
    _, scripts = scripted_session
    scripts.extend([FakePort(frames=[b"\xff\r\n"]), FakePort()])
    replies = iter(["measure", "", "", "", "measure", "", "", "", "quit"])
    monkeypatch.setattr("builtins.input", lambda: next(replies))
    assert cli.main(["record", "--port", "COM3", "--name", "readings"]) == 1
    text = support_text(tmp_path)
    assert "\\xff" in text and "non-ASCII" in text and "Traceback" in text
    assert "Saved reading 1" in text and "Serial port closed" in text
    assert len((tmp_path / "readings.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_log_falls_back_to_temporary_folder_when_working_folder_is_unwritable(
    tmp_path, monkeypatch
):
    original = diagnostics._SupportHandler
    temporary = tmp_path / "temporary"
    temporary.mkdir()

    def restricted(path):
        if path.parent == tmp_path:
            raise PermissionError("Folder is read-only")
        return original(path)

    monkeypatch.setattr(diagnostics, "_SupportHandler", restricted)
    monkeypatch.setattr(diagnostics.tempfile, "mkdtemp", lambda **kwargs: str(temporary))
    assert cli.main(["ports"]) == 0
    assert not list(tmp_path.glob("*.log"))
    assert "No serial ports found" in support_text(temporary)


def test_failed_diagnostic_write_does_not_interrupt_or_leak_handlers(
    tmp_path, monkeypatch, capsys
):
    class BrokenStream:
        def write(self, text):
            raise OSError("Disk full")

        def flush(self):
            pass

        def close(self):
            pass

    logger = logging.getLogger("photo_research_cli")
    before = list(logger.handlers)
    with diagnostics.SupportLog() as support:
        support.handler.stream.close()
        support.handler.stream = BrokenStream()
        logger.info("first failed write")
        logger.info("second failed write")
    assert support.handler.failed
    assert capsys.readouterr().err.count("Support log could not be updated") == 1
    assert logger.handlers == before
    assert cli.main(["ports"]) == 0
    assert logger.handlers == before
    logs = list(tmp_path.glob("*.log"))
    assert len(logs) == 2
    assert all(path.name.startswith("support-") for path in logs)
