"""Automatic support logs for the CLI and serial driver."""

from __future__ import annotations

import logging
import platform
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import serial

from . import __version__


class _SupportHandler(logging.FileHandler):
    """A diagnostic write failure must not interrupt an acquisition or cleanup."""

    def __init__(self, path: Path):
        super().__init__(path, mode="x", encoding="utf-8", errors="backslashreplace")
        self.failed = False

    def emit(self, record):
        if not self.failed:
            super().emit(record)

    def handleError(self, record):
        self.failed = True
        try:
            print(
                "Support log could not be updated. The session will continue.",
                file=sys.stderr,
                flush=True,
            )
        except OSError:
            pass


class _SupportFormatter(logging.Formatter):
    converter = time.gmtime

    def __init__(self):
        super().__init__("%(asctime)sZ +%(elapsed).3fs %(levelname)s %(message)s")
        self.started = time.monotonic()

    def format(self, record):
        record.elapsed = time.monotonic() - self.started
        return super().format(record)


class SupportLog:
    """Attach a flushed, timestamped file handler only for the current CLI run."""

    def __init__(self):
        name = f"support-{datetime.now():%Y-%m-%d_%H-%M-%S-%f}.log"
        self.path = Path(name).resolve()
        try:
            self.handler = _SupportHandler(self.path)
        except OSError:
            # Keep a support log even when the measurements folder is unwritable.
            self.path = Path(tempfile.mkdtemp(prefix="photo-research-support-")) / name
            self.handler = _SupportHandler(self.path)
        self.handler.setFormatter(_SupportFormatter())
        self.logger = logging.getLogger("photo_research_cli")

    def __enter__(self):
        self.previous_level = self.logger.level
        self.previous_propagate = self.logger.propagate
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.addHandler(self.handler)
        self.logger.info("Photo Research spectrum logger %s", __version__)
        self.logger.info("Python: %s", sys.version.replace("\n", " "))
        self.logger.info("System: %s", platform.platform())
        self.logger.info("pySerial: %s", serial.__version__)
        self.logger.info("Working folder: %s", Path.cwd())
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            self.logger.error("Run ended unexpectedly", exc_info=(kind, error, traceback))
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.previous_level)
        self.logger.propagate = self.previous_propagate
        try:
            self.handler.close()
        except OSError:
            self.handler.failed = True
