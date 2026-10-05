import csv
import json

import pytest

from photo_research_cli import logging
from photo_research_cli.logging import CsvSaveError, ReadingLog, export_csv, make_record


def load_csv(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def test_two_readings_append_full_jsonl_and_corresponding_csv(tmp_path, reading):
    path = tmp_path / "readings.jsonl"
    first = make_record(reading, 1, 'White, "reference"', "é\nsecond line", [])
    second = make_record(reading, 2, "Gray", "", ["Cleanup warning"])
    with ReadingLog(path) as log:
        log.append(first)
        before = path.read_bytes()
        log.append(second)
        assert path.read_bytes().startswith(before)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0] == json.loads(logging.encode_record(first))
    assert records[1] == json.loads(logging.encode_record(second))
    rows = load_csv(path.with_suffix(".csv"))
    assert len(rows) == 202
    assert rows[0]["sample_name"] == 'White, "reference"'
    assert rows[0]["notes"] == "é\nsecond line"
    assert rows[0]["spectral_value"] == "-0.125"
    assert rows[100]["wavelength_nm"] == "780.0"
    assert rows[101]["sequence"] == "2"
    assert rows[101]["sample_name"] == "Gray"


@pytest.mark.parametrize("existing_suffix", [".jsonl", ".csv"])
def test_existing_output_is_never_overwritten(tmp_path, existing_suffix):
    path = tmp_path / "readings.jsonl"
    existing = path.with_suffix(existing_suffix)
    existing.write_bytes(b"keep these bytes")
    with pytest.raises(FileExistsError):
        ReadingLog(path)
    assert existing.read_bytes() == b"keep these bytes"
    if existing_suffix == ".csv":
        assert not path.exists()
    else:
        assert not path.with_suffix(".csv").exists()


def test_partial_jsonl_failure_removes_only_failed_append(tmp_path, reading, monkeypatch):
    path = tmp_path / "readings.jsonl"
    record = make_record(reading, 1, "White", "", [])
    with ReadingLog(path) as log:
        log.append(record)
        before = path.read_bytes()
        csv_before = log.csv_path.read_bytes()
        original = logging._write_all

        def fail_jsonl(file, data):
            if file is log._file:
                file.write(data[:11])
                raise OSError("Disk full")
            original(file, data)

        monkeypatch.setattr(logging, "_write_all", fail_jsonl)
        with pytest.raises(OSError, match="Disk full"):
            log.append(make_record(reading, 2, "Gray", "", []))
        assert path.read_bytes() == before
        assert log.csv_path.read_bytes() == csv_before


@pytest.mark.parametrize("interrupted", [False, True])
def test_csv_failure_keeps_jsonl_reading_and_can_export_it(
    tmp_path, reading, monkeypatch, interrupted
):
    path = tmp_path / "readings.jsonl"
    with ReadingLog(path) as log:
        log.append(make_record(reading, 1, "White", "", []))
        csv_before = log.csv_path.read_bytes()
        original = logging._write_all

        def fail_csv(file, data):
            if file is log._csv:
                file.write(data[:19])
                raise KeyboardInterrupt if interrupted else OSError("CSV disk full")
            original(file, data)

        monkeypatch.setattr(logging, "_write_all", fail_csv)
        with pytest.raises(CsvSaveError) as caught:
            log.append(make_record(reading, 2, "Gray", "", []))
        assert caught.value.interrupted == interrupted
        assert len(path.read_text(encoding="utf-8").splitlines()) == 2
        assert log.csv_path.read_bytes() == csv_before
        monkeypatch.setattr(logging, "_write_all", original)
    before = path.read_bytes()
    recovered = tmp_path / "recovered.csv"
    assert export_csv(path, recovered) == 2
    assert len(load_csv(recovered)) == 202
    assert path.read_bytes() == before


def test_recovery_file_is_complete_and_exclusive(tmp_path, reading):
    record = make_record(reading, 1, "White", "", [])
    path = logging.save_recovery(record, tmp_path / "readings.jsonl")
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(logging.encode_record(record))
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        logging.save_recovery(record, tmp_path / "readings.jsonl")
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad_tail", ["{incomplete", "\n", '{"schema_version": 99}\n'])
def test_export_refuses_malformed_record_without_publishing_partial_csv(
    tmp_path, reading, bad_tail
):
    source = tmp_path / "source.jsonl"
    source.write_bytes(
        logging.encode_record(make_record(reading, 1, "White", "", [])) + bad_tail.encode()
    )
    before = source.read_bytes()
    destination = tmp_path / "output.csv"
    with pytest.raises(ValueError, match="line 2"):
        export_csv(source, destination)
    assert source.read_bytes() == before
    assert not destination.exists()


def test_export_refuses_existing_destination(tmp_path, reading):
    source = tmp_path / "source.jsonl"
    source.write_bytes(logging.encode_record(make_record(reading, 1, "White", "", [])))
    destination = tmp_path / "output.csv"
    destination.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        export_csv(source, destination)
    assert destination.read_bytes() == b"keep"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda record: record.update(spectral_values=[0]),
        lambda record: record["spectral_values"].__setitem__(0, float("nan")),
        lambda record: record["wavelengths_nm"].__setitem__(0, True),
        lambda record: record.update(sequence=True),
    ],
)
def test_csv_export_refuses_malformed_scientific_fields(tmp_path, reading, mutate):
    record = json.loads(logging.encode_record(make_record(reading, 1, "White", "", [])))
    mutate(record)
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        export_csv(source, tmp_path / "refused.csv")


def test_sync_failure_rolls_back_the_failed_jsonl_append(tmp_path, reading, monkeypatch):
    path = tmp_path / "readings.jsonl"
    with ReadingLog(path) as log:
        log.append(make_record(reading, 1, "White", "", []))
        before = path.read_bytes()
        original = logging.os.fsync
        failures = [log._file.fileno()]

        def fail_once(descriptor):
            if failures and descriptor == failures[0]:
                failures.pop()
                raise OSError("Sync failure")
            original(descriptor)

        monkeypatch.setattr(logging.os, "fsync", fail_once)
        with pytest.raises(OSError, match="Sync failure"):
            log.append(make_record(reading, 2, "Gray", "", []))
        assert path.read_bytes() == before
        assert len(load_csv(log.csv_path)) == 101


def test_rollback_failure_is_reported_without_hiding_original_error(tmp_path, reading, monkeypatch):
    path = tmp_path / "readings.jsonl"
    with ReadingLog(path) as log:
        log.append(make_record(reading, 1, "White", "", []))
        before = path.read_bytes()
        original = log._file

        class RollbackFailure:
            def __getattr__(self, name):
                return getattr(original, name)

            def truncate(self, size):
                raise OSError("Rollback refused")

        log._file = RollbackFailure()

        def fail_write(file, data):
            file.write(data[:7])
            raise OSError("Original write failure")

        monkeypatch.setattr(logging, "_write_all", fail_write)
        with pytest.raises(OSError, match="Original write failure") as caught:
            log.append(make_record(reading, 2, "Gray", "", []))
        assert path.read_bytes().startswith(before)
        assert any("Rollback refused" in note for note in caught.value.__notes__)


def test_duplicate_json_fields_are_refused(tmp_path, reading):
    record = logging.encode_record(make_record(reading, 1, "White", "", [])).decode()
    source = tmp_path / "source.jsonl"
    source.write_text(
        record.replace('"schema_version": 1', '"schema_version": 99, "schema_version": 1')
    )
    with pytest.raises(ValueError, match="Duplicate JSON field"):
        export_csv(source, tmp_path / "output.csv")
