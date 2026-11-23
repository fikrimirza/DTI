"""Turn Bio-logic records into format-neutral export sets.

An :class:`ExportSet` is a list of waveforms (channels, in microvolts) that
share one time axis, plus descriptive metadata.  All writers
(Neuroscan .avg, text, CSV) consume export sets, so single records and
combined (added / subtracted) records are written the same way.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from .biologic import Record

BASELINE_MODES = ("none", "prestim", "mean")
COMBINE_MODES = ("add", "subtract")


@dataclass
class Channel:
    label: str
    values: List[float]
    averages: Optional[int] = None
    rejected: Optional[int] = None
    description: str = ""


@dataclass
class ExportSet:
    name: str
    times_ms: List[float]
    channels: List[Channel]
    sample_rate_hz: float
    info: Dict[str, str] = field(default_factory=dict)
    patient_id: str = ""
    test_id: str = ""
    technician: str = ""
    date: Optional[_dt.datetime] = None
    low_cut_hz: float = 0.0
    high_cut_hz: float = 0.0

    @property
    def n_points(self) -> int:
        return len(self.times_ms)

    @property
    def xmin_ms(self) -> float:
        return self.times_ms[0] if self.times_ms else 0.0

    @property
    def xmax_ms(self) -> float:
        return self.times_ms[-1] if self.times_ms else 0.0

    def channel(self, label: str) -> Channel:
        for c in self.channels:
            if c.label == label:
                return c
        raise KeyError(label)


def safe_filename(text: str, maxlen: int = 120) -> str:
    text = re.sub(r"[^\w.\-]+", "_", text, flags=re.UNICODE).strip("._")
    return (text or "record")[:maxlen]


def apply_baseline(values: Sequence[float], times: Sequence[float], mode: str) -> List[float]:
    if mode == "none" or not values:
        return list(values)
    if mode == "prestim":
        pre = [v for v, t in zip(values, times) if t < 0]
        if not pre:  # no pre-stimulus period: fall back to the whole sweep
            pre = list(values)
        ref = sum(pre) / len(pre)
    elif mode == "mean":
        ref = sum(values) / len(values)
    else:
        raise ValueError("baseline must be one of %s" % ", ".join(BASELINE_MODES))
    return [v - ref for v in values]


def record_basename(rec: Record, anonymize: bool = False, number: Optional[int] = None) -> str:
    if anonymize:
        pid = "rec%04d" % (number if number is not None else rec.index)
        tid = ""
    else:
        pid = rec.patient.patient_id if rec.patient and rec.patient.patient_id else "unknown"
        tid = rec.test_id or ""
    parts = [pid, tid, "R%03d" % rec.index, rec.short_name()]
    return safe_filename("_".join(p for p in parts if p))


def _record_info(rec: Record, anonymize: bool) -> Dict[str, str]:
    amp = rec.amplifiers.get(1) or next(iter(rec.amplifiers.values()), {})
    info = {
        "Source": "Bio-logic Navigator Pro AEP (EPWinData.mdb)",
        "RecordID": rec.record_id or "",
        "TestType": rec.test_type_name,
        "Record": str(rec.index),
        "Stimulus": rec.stimulus,
        "StimulusFile": rec.custom_stim_file,
        "Ear": rec.ear,
        "EarCode": str(rec.stim_value("StimEar", "")),
        "Transducer": rec.transducer,
        "Polarity": rec.polarity,
        "Intensity": rec.intensity,
        "Rate": rec.rate,
        "InsertDelay_ms": "%g" % rec.insert_delay_ms,
        "Epoch_ms": "%g" % rec.epoch_ms,
        "Points": str(rec.n_points),
        "PreStim_ms": "%.4f" % rec.prestim_ms,
        "SampleRate_Hz": "%.3f" % rec.sample_rate_hz,
        "LowFilter_Hz": "%g" % (amp.get("LowFilter") or 0),
        "HighFilter_Hz": "%g" % (amp.get("HighFilter") or 0),
        "Gain": str(amp.get("AmplifierGain") or ""),
        "SoftwareVersion": rec.software_version,
    }
    if not anonymize:
        info["StartTime"] = str(rec.start_time or "")
        info["TestID"] = rec.test_id or ""
        if rec.patient:
            info["PatientID"] = rec.patient.patient_id
    return info


def record_to_export(rec: Record,
                     banks: Optional[Iterable[int]] = None,
                     channels: Optional[Iterable[int]] = None,
                     insert_delay_correction: bool = True,
                     timebase: str = "navigator",
                     baseline: str = "none",
                     anonymize: bool = False,
                     number: Optional[int] = None) -> ExportSet:
    """Convert one record to an export set (one channel per channel/bank)."""
    times = rec.times_ms(insert_delay_correction, timebase)
    bank_sel = set(banks) if banks else None
    ch_sel = set(channels) if channels else None
    chans: List[Channel] = []
    for w in rec.waveforms:
        if bank_sel is not None and w.bank not in bank_sel:
            continue
        if ch_sel is not None and w.channel not in ch_sel:
            continue
        vals = apply_baseline(w.uv, times, baseline)
        chans.append(Channel(label=w.label, values=vals, averages=w.averages,
                             rejected=w.rejected,
                             description="Channel %d bank %d %s" % (w.channel, w.bank, w.bank_name)))
    if not chans:
        raise ValueError("record %s has no waveform for the selected bank/channel "
                         "(available banks: %s)" % (rec.record_id, rec.banks))
    amp = rec.amplifiers.get(1) or next(iter(rec.amplifiers.values()), {})
    fs = rec.hardware_sample_rate_hz if timebase == "hardware" else rec.sample_rate_hz
    info = _record_info(rec, anonymize)
    info["InsertDelayCorrected"] = "yes" if insert_delay_correction else "no"
    info["Baseline"] = baseline
    info["Timebase"] = timebase
    return ExportSet(
        name=record_basename(rec, anonymize, number),
        times_ms=times[:min(len(c.values) for c in chans)],
        channels=chans,
        sample_rate_hz=fs,
        info=info,
        patient_id="" if anonymize or not rec.patient else rec.patient.patient_id,
        test_id="" if anonymize else (rec.test_id or ""),
        technician="" if anonymize or not rec.test else rec.test.technician,
        date=None if anonymize or not isinstance(rec.start_time, _dt.datetime) else rec.start_time,
        low_cut_hz=float(amp.get("LowFilter") or 0.0),
        high_cut_hz=float(amp.get("HighFilter") or 0.0),
    )


def combine_records(records: Sequence[Record], mode: str = "add",
                    bank: Optional[int] = None, channel: int = 1,
                    insert_delay_correction: bool = True,
                    timebase: str = "navigator", baseline: str = "none",
                    anonymize: bool = False, name: Optional[str] = None) -> ExportSet:
    """Combine waveforms of several records.

    ``add``      weighted average  sum(n_i * x_i) / sum(n_i)  (n = sweeps);
                 with two opposite-polarity records this is the "added"
                 (envelope / F0) cABR response.
    ``subtract`` (x_1 - x_2) / 2 of exactly two records; with opposite
                 polarities this is the "subtracted" (temporal fine
                 structure) response.
    """
    if mode not in COMBINE_MODES:
        raise ValueError("mode must be add or subtract")
    if not records:
        raise ValueError("no records to combine")
    if mode == "subtract" and len(records) != 2:
        raise ValueError("subtract needs exactly two records")
    ref = records[0]
    waves = []
    for r in records:
        if (r.n_points, round(r.epoch_ms, 3), r.prepost_points) != (
                ref.n_points, round(ref.epoch_ms, 3), ref.prepost_points):
            raise ValueError("records have different points/epoch/pre-stimulus; "
                             "cannot combine %s and %s" % (ref.record_id, r.record_id))
        b = bank if bank is not None else r.banks[0]
        w = r.waveform(channel, b)
        if w is None:
            raise ValueError("record %s has no channel %d bank %d (banks %s)"
                             % (r.record_id, channel, b, r.banks))
        waves.append(w)
    times = ref.times_ms(insert_delay_correction, timebase)
    n = min(len(w.ad) for w in waves)
    data = [w.uv for w in waves]
    if mode == "add":
        weights = [float(w.averages or 1) for w in waves]
        total = sum(weights)
        vals = [sum(wt * d[i] for wt, d in zip(weights, data)) / total for i in range(n)]
    else:
        vals = [(data[0][i] - data[1][i]) / 2.0 for i in range(n)]
    vals = apply_baseline(vals, times[:n], baseline)
    sweeps = sum(int(w.averages or 0) for w in waves) or None
    label = ("ADD" if mode == "add" else "SUB")
    es = record_to_export(ref, banks=[waves[0].bank], channels=[channel],
                          insert_delay_correction=insert_delay_correction,
                          timebase=timebase, baseline="none", anonymize=anonymize)
    es.channels = [Channel(label=label, values=vals, averages=sweeps,
                           description="%s of %d records" % (mode, len(records)))]
    es.times_ms = times[:n]
    es.info["Combined"] = "%s of records %s" % (
        mode, ", ".join("%s" % r.index for r in records))
    es.info["Polarities"] = ", ".join(r.polarity or "?" for r in records)
    es.info["Baseline"] = baseline
    es.name = name or safe_filename(es.name + "_" + label)
    return es
