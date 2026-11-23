"""ASCII output in the style of Bio-logic AEP2ASC 1.6.0.

The options and field captions are the ones of AEP2ASC (registry keys
``Software\\Bio-logic Systems Corp\\AEPTools``): patient / record /
stimulus / amplifier / marked point latency / marked point amplitude /
wave information, tab or comma separated, optional quotes and header line,
waveforms in columns or rows, append to an existing file.

The original program's exact line layout is not documented; this
re-implementation writes, per record, one header line + one value line with
all selected information fields, followed by the waveform block.
"""

from __future__ import annotations

import datetime as _dt
import io
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, TextIO

from .biologic import Record


@dataclass
class AsciiOptions:
    patient_info: bool = True
    record_info: bool = True
    stimulus_info: bool = True
    amplifier_info: bool = True
    mp_latency: bool = True
    mp_amplitude: bool = True
    wave_info: bool = True
    tab_delimited: bool = True      # False -> comma
    columns: bool = True            # waveforms in columns (False -> rows)
    quotes: bool = False
    header: bool = True
    insert_delay_correction: bool = True
    timebase: str = "navigator"
    anonymize: bool = False


def vb_format(value: Optional[float], min_dec: int = 1, max_dec: int = 4) -> str:
    """Emulate VB Format(x, "######0.0###")."""
    if value is None:
        return ""
    s = "%.*f" % (max_dec, value)
    whole, _, dec = s.partition(".")
    dec = dec.rstrip("0")
    if len(dec) < min_dec:
        dec = dec + "0" * (min_dec - len(dec))
    out = whole + ("." + dec if dec else "")
    return "0.0" if out in ("-0.0",) else out


def _date(v) -> str:
    if isinstance(v, _dt.datetime):
        if v.hour == v.minute == v.second == 0:
            return v.strftime("%Y-%m-%d")
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return "" if v is None else str(v)


def _fields(rec: Record, opt: AsciiOptions):
    names: List[str] = []
    values: List[str] = []

    def add(n, v):
        names.append(n)
        values.append("" if v is None else str(v))

    if opt.patient_info:
        p = rec.patient
        if opt.anonymize:
            add("Patient ID", "")
        else:
            add("Patient ID", p.patient_id if p else "")
            add("Last Name", p.last_name if p else "")
            add("First Name", p.first_name if p else "")
            add("Birth Date", _date(p.birthdate) if p else "")
            add("Test Date", _date(rec.test.test_date) if rec.test else "")
    if opt.record_info:
        add("Test Type", rec.test_type_name)
        add("Record", rec.index)
        add("Start Time", "" if opt.anonymize else _date(rec.start_time))
        add("Channels", rec.n_channels)
        add("Epoch (ms)", vb_format(rec.epoch_ms, 1, 2))
        add("Points", rec.n_points)
        add("Pre/Post Time(ms)", vb_format(rec.prestim_ms, 1, 2))
        add("Blocked Time(ms)", vb_format(rec.blocked_ms, 1, 2))
        add("Comments", rec.comments)
    if opt.stimulus_info:
        add("Ear", rec.ear)
        add("Transducer", rec.transducer)
        add("Stimulus", rec.stimulus)
        add("Polarity", rec.polarity)
        add("Intensity", rec.intensity)
        add("Rate", rec.rate)
        add("Masking(Contra)", rec.masking("contra"))
        add("Masking(Ipsi)", rec.masking("ipsi"))
    if opt.amplifier_info:
        for w in rec.waveforms:
            amp = rec.amplifiers.get(w.channel, {})
            pre = "Chan %d Bank %d " % (w.channel, w.bank)
            add(pre + "Averages", w.averages)
            add(pre + "Rejected", w.rejected)
            add(pre + "Gain", amp.get("AmplifierGain"))
            add(pre + "Low Filter", vb_format(amp.get("LowFilter"), 0, 2))
            add(pre + "High Filter", amp.get("HighFilter"))
            add(pre + "Notch Filter", "On" if amp.get("NotchFilter") else "Off")
            add(pre + "Comment", w.comment)
    if opt.mp_latency or opt.mp_amplitude:
        for m in sorted(rec.marked_points, key=lambda m: (m.channel, m.bank, m.label_number)):
            pre = "Chan %d Bank %d %s " % (m.channel, m.bank, m.label)
            if opt.mp_latency:
                add(pre + "Latency(ms)", vb_format(m.latency_ms))
            if opt.mp_amplitude:
                add(pre + "Amplitude(uV)", vb_format(m.amplitude_uv))
    return names, values


def write_records(fh: TextIO, records: Sequence[Record], opt: AsciiOptions) -> int:
    d = "\t" if opt.tab_delimited else ","

    def line(cells: Iterable[str]):
        cells = list(cells)
        if opt.quotes:
            cells = ['"%s"' % str(c).replace('"', "'") for c in cells]
        fh.write(d.join(cells) + "\r\n")

    count = 0
    for rec in records:
        names, values = _fields(rec, opt)
        if names:
            if opt.header:
                line(names)
            line(values)
        if opt.wave_info and rec.waveforms:
            times = rec.times_ms(opt.insert_delay_correction, opt.timebase)
            waves = [(w, w.uv) for w in rec.waveforms]
            labels = ["Chan %d Bank %d Amplitude(uV)" % (w.channel, w.bank) for w, _ in waves]
            if opt.columns:
                if opt.header:
                    line(["Latency(ms)"] + labels)
                for i, t in enumerate(times):
                    line([vb_format(t)] + [vb_format(v[i]) if i < len(v) else "" for _, v in waves])
            else:
                line(["Latency(ms)"] + [vb_format(t) for t in times])
                for lab, (_, v) in zip(labels, waves):
                    line([lab] + [vb_format(x) for x in v])
        fh.write("\r\n")
        count += 1
    return count


def write_ascii(path: str, records: Sequence[Record], opt: AsciiOptions,
                append: bool = False) -> int:
    """Write *records* to *path*; AEP2ASC appended to existing files."""
    with open(path, "a" if append else "w", newline="", encoding="cp1252",
              errors="replace") as fh:
        return write_records(fh, records, opt)


def to_string(records: Sequence[Record], opt: AsciiOptions) -> str:
    buf = io.StringIO()
    write_records(buf, records, opt)
    return buf.getvalue()
