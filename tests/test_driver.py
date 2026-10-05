import math

import pytest
import serial
from conftest import FakePort, frame

from photo_research_cli.driver import InstrumentError, PRError, PRMeter


def connect(port, timeout=2):
    return PRMeter("COM3", timeout, transport=port, clock=port.clock)


@pytest.mark.parametrize("model,step,count", [("PR-655", 4, 101), ("PR-670", 2, 201)])
@pytest.mark.parametrize("newline", ["\r", "\n", "\r\n"])
@pytest.mark.parametrize("echo", [False, True])
def test_complete_native_reading_preserves_values_and_units(model, step, count, newline, echo):
    port = FakePort(model, frames=[frame(model, newline)], echo=echo)
    with connect(port) as meter:
        reading = meter.measure()
        assert reading.model == model
        assert reading.port == "COM3"
        assert reading.wavelengths_nm == tuple(range(380, 781, step))
        assert len(reading.spectral_values) == count
        assert reading.spectral_values == (-0.125, *(1.25 for _ in range(count - 1)))
        assert reading.units_code == 0
        assert reading.peak_wavelength_nm == 550
        assert reading.instrument_integrated_reading == 0.1827
        assert reading.integrated_photon_reading == 51.47
        assert reading.raw_m5_response.endswith(frame(model, newline).decode("ascii"))
        assert reading.completed_at_utc >= reading.started_at_utc
        assert reading.duration_seconds >= 0
    assert port.closed
    assert port.commands == ["Q", "PHOTO", "D111", "B00", "M5", "B100", "Q"]
    assert sum(sleep == 0.05 for sleep in port.clock.sleeps) == 24
    assert meter.warnings == []


def test_delayed_fragmented_spectrum_does_not_finish_at_an_empty_buffer():
    port = FakePort()
    response = frame()
    port.chunks = [response[:1], response[1:25], response[25:73], response[73:]]
    port.delays = [0, 0.12, 0.43, 0.8]
    with connect(port, timeout=1) as meter:
        reading = meter.measure()
    assert len(reading.spectral_values) == 101
    assert reading.raw_m5_response == response.decode("ascii")
    assert reading.duration_seconds >= 0.8


@pytest.mark.parametrize(
    "bad_frame",
    [
        b"",
        b"0,0,550,1,2\r\n380,1\r\n",
        frame()[:-2],
        b"0,0,550,1\r\n",
        b"0,nan,550,1,2\r\n",
        b"0,0,550,1,2\r\n380,NaN\r\n",
        b"0,0,550,1,2\r\n380,inf\r\n",
        b"0,0,550,1,2\r\n382,1\r\n",
        b"0,0,550,1,2\r\n380,1,2\r\n",
        frame() + b"784,1\r\n",
        frame() + b"784,",
        b"380,1\r\n",
        b"-8,extra\r\n",
        b"1\r\n",
        b"0.5,0,550,1,2\r\n",
        b"\xff\r\n",
    ],
)
def test_incomplete_or_malformed_spectrum_never_publishes_a_reading(bad_frame):
    port = FakePort(frames=[bad_frame])
    with connect(port, timeout=0.3) as meter:
        with pytest.raises(PRError):
            meter.measure()
        with pytest.raises(PRError, match="reconnect"):
            meter.measure()
    assert port.commands.count("M5") == 1
    assert port.closed


@pytest.mark.parametrize(
    "original,replacement",
    [
        (b"0,0,550", b"0_0,0,550"),
        (b"0,0,550", b"0,1_1,550"),
        (b"0,0,550", b"0,0,5_50"),
        (b"0.1827", b"0.1_827"),
        (b"51.47", b"5_1.47"),
        (b"380,-0.125", b"3_80,-0.125"),
        (b"380,-0.125", b"380,-0.1_25"),
    ],
)
def test_python_numeric_literals_are_not_valid_instrument_numbers(original, replacement):
    port = FakePort(frames=[frame().replace(original, replacement)])
    with connect(port) as meter:
        with pytest.raises(PRError, match="Invalid numeric"):
            meter.measure()
        with pytest.raises(PRError, match="reconnect"):
            meter.measure()
    assert port.commands.count("M5") == 1
    assert port.closed


def test_all_rows_share_one_deadline():
    port = FakePort()
    response = frame()
    port.chunks = [response[:25], response[25:]]
    port.delays = [0.1, 1.0]
    with connect(port, timeout=0.3) as meter:
        with pytest.raises(PRError, match="Timed out"):
            meter.measure()
    assert port.clock.monotonic() < 3.0


@pytest.mark.parametrize("code", [-3, -8, -9, -10, -9876])
def test_standalone_instrument_error_is_not_retried(code):
    port = FakePort(frames=[f"{code}\r\n".encode("ascii"), frame()])
    with connect(port) as meter:
        with pytest.raises(InstrumentError, match=f"error {code}"):
            meter.measure()
        assert port.commands.count("M5") == 1
        reading = meter.measure()  # Explicit caller request, not an automatic retry.
        assert len(reading.spectral_values) == 101
    assert port.commands.count("M5") == 2


def test_unsupported_model_is_refused_before_acquisition():
    port = FakePort("PR-650")
    with pytest.raises(PRError, match="model identification"):
        connect(port)
    assert "M5" not in port.commands
    assert port.closed


@pytest.mark.parametrize("response", [b"", b"REMOTE WRONG\r\n"])
def test_remote_mode_must_be_verified(response):
    port = FakePort()
    port.overrides["PHOTO"] = response
    with pytest.raises(PRError):
        connect(port, timeout=0.1)
    assert "D111" not in port.commands
    assert port.closed


def test_partial_initialization_write_forbids_cleanup_commands():
    port = FakePort()
    port.fail_prefix = b"D1"
    with pytest.raises(serial.SerialTimeoutException):
        connect(port)
    assert port.commands == ["Q", "PHOTO"]
    assert b"".join(port.writes).endswith(b"D1")
    assert port.closed


def test_partial_measurement_write_forbids_backlight_and_exit_writes():
    port = FakePort()
    with connect(port) as meter:
        port.fail_prefix = b"M"
        with pytest.raises(serial.SerialTimeoutException):
            meter.measure()
    assert port.commands == ["Q", "PHOTO", "D111", "B00"]
    assert b"".join(port.writes).endswith(b"M")
    assert port.closed


def test_short_write_is_also_a_failed_write():
    port = FakePort()
    meter = connect(port)
    port.write = lambda byte: 0
    with pytest.raises(PRError, match="incomplete"):
        meter.measure()
    meter.close()
    assert port.closed


@pytest.mark.parametrize("failure", ["bad_ack", "write_timeout", "interrupt"])
def test_complete_reading_survives_backlight_cleanup_failure(failure):
    port = FakePort()
    with connect(port) as meter:
        if failure == "bad_ack":
            port.overrides["B100"] = b"WRONG\r\n"
        elif failure == "write_timeout":
            port.fail_prefix = b"B1"
        else:
            port.interrupt_prefix = b"B1"
        reading = meter.measure()
        assert len(reading.spectral_values) == 101
    assert meter.warnings
    assert meter.interrupted == (failure == "interrupt")
    assert port.closed
    if failure != "bad_ack":
        assert port.commands.count("Q") == 1


def test_interrupt_before_completion_publishes_no_reading_and_sends_no_cleanup():
    port = FakePort()
    with connect(port) as meter:
        port.interrupt_prefix = b"M5"
        with pytest.raises(KeyboardInterrupt):
            meter.measure()
    assert port.commands == ["Q", "PHOTO", "D111", "B00"]
    assert port.closed


def test_reply_limit_refuses_before_large_read():
    port = FakePort(frames=[b"x" * (PRMeter.MAX_REPLY_BYTES + 1)])
    with connect(port) as meter:
        with pytest.raises(PRError, match="64 KiB"):
            meter.measure()
    assert port.closed


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True])
def test_invalid_timeout_does_not_open_hardware(timeout):
    with pytest.raises(ValueError, match="timeout"):
        PRMeter("COM3", timeout)


def test_blank_port_does_not_open_hardware():
    with pytest.raises(ValueError, match="explicitly"):
        PRMeter(" ")


@pytest.mark.parametrize("reply", [b"Backlight set to 00 %\r\n", b"Backlight set to 000%\r\n"])
def test_zero_padded_backlight_acknowledgement_allows_measurement(reply):
    port = FakePort()
    port.overrides["B00"] = reply
    with connect(port) as meter:
        assert len(meter.measure().spectral_values) == 101
        assert meter.warnings == []
    assert "M5" in port.commands and port.closed


@pytest.mark.parametrize("reply", [b"Display off\r\n", b"-1000\r\n", b"00000\r\n"])
def test_complete_unconfirmed_backlight_reply_warns_and_preserves_reading(reply):
    port = FakePort()
    port.overrides["B00"] = reply
    with connect(port) as meter:
        reading = meter.measure()
        assert len(reading.spectral_values) == 101
        assert reading.raw_m5_response == frame().decode("ascii")
        assert "Backlight-off command was not confirmed" in meter.warnings[0]
    assert port.commands[-3:] == ["M5", "B100", "Q"]


@pytest.mark.parametrize("reply", [b"", b"Display off", b"Display off\r\nextra"])
def test_incomplete_backlight_exchange_cannot_start_measurement(reply):
    port = FakePort()
    port.overrides["B00"] = reply
    with connect(port, timeout=0.2) as meter:
        with pytest.raises(PRError):
            meter.measure()
        with pytest.raises(PRError, match="reconnect"):
            meter.measure()
    assert "M5" not in port.commands and port.closed


@pytest.mark.parametrize("stage", ["in_waiting", "read"])
def test_serial_disconnection_mid_spectrum_refuses_reading_and_closes_port(stage):
    class DisconnectedPort(FakePort):
        read_spectrum = False
        disconnected = False

        @property
        def in_waiting(self):
            if stage == "in_waiting" and self.read_spectrum and not self.disconnected:
                self.disconnected = True
                raise serial.SerialException("Disconnected during spectrum")
            return super().in_waiting

        def read(self, count):
            if stage == "read" and self.read_spectrum and not self.disconnected:
                self.disconnected = True
                raise serial.SerialException("Disconnected during spectrum")
            data = super().read(count)
            if self.has_measured:
                self.read_spectrum = True
            return data

    port = DisconnectedPort()
    port.chunks = [frame()[:150], frame()[150:]]
    port.delays = [0, 0.12]
    with connect(port) as meter:
        with pytest.raises(serial.SerialException, match="Disconnected"):
            meter.measure()
        with pytest.raises(PRError, match="reconnect"):
            meter.measure()
    assert port.closed and port.commands.count("M5") == 1


@pytest.mark.parametrize("system", ["posix", "nt"])
def test_serial_open_options_match_platform(monkeypatch, system):
    from types import SimpleNamespace

    from photo_research_cli import driver

    port = FakePort()
    options = {}

    def open_serial(**kwargs):
        options.update(kwargs)
        return port

    monkeypatch.setattr(driver, "os", SimpleNamespace(name=system))
    monkeypatch.setattr(driver.serial, "Serial", open_serial)
    with PRMeter("SOFTWARE_TEST", clock=port.clock):
        pass
    assert options["baudrate"] == 115200
    assert options["xonxoff"] is options["rtscts"] is options["dsrdtr"] is False
    if system == "posix":
        assert options["exclusive"] is True
    else:
        assert "exclusive" not in options
