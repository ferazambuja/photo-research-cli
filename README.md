# Photo Research spectrum logger

A Python script for taking PR-655/PR-670 readings and saving them as you go.

Every reading is added to two files in the project folder:

- **CSV:** open this in Excel. It contains the spectrum, sample name and notes,
  with one row per wavelength.
- **JSONL:** keeps the complete readings, including the meter's original response.

The script names both files with the session's date and time, such as
`readings-2026-10-02_14-30-00-123456.csv` and the matching `.jsonl` file.
It prints their locations. You don't need to name either file.

## Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then
   reopen your terminal. uv manages Python and the script's dependencies.
2. On this GitHub page, click **Code**, then **Download ZIP**. Extract the folder
   and open a terminal in it.
3. Run:

```sh
uv sync
```

## Connect the meter

Power on the meter, connect its USB cable, and wait for startup. Close any other
program using the meter.

For an RS-232 connection, select **115200 baud** in the meter's Connectivity
settings and turn off PR-650 emulation.

Find its port:

```sh
uv run python pr_meter.py ports
```

On Windows, the port might be `COM3`. On macOS, it might be
`/dev/cu.usbmodem101`. If several ports appear, unplug the meter and run the
command again. Reconnect it; the port that reappears is the one to use.

## Check the connection first

With the meter connected, replace `COM3` with its port:

```sh
uv run python pr_meter.py check --port COM3
```

The check reads the model, serial number, device software version, hardware,
accessories, apertures and current settings. It also requests the last exposure
and synchronization reports. It does not take a measurement.

When asked about setup command tests, answer `y` to test commands using the
current values, or press Enter to skip. On the PR-670, this includes smart dark,
aperture, speed and sensitivity. After each command, the script reads the
settings again to check that they stayed the same.
The aperture command may move the mechanism even when its value stays the same.
Skip setup tests if you only want to read the device information.

Send Fernando the **support log** printed on screen, whether the check works
or fails. Then use `record` below to test a spectrum reading.

## Take readings

Run `check` above before your first reading. Then start the session, replacing
`COM3` with your meter's port:

```sh
uv run python pr_meter.py record --port COM3
```

The script shows the CSV and JSONL file locations. Type `measure`, enter a sample
name and optional notes, then aim and focus on the sample. Press Enter to take
the reading.

```text
Command [measure / help / quit]: measure
Sample name [Enter for Sample 001; help / quit]: White reference
Notes [optional; Enter to skip]: First position
Aim and focus on 'White reference'. Keep the sample and illumination steady.
Press Enter to measure, or type cancel:
Measuring 'White reference'...
Saved reading 1: 'White reference' (PR-670, 201 spectral samples, 380-780 nm).
Reposition the next sample, then enter its name, or type 'quit' to finish.
Sample name [Enter for Sample 002; help / quit]:
```

After each save, position the next sample and enter its name. Press Enter to
use the suggested name, add optional notes, then press Enter to measure.
Each reading is saved automatically to both files. At the sample-name prompt,
type `quit` when finished or `help` for guidance. There is no final save step.

Use your usual exposure, averaging and synchronization settings on the meter.
The script records spectra and the meter's header values; it does not calculate XYZ.

If you'd like to name the files yourself:

```sh
uv run python pr_meter.py record --port COM3 --name my-readings
```

This creates **my-readings.jsonl** and **my-readings.csv**. Just give the name;
the script adds both extensions. If the name is already in use, choose another
or leave out `--name` to use the date and time.

## Send a support log

The script automatically creates a dated `support-...log` file for each run.
It prints the location at the start and end. Send this file to Fernando after
a successful test or if something goes wrong.

The log includes the script and Python versions, operating system, port details,
commands, original device replies, timing, prompts and errors. It also contains
sample names, notes and any reported device serial number. CSV and JSONL remain
your measurement files. The log includes the full working-folder path, which
may contain your computer account name, and USB serial numbers reported by the OS.

If the current folder cannot hold the log, it is saved in a temporary folder
and that location is printed instead. Logs are saved locally; the script does
not upload them.

See [commands checked](docs/commands.md) for the query and setup test coverage.

## If something goes wrong

- **No port appears:** check the power and USB cable. Windows may need the USB
  driver from the [manufacturer's download page](https://novanta.com/precision-medicine/product/photo-research-pr-655/#tab-documents-downloads-2).
- **A reading fails:** check the displayed error and meter settings. Wait for
  the meter to finish, then type `measure` to try again. Earlier readings stay saved.
- **The connection still fails:** close the session, turn the meter off and on,
  wait for startup, then run `ports` and `check` again. This also helps after an
  interrupted command.
- **A reading times out:** the default wait is 300 seconds. Long exposures or
  many averaging cycles may need more time. For example, allow one hour with
  `uv run python pr_meter.py record --port COM3 --timeout 3600`.
- **A backlight warning appears:** the spectrum is saved with the warning in
  JSONL. Check the display manually; its brightness was not confirmed.
- **You press Ctrl-C:** the session ends. Wait for the meter to finish before
  starting another session.
- **A file cannot be saved:** follow the message on screen. The script keeps
  a recovery copy when possible and prints its location.

To recreate a CSV from a saved JSONL file:

```sh
uv run python pr_meter.py export-csv my-readings.jsonl
```

The recreated CSV gets a name with the date and time. Add `--name recovered`
if you'd prefer `recovered.csv`.

The protocol was compared with the MATLAB driver, manufacturer manuals,
Psychtoolbox, PsychoPy and ISET examples. Tests include the script communicating
through pySerial with a local serial emulator. Testing with a physical meter is
still pending. See the [review](docs/validation.md) and
[technical reference](docs/protocol.md) for details.

## Test the prompts without a meter

This optional demo tests the prompts and file saving with generated sample data:

```sh
uv run python pr_meter.py record --demo
```

Type `measure` once, enter a sample name and optional notes, then press Enter to
generate a demo reading. After each save, the script asks for the next sample
name. Press Enter to use the suggested name, or type `quit` to finish. Each
reading uses the same generated spectrum and is saved to both CSV and JSONL.

The files start with `demo-` followed by the date and time. The data is marked
as demo data inside both files. Add `--name my-demo` if you prefer
`my-demo.csv` and `my-demo.jsonl`.

MIT licensed. See [LICENSE](LICENSE) and [source attribution](THIRD_PARTY_NOTICES.md).
