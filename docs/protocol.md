# Serial protocol and records

`photo_research_cli.driver.PRMeter` owns serial communication. It has no prompts
or file operations. `cli.py` owns operator interaction; `logging.py` owns the
two outputs and offline CSV export.

The CLI creates a matching CSV/JSONL pair automatically in the current folder.
Default filenames contain the session's local date and time. An optional
`--name name` produces `name.jsonl` and `name.csv`. Extensions are added by the
script. The record schema is the same for automatically named and custom files.
CSV export also names its output automatically beside the source; `--name name`
selects `name.csv` instead.

Typing `measure` starts a sequence of guided readings. After each successful
save, the CLI asks for the next sample name directly. At that prompt, `help`
shows instructions and `quit` ends the session. Cancellation or acquisition
failure returns to the command prompt; taking another reading requires typing
`measure` again. Every acquisition still requires Enter at the confirmation
prompt, and the sample number advances only after saving.

With `record --demo`, `demo.py` generates a fixed spectrum on the PR-670 grid
without opening or listing serial ports. The same prompts and save path are used.
Automatic demo filenames start with `demo-`; `--name` still works. Demo records
use `port: "DEMO"`, `spectral_quantity: "synthetic"`, arbitrary demo units,
and a warning identifying the generated data. Meter settings and calibration
are marked as inapplicable. The raw response is empty; the units code and both
integrated header fields are zero placeholders. Real-meter records are unchanged.

## Sources and implemented exchange

The Python port follows the MATLAB PR-655/PR-670 workflow with the attribution
in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Primary protocol reference:
Photo Research, *PR-655/PR-670 User Manual*, Rev. B, 2009-07-29, printed pages
102–111 (remote control), 113 (quantity codes), 116 (spectral response),
118 (model report), and 122 (error codes). The manufacturer provides downloads
on its [PR-655 product page](https://novanta.com/precision-medicine/product/photo-research-pr-655/#tab-documents-downloads-2).

Connection uses 115200 baud, 8 data bits, no parity, one stop bit, no flow control.
POSIX opens request pySerial's exclusive access; the OS handles Windows port
ownership. Port listing does not identify a model; identification occurs only
on the explicitly selected port.

The manual lists 115200 as the default RS-232 baud rate, while USB uses its
driver's communication settings. Public USB examples also work at a nominal
9600 baud. This script retains the MATLAB driver's 115200 setting. For RS-232,
select that rate on the meter and disable PR-650 emulation, which requires a
different startup handshake. See the [protocol review](validation.md) for
the sources compared.

1. Send `Q` without CR, wait 0.5 seconds, clear input.
2. Send `PHOTO` without CR; require `REMOTE MODE`.
3. Send `D111` plus CR; require status zero and `PR-655` or `PR-670`.
4. For a reading, send `B00` plus CR and check its acknowledgement.
5. Send `M5` plus CR; check the five-field header and read the complete native grid.
6. Attempt `B100` plus CR and check its acknowledgement. Close sends `Q` without
   CR when writes remain usable, then releases the host port.

Every command character, including CR when used, is written separately with
50 ms pacing. Each write is bounded by `min(5, timeout)` seconds and its return
count must be exactly one. Failed or interrupted writes forbid further writes
on that connection, including cleanup. There is no automatic write retry.

Reply lines may end in CR, LF, or CRLF and may arrive in fragments. Only exact
command echoes are ignored before the reply. Remote-mode response allows
`min(10, timeout)` seconds; short replies allow `min(5, timeout)`. The complete
M5 header and all spectral rows share one `timeout` deadline beginning after
the paced M5 write. A temporary empty buffer does not mark response completion.
Replies are bounded to 64 KiB by host policy.

The M5 status must be zero; complete standalone negative statuses are instrument
errors. All header and spectral numbers must be finite decimal numbers,
optionally in scientific notation. Python underscore separators are refused.
Each row must contain
exactly a wavelength and value on its model's native grid. Incomplete replies,
wrong grids and surplus data already available after the last row are refused.
An incomplete exchange requires reconnection. Backlight acknowledgement does
not prove the previous exposure finished. The CLI uses a fresh connection for
every operator-requested acquisition.

Cleanup failures after a complete spectrum retain that reading and add warnings.
An interruption during backlight restoration or remote-mode exit likewise keeps
the complete reading; the CLI saves it and stops with status 130. Interruption
before a spectrum is complete publishes no reading and claims no hardware abort.

## JSONL schema version 1

Each line is one ordinary JSON object with `schema_version: 1` and
`record_type: "photo_research_m5_spectrum"`. The record fields are:

| Fields | Meaning |
| --- | --- |
| `record_id`, `software`, `sequence` | UUID, logger name/version, and 1-based saved-reading number in this new file |
| `sample_name`, `notes` | Operator-entered text; notes may be empty |
| `model`, `port` | D111 model and explicitly selected OS port |
| `started_at_utc`, `completed_at_utc`, `duration_seconds` | Host UTC times and monotonic duration from preparation of M5 through complete spectrum validation; excludes connection setup and subsequent cleanup |
| `wavelengths_nm`, `spectral_values` | Native grid and unscaled signed readings |
| `units_code`, `peak_wavelength_nm` | Second and third M5 header fields; peak zero is retained |
| `instrument_integrated_reading`, `integrated_photon_reading` | Fourth and fifth header fields, preserved as reported |
| `raw_m5_response` | Received M5 ASCII bytes, including echo/line endings when supplied, encoded as JSON text; this is not a transcript of setup or cleanup |
| `spectral_quantity`, `spectral_units` | Cautious instrument-reported quantity and unverified units text |
| `acquisition_settings`, `calibration_status` | Explicitly state settings were not queried/changed and calibration was not checked |
| `warnings` | Cleanup failures; empty on an exchange with no reported cleanup problem |

JSON encoding uses finite numbers only, preserves Unicode, and escapes newline
characters inside strings. Quantity code `0` is used by the manual's M5 example
but is not defined by its quantity-code table; no physical unit is assigned to
that code. Other codes are retained without host reinterpretation. No computed
colorimetric or integral quantities are supplied by this version.

CSV is a companion inspection format. Its `wavelength_nm` and `spectral_value`
columns contain one native pair per row. The remaining columns repeat the
sample, connection, timing, units code and header fields for that reading. Use
JSONL for complete retention, including raw response and warnings.

The JSONL append is committed first. A later CSV failure does not remove a
complete JSONL reading. An exclusive file create prevents two logger sessions
from taking the same output paths, and an existing CSV is refused even if the
JSONL filename is new. CSV export validates the record kind, schema version,
model grid, finite scientific values and required CSV fields. It writes a new
destination, never replaces the source, and removes its newly created output
if a record is refused or writing fails.
