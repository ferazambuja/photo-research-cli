"""Scripted serial replies. Physical port creation is forbidden in every test."""

import pytest
import serial


@pytest.fixture(autouse=True)
def forbid_hardware(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A software test attempted to open a physical serial port")

    monkeypatch.setattr(serial, "Serial", forbidden)


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


def frame(model="PR-655", newline="\r\n"):
    step = 4 if model == "PR-655" else 2
    rows = ["0,0,550,0.1827,51.47"]
    rows += [f"{w},{'-0.125' if w == 380 else '1.25'}" for w in range(380, 781, step)]
    return (newline.join(rows) + newline).encode("ascii")


class FakePort:
    def __init__(self, model="PR-655", *, clock=None, frames=None, echo=False):
        self.clock = clock or FakeClock()
        self.model = model
        self.frames = list(frames) if frames is not None else [frame(model)]
        self.echo = echo
        self.buffer = bytearray()
        self.pending = []
        self.command = bytearray()
        self.commands = []
        self.writes = []
        self.closed = False
        self.write_timeout = None
        self.overrides = {}
        self.fail_prefix = None
        self.interrupt_prefix = None
        self.interrupt_close = False
        self.has_measured = False
        self.chunks = None
        self.delays = None

    @property
    def in_waiting(self):
        while self.pending and self.clock.monotonic() >= self.pending[0][0]:
            _, data = self.pending.pop(0)
            self.buffer.extend(data)
        return len(self.buffer)

    def read(self, count):
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def reset_input_buffer(self):
        self.buffer.clear()

    def write(self, byte):
        assert isinstance(byte, bytes) and len(byte) == 1
        assert self.write_timeout is not None and self.write_timeout > 0
        self.writes.append(byte)
        prefix = bytes(self.command) + byte
        if prefix == self.fail_prefix:
            raise serial.SerialTimeoutException("Scripted partial write timeout")
        if prefix == self.interrupt_prefix or (
            self.interrupt_close and byte == b"Q" and self.has_measured
        ):
            raise KeyboardInterrupt
        if not self.command and byte == b"Q":
            self.respond("Q")
        elif byte == b"\r":
            self.respond(self.command.decode("ascii"))
            self.command.clear()
        else:
            self.command.extend(byte)
            if self.command == b"PHOTO":
                self.respond("PHOTO")
                self.command.clear()
        return 1

    def respond(self, command):
        self.commands.append(command)
        if command == "Q":
            return
        if command in self.overrides:
            response = self.overrides[command]
        elif command == "PHOTO":
            response = b"REMOTE MODE\r\n"
        elif command == "D111":
            response = f"00000,{self.model}\r\n".encode("ascii")
        elif command == "I":
            response = b"00000\r\n"
        elif command == "D110":
            # This serial number is a published manufacturer-manual example.
            response = b"00000,67065106\r\n"
        elif command == "D114":
            response = b"00000,2.22D\r\n"
        elif command == "D112":
            response = b"00000,1,4\r\n" if self.model == "PR-670" else b"00000,1,1\r\n"
        elif command == "D116":
            response = b"00000,0,MS-75,Primary,Luminance,Radiance\r\n"
        elif command == "D117":
            response = b"00000,0,1 deg,0.00\r\n"
            if self.model == "PR-670":
                response += (b"00000,1,1/2 deg,0.00\r\n00000,2,1/4 deg,0.00\r\n"
                             b"00000,3,1/8 deg,0.00\r\n")
        elif command == "D120":
            response = (b"00000,201,0.00,380,780,2,256,7,247\r\n" if self.model == "PR-670"
                        else b"00000,101,0.00,380,780,4,128,0,127\r\n")
        elif command == "D601":
            response = b"00000,0,-1,-1,-1,0,0,0,0,0,1,2,0,0,0,60.00\r\n"
        elif command == "D602":
            response = (b"00000,MS-75,None,None,None,1 deg,English,Adaptive,0 msec,Normal,"
                        b"1 cycles,2 deg,No Smart Dark,No Sync,Standard Sensitivity,"
                        b"60.00 Hertz\r\n")
        elif command == "D13":
            response = b"00000,Fast,16500 msec\r\n"
        elif command == "D14":
            response = b"00000,User Sync,120.00 Hertz\r\n"
        elif command in ("SN1", "SO2", "SS0", "SU0", "SD0", "SF0", "SG0", "SH0"):
            response = b"00000\r\n"
        elif command in ("B00", "B100"):
            response = f"Backlight set to {int(command[1:])}%\r\n".encode("ascii")
        elif command == "M5":
            self.has_measured = True
            response = self.frames.pop(0)
        else:
            raise AssertionError(f"Unexpected command: {command}")
        if self.echo:
            response = command.encode("ascii") + b"\r\n\n" + response
        if command == "M5" and self.chunks is not None:
            chunks, delays = self.chunks, self.delays
        else:
            chunks, delays = [response], [0]
        self.pending.extend(
            (self.clock.monotonic() + delay, data)
            for data, delay in zip(chunks, delays, strict=True)
        )
        self.pending.sort(key=lambda item: item[0])

    def close(self):
        self.closed = True


@pytest.fixture
def scripted_session(monkeypatch):
    from photo_research_cli import cli
    from photo_research_cli.driver import PRMeter

    connections = []
    scripts = []

    def factory(port, timeout):
        transport = scripts.pop(0) if scripts else FakePort()
        connections.append(transport)
        return PRMeter(port, timeout, transport=transport, clock=transport.clock)

    monkeypatch.setattr(cli, "PRMeter", factory)
    return connections, scripts


@pytest.fixture
def reading():
    from photo_research_cli.driver import PRMeter

    port = FakePort()
    with PRMeter("COM3", transport=port, clock=port.clock) as meter:
        return meter.measure()
