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
2. Download this project and extract the folder. Open a terminal in that folder.
3. Run:

```sh
uv sync
```

## Try the demo

You can try the prompts and file saving without connecting a meter:

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

## Take readings

Start the session, replacing `COM3` with your meter's port:

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
Saved reading 1: 'White reference' (PR-670, 201 spectral samples, 380–780 nm).
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

## If something goes wrong

- **No port appears:** check the power and USB cable. Windows may need the USB
  driver from the [manufacturer's download page](https://novanta.com/precision-medicine/product/photo-research-pr-655/#tab-documents-downloads-2).
- **A reading fails:** check the displayed error and meter settings. Wait for
  the meter to finish, then type `measure` to try again. Earlier readings stay saved.
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

MIT licensed. See [LICENSE](LICENSE) and [source attribution](THIRD_PARTY_NOTICES.md).
