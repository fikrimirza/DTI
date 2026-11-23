"""Plain text outputs.

* single column text (one microvolt value per line) - the input expected by
  the Brainstem Toolbox converter ``bt_txt2avg(file, fs, xmin_ms, xmax_ms)``
* CSV / tab separated table (time + one column per waveform)
* a small ``.info.txt`` sidecar with all metadata and the matching
  ``bt_txt2avg`` call
"""

from __future__ import annotations

from typing import List

from .export import ExportSet


def _num(v: float, digits: int = 6) -> str:
    s = "%.*f" % (digits, v)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def bt_txt2avg_call(es: ExportSet, txt_name: str) -> str:
    # Brainstem Toolbox convention: xmax = xmin + pnts / fs
    fs = es.sample_rate_hz
    xmax = es.xmin_ms + es.n_points * 1000.0 / fs if fs else es.xmax_ms
    return "bt_txt2avg('%s', %s, %s, %s);" % (
        txt_name, _num(fs, 3), _num(es.xmin_ms, 4), _num(xmax, 4))


def write_single_column(path: str, es: ExportSet, channel_index: int = 0) -> None:
    ch = es.channels[channel_index]
    with open(path, "w", newline="\n") as fh:
        for v in ch.values:
            fh.write(_num(v, 6) + "\n")


def write_table(path: str, es: ExportSet, delimiter: str = ",", header: bool = True) -> None:
    with open(path, "w", newline="") as fh:
        if header:
            cols = ["Time(ms)"] + ["%s(uV)" % c.label for c in es.channels]
            fh.write(delimiter.join(cols) + "\r\n")
        for i, t in enumerate(es.times_ms):
            row = [_num(t, 5)] + [_num(c.values[i], 6) for c in es.channels]
            fh.write(delimiter.join(row) + "\r\n")


def info_lines(es: ExportSet) -> List[str]:
    lines = ["%s: %s" % (k, v) for k, v in es.info.items() if v not in (None, "")]
    lines.append("Points: %d" % es.n_points)
    lines.append("FirstSample_ms: %s" % _num(es.xmin_ms, 4))
    lines.append("LastSample_ms: %s" % _num(es.xmax_ms, 4))
    for c in es.channels:
        lines.append("Channel %s: %s, sweeps=%s, rejected=%s" % (
            c.label, c.description, c.averages, c.rejected))
    return lines


def write_info(path: str, es: ExportSet, txt_name: str = "") -> None:
    lines = info_lines(es)
    if txt_name:
        lines.append("")
        lines.append("Brainstem Toolbox (MATLAB):")
        lines.append("  " + bt_txt2avg_call(es, txt_name))
    with open(path, "w", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
