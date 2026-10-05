"""PR-655/PR-670 M5 protocol port from the attributed MATLAB driver.

See THIRD_PARTY_NOTICES.md and docs/protocol.md for sources and limitations.
No exposure, synchronization, accessory or calibration settings are changed.
"""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import serial

_DECIMAL_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class PRError(Exception):
    """An instrument or communication error; no automatic retry is performed."""


class InstrumentError(PRError):
    """A complete, standalone negative instrument status."""


@dataclass(frozen=True)
class Reading:
    model: str
    port: str
    started_at_utc: str
    completed_at_utc: str
    duration_seconds: float
    wavelengths_nm: tuple[float, ...]
    spectral_values: tuple[float, ...]
    units_code: float
    peak_wavelength_nm: float
    instrument_integrated_reading: float
    integrated_photon_reading: float
    raw_m5_response: str


def validate_connection(port: str, timeout: float) -> None:
    if not isinstance(port, str) or not port.strip():
        raise ValueError("Select the meter's serial port explicitly.")
    if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("The measurement timeout must be a finite positive number of seconds.")


class PRMeter:
    """One verified connection. Pass a transport and clock only in software tests."""

    MAX_REPLY_BYTES = 65536

    def __init__(self, port: str, timeout: float = 300, *, transport=None, clock=time):
        validate_connection(port, timeout)
        self.port = port
        self.timeout = timeout
        self.clock = clock
        self.model = ""
        self.warnings: list[str] = []
        self.interrupted = False
        self._buffer = bytearray()
        self._raw = bytearray()
        self._write_failed = False
        self._needs_reconnect = False
        self._transport = None
        try:
            self._transport = (
                transport
                if transport is not None
                else serial.Serial(
                    port=port,
                    baudrate=115200,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0,
                    write_timeout=min(5, timeout),
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                    **({"exclusive": True} if os.name == "posix" else {}),
                )
            )
            self._reset_input()
            self._write("Q", carriage_return=False)
            self.clock.sleep(0.5)
            self._reset_input()
            self._write("PHOTO", carriage_return=False)
            reply = self._reply("PHOTO", self.clock.monotonic() + min(10, timeout))
            if reply != "REMOTE MODE":
                raise PRError(f"Expected REMOTE MODE on {port}; received {reply!r}.")
            fields = self._fields(self._request("D111"), "D111")
            if len(fields) != 2 or fields[1].strip() not in ("PR-655", "PR-670"):
                raise PRError(
                    f"Expected PR-655 or PR-670 model identification; received {fields!r}."
                )
            self.model = fields[1].strip()
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _reset_input(self):
        self._transport.reset_input_buffer()
        self._buffer.clear()
        self._raw.clear()

    def _write(self, command: str, *, carriage_return: bool = True):
        if self._transport is None or self._write_failed:
            raise PRError(
                "The connection cannot accept commands. Wait for the meter and reconnect."
            )
        encoded = (command + ("\r" if carriage_return else "")).encode("ascii")
        try:
            self._transport.write_timeout = min(5, self.timeout)
            for byte in encoded:
                if self._transport.write(bytes((byte,))) != 1:
                    raise PRError(
                        "A serial write was incomplete. Wait for the meter and reconnect."
                    )
                self.clock.sleep(0.05)
        except BaseException:
            # A transmitted prefix makes additional cleanup commands unsafe.
            self._write_failed = True
            self._needs_reconnect = True
            raise

    def _receive(self):
        count = self._transport.in_waiting
        if count:
            if count + len(self._raw) > self.MAX_REPLY_BYTES:
                raise PRError(
                    "The reply exceeded the 64 KiB host limit. Reconnect before retrying."
                )
            data = self._transport.read(count)
            if len(self._raw) + len(data) > self.MAX_REPLY_BYTES:
                raise PRError(
                    "The reply exceeded the 64 KiB host limit. Reconnect before retrying."
                )
            self._raw.extend(data)
            self._buffer.extend(data)
        return count

    def _line(self, command: str, deadline: float) -> str:
        while self.clock.monotonic() < deadline:
            delimiter = next((i for i, byte in enumerate(self._buffer) if byte in (10, 13)), None)
            if delimiter is not None:
                data = bytes(self._buffer[:delimiter])
                del self._buffer[: delimiter + 1]
                try:
                    line = data.decode("ascii").strip()
                except UnicodeDecodeError as error:
                    raise PRError(
                        f"{command} returned non-ASCII data. Check the selected port."
                    ) from error
                if line:
                    return line
            elif not self._receive():
                self.clock.sleep(0.01)
        raise PRError(
            f"Timed out waiting for {command}. Wait for the meter to finish before retrying."
        )

    def _reply(self, command: str, deadline: float) -> str:
        line = self._line(command, deadline)
        while line == command:
            line = self._line(command, deadline)
        return line

    def _request(self, command: str) -> str:
        self._reset_input()
        self._write(command)
        return self._reply(command, self.clock.monotonic() + min(5, self.timeout))

    @staticmethod
    def _numbers(fields: list[str], context: str) -> list[float]:
        try:
            # float() also accepts Python underscore separators, which are not
            # part of the instrument's decimal/scientific response format.
            if any(_DECIMAL_NUMBER.fullmatch(field.strip()) is None for field in fields):
                raise ValueError("Expected a decimal instrument number")
            values = [float(field) for field in fields]
        except ValueError as error:
            raise PRError(f"Invalid numeric values in {context}: {fields!r}.") from error
        if not all(math.isfinite(value) for value in values):
            raise PRError(f"Nonfinite numeric values in {context}: {fields!r}.")
        return values

    @classmethod
    def _fields(cls, line: str, command: str) -> list[str]:
        fields = line.split(",")
        status = cls._numbers(fields[:1], f"{command} status")[0]
        if status != int(status):
            raise PRError(f"{command} returned a noninteger status: {line!r}.")
        if status != 0:
            if status > 0 or len(fields) != 1:
                raise PRError(f"{command} returned a malformed status: {line!r}.")
            detail = {
                -3: "Cannot synchronize: check signal level and source frequency (20–400 Hz).",
                -8: "Insufficient signal: check aim, focus, source level and exposure settings.",
                -9: "Synchronization error: check the source and meter synchronization settings.",
                -10: "Automatic synchronization failed: check source and signal level.",
            }.get(status, "Consult the manual's Remote Control Error Codes.")
            raise InstrumentError(f"{command} returned instrument error {int(status)}. {detail}")
        return fields

    def _backlight(self, percent: int):
        command = f"B{percent:02d}"
        line = self._request(command)
        if not re.fullmatch(rf"Backlight set to\s*{percent}\s*%", line, re.IGNORECASE):
            self._fields(line, command)
            raise PRError(f"Unexpected backlight response: {line!r}.")

    def measure(self) -> Reading:
        if self._needs_reconnect or self._transport is None:
            raise PRError("The previous exchange was incomplete. Wait for the meter and reconnect.")
        self._needs_reconnect = True
        started_at = datetime.now(timezone.utc).isoformat()
        started = self.clock.monotonic()
        try:
            self._backlight(0)
            self._reset_input()
            self._write("M5")
            deadline = self.clock.monotonic() + self.timeout
            header_line = self._reply("M5", deadline)
            fields = self._fields(header_line, "M5")
            if len(fields) != 5:
                raise PRError(f"Expected five fields in the M5 header; received {header_line!r}.")
            header = self._numbers(fields, "M5 header")
            step = 4 if self.model == "PR-655" else 2
            wavelengths = tuple(float(w) for w in range(380, 781, step))
            values = []
            for index, wavelength in enumerate(wavelengths, 1):
                line = self._line("M5", deadline)
                row = line.split(",")
                if len(row) != 2:
                    raise PRError(
                        f"Expected wavelength and value at spectral row {index}: {line!r}."
                    )
                actual, value = self._numbers(row, f"spectral row {index}")
                if actual != wavelength:
                    raise PRError(
                        f"Expected {wavelength:g} nm at row {index}; received {actual:g} nm."
                    )
                values.append(value)
            self._receive()
            if self._buffer.strip():
                raise PRError("M5 returned extra data after the native wavelength grid.")
            try:
                raw = self._raw.decode("ascii")
            except UnicodeDecodeError as error:
                raise PRError("M5 returned non-ASCII trailing data.") from error
            reading = Reading(
                self.model,
                self.port,
                started_at,
                datetime.now(timezone.utc).isoformat(),
                self.clock.monotonic() - started,
                wavelengths,
                tuple(values),
                header[1],
                header[2],
                header[3],
                header[4],
                raw,
            )
            self._needs_reconnect = False
        except InstrumentError:
            # A terminated standalone status is a complete failed acquisition.
            self._needs_reconnect = False
            raise
        except KeyboardInterrupt:
            self._write_failed = True
            raise
        finally:
            if not self._write_failed:
                uncertain = self._needs_reconnect
                self._needs_reconnect = True
                try:
                    self._backlight(100)
                    self._needs_reconnect = uncertain
                except KeyboardInterrupt:
                    self.interrupted = True
                    self._write_failed = True
                    self.warnings.append(
                        "Backlight restoration was interrupted; check it manually."
                    )
                except Exception as error:
                    self.warnings.append(f"Could not restore backlight to 100%: {error}")
        return reading

    def close(self):
        if self._transport is None:
            return
        try:
            if not self._write_failed:
                try:
                    self._write("Q", carriage_return=False)
                except KeyboardInterrupt:
                    self.interrupted = True
                    self.warnings.append(
                        "Remote-mode exit was interrupted; check the meter manually."
                    )
                except Exception as error:
                    self.warnings.append(f"Could not send the remote-mode exit command: {error}")
        finally:
            connection, self._transport = self._transport, None
            try:
                connection.close()
            except KeyboardInterrupt:
                self.interrupted = True
                self.warnings.append("Port closure was interrupted; check the connection manually.")
            except Exception as error:
                self.warnings.append(f"Could not close the serial port: {error}")
