# Device command checks

Run `uv run python pr_meter.py check --port COM3` before a measurement session.
The support log retains the commands, exact received bytes, parsed replies,
timing and exceptions. Information is queried from the explicitly selected port.
OS port descriptions and USB metadata are logged separately from the model
reported by the instrument.

Sources: Photo Research *PR-655/PR-670 User Manual*, Rev. B, 2009-07-29,
printed pages 102–111 and 114–121, and the
[2019 manufacturer manual](https://github.com/ISET/isetcalibrate/blob/39ff27392f0bd60d7eb044aa5b15d751e6920ff2/PR-655-670-SpectraScan-User-Manual.pdf),
printed pages 113–132. Both editions include the numeric D601 setup layout and
the human-readable D602 example (Rev. B pages 120–121; 2019 page 132). Rev. B's
title page explicitly gives its version date as 07/29/09.

## Connection and query checks

| Command | Information or behavior checked |
| --- | --- |
| `Q`, `PHOTO`, `D111` | Remote-mode entry and PR-655/PR-670 model identification; `Q` also exits on close |
| `I` | Instrument status/error report |
| `D110` | Instrument serial number, retained as text |
| `D114` | Device software version, retained as text |
| `D112` | Number of calibrated accessories and apertures |
| `D116` | Accessory list, read using the accessory count from D112 |
| `D117` | Aperture list, read using the aperture count from D112 |
| `D120` | Hardware configuration, including native spectrum grid and detector information |
| `D601` | Numeric current setup report |
| `D602` | Current setup report with descriptive text |
| `D13` | Gain description and exposure time from the last measurement |
| `D14` | Synchronization mode and frequency report |

All commands except Q and PHOTO include CR. Existing 50 ms character pacing
is retained. Reports use a shared deadline of up to five seconds per query and
the existing 64 KiB response limit. Counted lists must contain every expected
row, even across gaps; an empty serial buffer does not end a list. Zero-count
lists are skipped. Single-line and list reports are checked against documented
field counts. D112 counts must be nonnegative integers. D120 is compared with the
grid this logger supports. D601 values must be finite instrument decimals.

A complete negative status is logged as an unavailable report, and later
queries can continue. For `I`, a negative code is a successfully reported stored
error; it is displayed and logged without clearing it or failing the check.
Complete reports with unfamiliar fields are shown and logged, then other
queries continue. Unknown D112 counts skip the accessory/aperture lists; an
unrecognized D601 skips setup tests. Text bytes outside ASCII are displayed as
`\xNN` escapes and retained exactly in the raw-byte log. Numeric fields remain
strict decimal/scientific ASCII.
A timeout, incomplete list, extra data or failed write stops the check.
It does not reconnect or retry automatically. Failed reports produce a nonzero
exit status, even when model identification succeeded.

## Optional setup command checks

Answer `y` at the setup-test prompt to run these checks. They resend the values
in the current D601 report, require a successful acknowledgement, then request
D601 again and compare every numeric field with the original report.

| Command | Setting | D601 field index, with status at index 0 |
| --- | --- | --- |
| `SN` | Averaging cycles | 10 |
| `SO` | CIE observer | 11 |
| `SS` | Synchronization mode | 13 |
| `SU` | Photometric units | 6 |
| `SD`, PR-670 only | Smart dark | 12 |
| `SF`, PR-670 only | Aperture | 5 |
| `SG`, PR-670 only | Speed/gain mode | 9 |
| `SH`, PR-670 only | Standard/extended sensitivity | 14 |

The test validates all selected values before sending a setup command. If a
command fails or any setting changes, it stops and preserves both reports in
the log. An unexpected change is reported on screen so the operator can check
the meter before measuring. There is no automatic attempt to rewrite the whole
setup after an unexpected response.

The PR-670 aperture command may move the mechanism even when its value remains
unchanged. Press Enter to skip setup tests when only device information is needed.

These tests establish command acceptance and report consistency at current
values. They do not test switching between values, aperture motion, dark-current
performance, sensitivity, exposure accuracy or other optical effects.

## Other commands

`record` exercises B00, M5 and B100 for each operator-confirmed spectrum and
retains measurement data in CSV/JSONL alongside the support log. Zero-padded
backlight acknowledgements are accepted. A complete rejected or unfamiliar B00
reply adds a warning and allows M5; a timeout, extra data or failed write does
not. B100 restoration is best-effort. The manual gives the brightness range as
0 to 100%, including B100. The script uses the meter's current settings.

The connection check does not send M/F measurement commands, toggle echo,
clear instrument errors, change titles or contrast, recall stored readings,
enable instrument data logging, write stored data or issue reset commands.
It does not change exposure time, lenses, add-on accessories or user sync
frequency, and it does not request stored measurement directories or raw
detector arrays. Those commands are not covered by this check. Testing alternate
PR-670 settings and their optical effects requires a controlled physical test.

The software tests use documented example replies and constructed variations,
including both models, command rejection, fragmented aperture lists, incomplete
replies, settings changes and support-file failures. A separate POSIX serial
replay exercises the actual script through pySerial. Physical meter testing
remains pending.
