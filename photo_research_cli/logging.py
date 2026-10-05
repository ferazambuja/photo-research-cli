"""Append complete readings to a new JSONL file; preserve records on save failure."""

from __future__ import annotations

import csv
import io
import json
import math
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from . import __version__
from .driver import Reading

CSV_COLUMNS = (
    "sequence",
    "sample_name",
    "notes",
    "model",
    "port",
    "started_at_utc",
    "completed_at_utc",
    "duration_seconds",
    "units_code",
    "peak_wavelength_nm",
    "instrument_integrated_reading",
    "integrated_photon_reading",
    "spectral_units",
    "wavelength_nm",
    "spectral_value",
)


class CsvSaveError(OSError):
    """The authoritative JSONL reading was saved, but its companion CSV failed."""

    def __init__(self, error: BaseException):
        super().__init__(str(error))
        self.interrupted = isinstance(error, KeyboardInterrupt)
        for note in getattr(error, "__notes__", ()):
            self.add_note(note)


def make_record(
    reading: Reading, sequence: int, sample: str, notes: str, warnings: list[str]
) -> dict:
    return {
        "schema_version": 1,
        "record_type": "photo_research_m5_spectrum",
        "record_id": str(uuid4()),
        "software": {"name": "photo-research-cli", "version": __version__},
        "sequence": sequence,
        "sample_name": sample,
        "notes": notes,
        **asdict(reading),
        "spectral_quantity": "instrument_reported",
        "spectral_units": "unverified; retain the reported units_code",
        "acquisition_settings": "existing meter settings; not queried or changed",
        "calibration_status": "not_checked",
        "warnings": list(warnings),
    }


def encode_record(record: dict) -> bytes:
    return (json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_all(file, data: bytes):
    remaining = memoryview(data)
    while remaining:
        count = file.write(remaining)
        if count is None or count <= 0:
            raise OSError("The file write made no progress.")
        remaining = remaining[count:]


def _csv_header() -> bytes:
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerow(CSV_COLUMNS)
    return stream.getvalue().encode("utf-8")


def _csv_reading(record: dict) -> bytes:
    if (
        not isinstance(record, dict)
        or type(record.get("schema_version")) is not int
        or record["schema_version"] != 1
        or record.get("record_type") != "photo_research_m5_spectrum"
        or record.get("model") not in ("PR-655", "PR-670")
    ):
        raise ValueError("Expected a version 1 Photo Research spectrum record.")
    wavelengths, values = record.get("wavelengths_nm"), record.get("spectral_values")
    step = 4 if record["model"] == "PR-655" else 2
    expected = list(range(380, 781, step))
    if (
        not isinstance(wavelengths, (list, tuple))
        or list(wavelengths) != expected
        or not isinstance(values, (list, tuple))
        or len(values) != len(expected)
    ):
        raise ValueError("The record does not contain its model's complete native spectrum.")
    metadata = [record[key] for key in CSV_COLUMNS[:-2]]
    numeric = [
        *wavelengths,
        *values,
        *(
            record[key]
            for key in (
                "duration_seconds",
                "units_code",
                "peak_wavelength_nm",
                "instrument_integrated_reading",
                "integrated_photon_reading",
            )
        ),
    ]
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in numeric):
        raise ValueError("CSV scientific fields must be finite real numbers.")
    if type(record["sequence"]) is not int or record["sequence"] <= 0:
        raise ValueError("The reading sequence must be a positive integer.")
    for key in (
        "sample_name",
        "notes",
        "port",
        "started_at_utc",
        "completed_at_utc",
        "spectral_units",
    ):
        if not isinstance(record[key], str):
            raise ValueError(f"{key} must be text.")
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows(
        [*metadata, wavelength, value]
        for wavelength, value in zip(wavelengths, values, strict=True)
    )
    return stream.getvalue().encode("utf-8")


def _append_durable(file, data: bytes, path: Path):
    previous_length = file.tell()
    try:
        _write_all(file, data)
        os.fsync(file.fileno())
    except BaseException as error:
        try:
            file.truncate(previous_length)
            file.seek(previous_length)
            os.fsync(file.fileno())
        except OSError as rollback_error:
            error.add_note(
                f"Could not remove an incomplete final entry from {path}: {rollback_error}. "
                "Keep the original file and inspect its tail before loading it."
            )
        raise


class ReadingLog:
    """Single owner of a newly created file; existing files are never opened for writing."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.csv_path = self.path.with_suffix(".csv")
        self._file = self.path.open("xb", buffering=0)
        self._csv = None
        try:
            self._csv = self.csv_path.open("xb", buffering=0)
            _write_all(self._csv, _csv_header())
            os.fsync(self._csv.fileno())
        except BaseException:
            self._file.close()
            self.path.unlink()
            if self._csv is not None:
                self._csv.close()
                self.csv_path.unlink()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self._file.close()
        finally:
            self._csv.close()

    def append(self, record: dict):
        data = encode_record(record)
        csv_data = _csv_reading(record)
        _append_durable(self._file, data, self.path)
        try:
            _append_durable(self._csv, csv_data, self.csv_path)
        except BaseException as error:
            raise CsvSaveError(error) from error


def save_recovery(record: dict, log_path: Path) -> Path:
    path = log_path.with_name(f"{log_path.stem}.recovery-{record['record_id']}.json")
    # An exclusive create protects any earlier recovery file too.
    with path.open("xb", buffering=0) as file:
        _write_all(file, encode_record(record))
        os.fsync(file.fileno())
    return path


def _json_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def export_csv(source: Path, destination: Path) -> int:
    """Rebuild a new CSV from complete JSONL records without using an instrument."""
    source, destination = source.expanduser().resolve(), destination.expanduser().resolve()
    if destination.suffix.lower() != ".csv":
        raise ValueError("Choose a NEW destination ending in .csv.")
    count = 0
    with source.open(encoding="utf-8") as readings:
        file = destination.open("xb", buffering=0)
        try:
            with file:
                _write_all(file, _csv_header())
                for number, line in enumerate(readings, 1):
                    try:
                        record = json.loads(line, object_pairs_hook=_json_fields)
                        _write_all(file, _csv_reading(record))
                    except (ValueError, KeyError, TypeError, OverflowError) as error:
                        raise ValueError(
                            f"Invalid JSONL record at line {number}: {error}"
                        ) from error
                    count += 1
                os.fsync(file.fileno())
        except BaseException:
            destination.unlink()
            raise
    return count
