# Protocol checks

The Python script was compared with the existing MATLAB PR driver and public
PR-655/PR-670 examples. The acquisition commands and native spectrum format
follow the manufacturer manuals. Software tests cover malformed numbers,
zero-padded backlight replies and unfamiliar diagnostic reports. Physical
testing remains pending.

## Sources checked

| Source | Parts used in the comparison |
| --- | --- |
| Photo Research, *PR-655/PR-670 User Manual*, Rev. B, 2009-07-29 | Printed pages 95-96: RS-232 and default baud rate; 102-104: single-character commands, remote mode, backlight, measurement and exit; 113-118: units, spectrum and model report; 122: error codes |
| [Manufacturer manual, 2019 edition, public copy in ISET](https://github.com/ISET/isetcalibrate/blob/39ff27392f0bd60d7eb044aa5b15d751e6920ff2/PR-655-670-SpectraScan-User-Manual.pdf) | Printed page 44: native wavelength grids; 107-108: serial settings; 113-116: commands; 124-129: response fields; 133-134: errors |
| MATLAB PR-655/PR-670 driver, credited in [source attribution](../THIRD_PARTY_NOTICES.md) | Startup exchange, model check, native grids, M5 header fields, command pacing, timeouts and backlight lifecycle |
| [Psychtoolbox PR-670 routines](https://github.com/Psychtoolbox-3/Psychtoolbox-3/tree/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/PsychHardware/PR670Toolbox) and [PR-655 routines](https://github.com/Psychtoolbox-3/Psychtoolbox-3/tree/8f952b4cae7ee3fd90a792b1b36bfb3030ed701d/Psychtoolbox/PsychHardware/PR655Toolbox) | Q/PHOTO startup, 50 ms character pacing, M5 command, native sample counts and application-specific spectrum scaling |
| [PsychoPy PhotoResearch driver](https://github.com/psychopy/psychopy-photoresearch/blob/cda3b36381da0d3899ccbf3851a9770f65806f01/psychopy_photoresearch/pr.py) | PR-655/PR-670 support, PHOTO, D111, individual character writes and unscaled spectrum parsing |
| [ISET PR-670 examples](https://github.com/ISET/isetcalibrate/tree/39ff27392f0bd60d7eb044aa5b15d751e6920ff2/devices/pr670) | Modern MATLAB serialport use and 50 ms character pacing, especially `icalPR670Init`, `icalPR670write` and `icalPR670CMD` |

## Findings

- **Startup follows the PR-670 Psychtoolbox exchange.** This script sends Q
  and PHOTO without CR, and D111, B00, M5 and B100 with CR. Other implementations
  use CR for Q/PHOTO, or different line endings; the no-CR form is not universal.
  Commands are sent one character at a time. The PR-670 Psychtoolbox startup
  allows 0.5 seconds after Q; its writer uses 50 ms between characters.
- **Backlight control follows the documented 0–100% range.** Zero-padded
  acknowledgement text is accepted. Complete rejected or unfamiliar B00 replies
  add a warning while allowing a spectrum; incomplete replies still stop it.
  Actual reply wording and display behavior need a meter test.
- **Diagnostics retain unfamiliar firmware replies.** Complete unexpected
  reports are logged and later queries continue. Incomplete lists and failed
  exchanges still require reconnection. A stored error returned by I is reported
  without clearing it. Non-ASCII text bytes are escaped; numeric parsing remains
  strict. Both manual editions contain the D601/D602 setup examples.
- **Native grids agree.** PR-655 returns 101 samples from 380 through 780 nm,
  spaced 4 nm apart. PR-670 returns 201 samples at 2 nm spacing. The script
  checks every wavelength and waits for the complete grid across packet gaps.
- **The M5 header agrees.** Its five fields are status, units code, peak
  wavelength, integrated radiometric value and integrated photon value.
  The manual's zero peak wavelength is valid and is retained. Scientific
  notation, signed values and the original response are preserved.
- **Different nominal USB baud rates are not a protocol contradiction.**
  MATLAB uses 115200; PsychoPy, Psychtoolbox and ISET use 9600 in their USB
  examples. The manual says the USB driver sets the communication parameters.
  RS-232 has a selectable rate and defaults to 115200. This script uses 115200;
  an RS-232 meter must use that setting. PR-650 emulation needs a different
  handshake and is outside this script's supported setup.
- **Application scaling is kept separate from logging.** Psychtoolbox
  multiplies PR-655 values by 4 and PR-670 values by 2 before resampling to its
  own spectrum convention. The MATLAB driver and PsychoPy retain unscaled
  values. This script also retains the instrument values and does not infer
  physical units or calculate XYZ. The manuals use units code 0 in examples
  without defining it in their units table.
- **Malformed numbers are now rejected.** Python's `float()` accepted serial
  tokens such as `3_80` and `-0.1_25`. These are Python numeric syntax, not
  instrument decimal responses. The parser now checks decimal/scientific
  syntax before conversion. Seven regression cases cover the status, units,
  peak, both integrated fields, wavelength and spectral value. They failed
  before the fix and pass afterwards.

The manual's spectrum example contains a truncated `380,1.627e-` line. That is
an incomplete example, so it was not treated as a valid complete reading.
The serial replay uses the documented header and constructed complete spectra.

## Software verification

The tests include:

- Both native grids with CR, LF and CRLF, command echoes and fragmented replies.
- Complete-spectrum deadlines, unsupported models, invalid rows and unknown
  instrument error codes, without automatic acquisition retries.
- Incomplete writes and interruptions, preservation of completed readings
  after cleanup failure, and JSONL/CSV saving and recovery.
- Repeated guided readings, cancellation, optional filenames and offline CSV
  export.
- Subprocess runs of the actual script through pySerial and a POSIX
  pseudo-terminal, covering recording and device checks for both models.
  The separate emulator checks commands, echoes, documented headers and
  backlight wording, and constructed spectra fragmented with 120 ms gaps.
  Recording runs take two readings on separate connections and verify both
  measurement files. Device checks include setup commands and fragmented
  aperture reports. Both modes verify support logs. Each subprocess can open
  only the test's virtual terminal.
- Connection failure, command rejection, partial replies, incorrect reported
  grids, unexpected settings changes and support-log write failure while
  saving a complete reading.
- Unexpected diagnostic formats, commas in text, non-ASCII text bytes,
  zero-padded and rejected backlight replies, and serial disconnection during
  spectrum reads. Direct-script tests use an ASCII console encoding. Serial
  opening options are checked for both POSIX and Windows.

Software check on macOS, version 0.2.1: **159 tests passed; Ruff passed**.

```sh
uv run --locked pytest -q
uv run --locked ruff check .
```

The local serial replay is skipped on Windows, where POSIX pseudo-terminals
are unavailable. It verifies host communication and saving with a simulator.
Actual firmware replies, USB drivers, instrument timing and optical accuracy
still need a physical PR-655/PR-670 test.

GitHub Actions runs the software tests and Ruff on Windows with Python 3.11.
That checks Windows host behavior without a meter; USB-driver installation,
COM-port discovery and actual console use still need a test on the user's PC.

The first hardware check should retain a support log of remote-mode entry,
echoes, identity, setup reports and B00/B100 replies. Check long-exposure and
averaging settings with a suitable `--timeout`. Current-value setup tests cannot
prove that an aperture does not move. An empty M5 units field is still refused,
and reopening the port may affect the device's control lines. After an
interrupted command, power-cycle before retrying if remote-mode entry fails.

The script creates support logs and includes a `check` command. The documented
queries and optional tests of current setup values, including the PR-670-only
SD/SF/SG/SH commands, are listed in [command coverage](commands.md).
