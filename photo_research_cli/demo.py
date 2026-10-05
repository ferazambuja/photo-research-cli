"""Generate a synthetic spectrum for trying the CLI without a meter."""

import math
from datetime import datetime, timezone

from .driver import Reading
from .logging import make_record


def make_demo_record(sequence: int, sample: str, notes: str) -> dict:
    wavelengths = tuple(range(380, 781, 2))
    values = tuple(round(math.exp(-0.5 * ((w - 550) / 40) ** 2), 6) for w in wavelengths)
    timestamp = datetime.now(timezone.utc).isoformat()
    reading = Reading(
        model="PR-670",
        port="DEMO",
        started_at_utc=timestamp,
        completed_at_utc=timestamp,
        duration_seconds=0.0,
        wavelengths_nm=wavelengths,
        spectral_values=values,
        units_code=0.0,
        peak_wavelength_nm=550.0,
        instrument_integrated_reading=0.0,
        integrated_photon_reading=0.0,
        raw_m5_response="",
    )
    record = make_record(
        reading, sequence, sample, notes, ["Synthetic demo data; no meter was connected."]
    )
    record.update(
        spectral_quantity="synthetic",
        spectral_units="arbitrary demo units",
        acquisition_settings="demo; no meter settings",
        calibration_status="not_applicable",
    )
    return record
