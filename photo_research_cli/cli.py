"""Human instructions go to stderr. Unsaved recovery JSON goes to stdout."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

from . import __version__
from .demo import make_demo_record
from .driver import PRError, PRMeter, validate_connection
from .logging import CsvSaveError, ReadingLog, export_csv, make_record, save_recovery


def _say(message: str):
    print(message, file=sys.stderr, flush=True)


def _ask(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    return input().strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uv run python pr_meter.py",
        description="Take PR-655/PR-670 readings and save them to CSV and JSONL.",
        epilog="Try it without a meter: uv run python pr_meter.py record --demo. "
        "Use 'uv run python pr_meter.py ports' to find the meter's port.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "ports",
        help="Find the meter's serial port",
        description="List serial ports. Unplug and reconnect the meter "
        "to see which port reappears.",
    )
    record = commands.add_parser(
        "record",
        help="Take readings and save them automatically to CSV and JSONL",
        description="Type measure to begin, enter each sample name, and follow the prompts. "
        "The script creates both output files for you.",
        epilog="With a meter: uv run python pr_meter.py record --port COM3. "
        "Without a meter: uv run python pr_meter.py record --demo.",
    )
    source = record.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--port", help="Meter port shown by the ports command, e.g. COM3"
    )
    source.add_argument(
        "--demo", action="store_true", help="Try the prompts and file saves without a meter"
    )
    record.add_argument(
        "--name",
        help="Optional name for both files, e.g. white-reference. "
        "Otherwise a date and time is used. Extensions are added automatically",
    )
    record.add_argument(
        "--timeout",
        type=float,
        default=300,
        metavar="SECONDS",
        help="Maximum wait for the complete M5 spectrum (default: 300 seconds)",
    )
    export = commands.add_parser(
        "export-csv",
        help="Create a CSV from a saved JSONL file",
    )
    export.add_argument("input", type=Path, help="Saved .jsonl log containing complete readings")
    export.add_argument("--name", help="Optional name for the recreated CSV, without .csv")
    return parser


def _file_path(name: str | None, extension: str, prefix: str = "readings") -> Path:
    base = name.strip() if name is not None else f"{prefix}-{datetime.now():%Y-%m-%d_%H-%M-%S-%f}"
    if not base or base in (".", "..") or "/" in base or "\\" in base:
        raise ValueError("Use a file name like --name white-reference.")
    if base.lower().endswith((".jsonl", ".csv")):
        raise ValueError("Leave off the extension: use --name white-reference.")
    return Path(f"{base}{extension}")


def _ports() -> int:
    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        _say("No serial ports found. Power on the meter, connect USB, and wait for startup.")
        _say("Check cable and the USB driver, then run 'uv run python pr_meter.py ports' again.")
        return 0
    _say("Available serial ports:")
    for port in ports:
        _say(f"  {port.device}  {port.description}")
    _say("To find the meter's port, unplug it, run this command again, then reconnect it.")
    _say("Use the port that reappears:")
    _say("uv run python pr_meter.py record --port YOUR_PORT")
    return 0


def _help(demo: bool = False):
    if demo:
        _say("measure  Enter a sample name and notes, then press Enter for a demo reading.")
    else:
        _say(
            "measure  Enter a sample name and notes, position the sample, "
            "then press Enter to measure."
        )
    _say("help     Show these instructions.")
    _say("quit     End the session. Every successful reading is already saved.")
    _say("After each save, enter the next sample name. Type 'help' or 'quit' at that prompt.")
    if demo:
        _say("Demo: each reading uses the same generated spectrum. No meter is needed.")
        _say("Ctrl-C ends the session.")
    else:
        _say("Before measuring: aim and focus; keep illumination and sample position steady.")
        _say("Use your usual exposure, averaging and synchronization settings on the meter.")
        _say("Ctrl-C ends the session. Wait for the meter to finish before starting again.")


def _recover(record: dict, path: Path, error: BaseException):
    _say(f"Could not save this reading to {path}: {error}")
    for note in getattr(error, "__notes__", ()):
        _say(note)
    try:
        recovery = save_recovery(record, path)
        _say(f"The complete unsaved reading was saved separately: {recovery}")
    except OSError as recovery_error:
        _say(f"The separate recovery file could not be saved: {recovery_error}")
        _say("The complete unsaved reading is printed as JSON. Copy it to a new .json file.")
    # ASCII escapes preserve Unicode notes even on a redirected legacy console.
    # A broken stdout must not prevent the separate recovery save above.
    try:
        print(json.dumps(record, ensure_ascii=True, allow_nan=False), flush=True)
    except OSError as stdout_error:
        _say(f"Could not print recovery JSON to stdout: {stdout_error}")
        _say(json.dumps(record, ensure_ascii=True, allow_nan=False))
    _say("Session ended. Keep the recovery copy with your readings.")


def _session(args: argparse.Namespace) -> int:
    if not args.demo:
        validate_connection(args.port, args.timeout)
    output = _file_path(args.name, ".jsonl", "demo" if args.demo else "readings")
    saved = 0
    failed = False
    taking_readings = False
    # Reserve storage before issuing any serial command. A second process cannot
    # share this log because the exclusive creation refuses its existing path.
    with ReadingLog(output) as log:
        _say(f"Photo Research spectrum logger {__version__}")
        _say("by Fernando Voltolini de Azambuja")
        if args.demo:
            _say("DEMO: generated sample data. No meter is needed or connected.")
        else:
            _say(f"Selected port: {args.port}")
        _say("Each reading will be saved automatically to both files:")
        _say(f"  CSV (open in Excel): {log.csv_path}")
        _say(f"  JSONL (complete readings): {log.path}")
        if not args.demo:
            _say("\nPower on the meter, wait for startup, and close other programs using it.")
            _say("Use your usual meter settings. Aim and focus before each reading.")
        _say("\nType 'measure' for a reading, 'help' for guidance, or 'quit' to finish.")
        try:
            while True:
                if not taking_readings:
                    command = _ask("\nCommand [measure / help / quit]: ").lower()
                    if command == "quit":
                        break
                    if command == "help":
                        _help(args.demo)
                        continue
                    if command != "measure":
                        _say("Enter 'measure', 'help', or 'quit'.")
                        continue
                    taking_readings = True
                default_name = f"Sample {saved + 1:03d}"
                name = _ask(f"Sample name [Enter for {default_name}; help / quit]: ")
                if name.lower() == "quit":
                    break
                if name.lower() == "help":
                    _help(args.demo)
                    continue
                name = name or default_name
                notes = _ask("Notes [optional; Enter to skip]: ")
                if args.demo:
                    _say(f"Demo will generate a sample spectrum for '{name}'.")
                else:
                    _say(f"Aim and focus on '{name}'. Keep the sample and illumination steady.")
                if _ask("Press Enter to measure, or type cancel: "):
                    _say("Cancelled. Type 'measure' when you're ready.")
                    taking_readings = False
                    continue
                if args.demo:
                    _say(f"Generating demo reading for '{name}'...")
                else:
                    _say(f"Measuring '{name}'...")
                meter = None
                try:
                    if args.demo:
                        record = make_demo_record(saved + 1, name, notes)
                    else:
                        with PRMeter(args.port, args.timeout) as meter:
                            reading = meter.measure()
                        record = make_record(reading, saved + 1, name, notes, meter.warnings)
                except (PRError, serial.SerialException, OSError) as error:
                    failed = True
                    _say(f"Reading failed: {error}")
                    _say("Earlier readings stay saved.")
                    _say(
                        "Check power, cable, selected port and meter settings; "
                        "close other serial programs."
                    )
                    if meter is not None:
                        for warning in meter.warnings:
                            _say(f"Warning: {warning}")
                    _say("Wait for the meter to finish before typing 'measure' to try again.")
                    taking_readings = False
                    continue
                csv_failure = None
                try:
                    log.append(record)
                except CsvSaveError as error:
                    csv_failure = error
                except (OSError, KeyboardInterrupt) as error:
                    _recover(record, log.path, error)
                    return 130 if isinstance(error, KeyboardInterrupt) else 2
                saved += 1
                label = "demo reading" if args.demo else "reading"
                _say(
                    f"Saved {label} {saved}: '{name}' ({record['model']}, "
                    f"{len(record['wavelengths_nm'])} spectral samples, 380–780 nm)."
                )
                if csv_failure is not None:
                    _say(f"The reading is saved in JSONL, but the CSV update failed: {csv_failure}")
                    for note in getattr(csv_failure, "__notes__", ()):
                        _say(note)
                    _say("To recreate the CSV from your saved readings, run:")
                    _say(
                        f'uv run python pr_meter.py export-csv "{log.path}" '
                        f'--name "{log.path.stem}-recovered"'
                    )
                    return 130 if csv_failure.interrupted else 2
                if meter is not None:
                    for warning in meter.warnings:
                        _say(f"Warning: {warning}")
                if meter is not None and meter.interrupted:
                    _say("Interrupted during connection cleanup; the completed reading was saved.")
                    return 130
                if args.demo:
                    _say("Enter the next sample name, or type 'quit' to finish.")
                else:
                    _say(
                        "Reposition the next sample, then enter its name, or type 'quit' to finish."
                    )
        except EOFError:
            _say("\nInput ended.")
        except KeyboardInterrupt:
            _say("\nSession interrupted.")
            if not args.demo:
                _say("Wait for the meter to finish before starting again.")
            _say(f"{saved} earlier complete reading(s) remain saved to: {log.path}")
            return 130
        _say(f"\nSession ended. {saved} complete reading(s) saved to: {log.path}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "ports":
            return _ports()
        if args.command == "export-csv":
            output = args.input.expanduser().resolve().parent / _file_path(
                args.name, ".csv", f"{args.input.stem}-recovered"
            )
            count = export_csv(args.input, output)
            _say(f"Exported {count} complete reading(s) to: {output}")
            return 0
        return _session(args)
    except FileExistsError as error:
        _say(f"{error.filename or 'The output file'} already exists.")
        if args.command == "record":
            _say("Use a different --name, or leave it out for automatic filenames.")
        else:
            _say("Use a different --name for the CSV, or leave it out for automatic naming.")
        return 1
    except (ValueError, OSError, serial.SerialException) as error:
        _say(f"Cannot start: {error}")
        if getattr(args, "demo", False):
            _say("Check the output folder, then run 'uv run python pr_meter.py record --help'.")
        else:
            _say(
                "Check the port, timeout and output folder, "
                "then run 'uv run python pr_meter.py record --help'."
            )
        return 1
    except KeyboardInterrupt:
        _say("Interrupted.")
        if not getattr(args, "demo", False):
            _say("Wait for the meter to finish before starting again.")
        return 130
