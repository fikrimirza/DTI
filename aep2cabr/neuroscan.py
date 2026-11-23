"""Neuroscan ``.avg`` writer / reader.

``.avg`` is the input format of the Brainstem Toolbox (Skoe & Kraus,
Northwestern University) and of the IHS cABR stand-alone tools that are
derived from it (IHSPITCH.exe / IHS_Phaseogram.exe: "Stimulus file must be
in '.avg' format").

Layout (little endian)::

    900 bytes   SETUP header
    75 bytes    ELECTLOC per channel
    per channel 5 byte sweep header + pnts * float32  (signal, microvolts)
    per channel pnts * float32                       (variance)

Scaling is written so that every common reader gets microvolts back
unchanged: calib = 1, sensitivity = 204.8, baseline = 0, n = 1, i.e.
``(x - baseline) * calib * sensitivity / 204.8 / n == x``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional

from .export import ExportSet

HEADER_SIZE = 900
ELECTLOC_SIZE = 75


def _put_str(buf: bytearray, off: int, size: int, text: str):
    raw = (text or "").encode("latin-1", errors="replace")[:size - 1]
    buf[off:off + size] = raw + b"\x00" * (size - len(raw))


def write_avg(path: str, es: ExportSet, sweeps_header: int = 1) -> None:
    """Write *es* as a Neuroscan .avg file."""
    nchan = len(es.channels)
    pnts = es.n_points
    if nchan == 0 or pnts == 0:
        raise ValueError("nothing to write")
    if pnts > 65535 or nchan > 65535:
        raise ValueError("too many points/channels for the .avg format")
    rate = int(round(es.sample_rate_hz)) if es.sample_rate_hz else 0
    if not 0 < rate <= 65535:
        raise ValueError("sample rate %r not representable in .avg" % es.sample_rate_hz)

    h = bytearray(HEADER_SIZE)
    _put_str(h, 0, 12, "Version 3.0")
    h[20] = 0                                   # type: AVG
    _put_str(h, 21, 20, es.test_id)              # id
    _put_str(h, 41, 20, es.technician)           # oper
    _put_str(h, 121, 20, es.patient_id)          # patient
    _put_str(h, 205, 20, es.info.get("Stimulus", "")[:19])  # label
    if es.date:  # left empty for anonymised exports
        _put_str(h, 225, 10, es.date.strftime("%m/%d/%y"))
        _put_str(h, 235, 12, es.date.strftime("%H:%M:%S"))
    total = sum(int(c.averages or 0) for c in es.channels[:1])
    struct.pack_into("<H", h, 360, min(total, 65535))   # nsweeps (expected)
    struct.pack_into("<H", h, 362, sweeps_header)        # compsweeps (read as nsweeps)
    struct.pack_into("<H", h, 364, min(total, 65535))   # acceptcnt
    rej = sum(int(c.rejected or 0) for c in es.channels[:1])
    struct.pack_into("<H", h, 366, min(rej, 65535))     # rejectcnt
    struct.pack_into("<H", h, 368, pnts)
    struct.pack_into("<H", h, 370, nchan)
    struct.pack_into("<H", h, 372, 1)                   # avgupdate
    h[374] = 0                                          # domain: time
    h[375] = 1                                          # variance present
    struct.pack_into("<H", h, 376, rate)
    struct.pack_into("<d", h, 378, 1.0)                 # scale
    struct.pack_into("<f", h, 497, -10.0)               # dispmin
    struct.pack_into("<f", h, 501, 10.0)                # dispmax
    struct.pack_into("<f", h, 505, es.xmin_ms / 1000.0)  # xmin [s]
    struct.pack_into("<f", h, 509, es.xmax_ms / 1000.0)  # xmax [s]
    allv = [v for c in es.channels for v in c.values] or [0.0]
    struct.pack_into("<f", h, 513, min(allv))           # AutoMin
    struct.pack_into("<f", h, 517, max(allv))           # AutoMax
    struct.pack_into("<f", h, 529, es.low_cut_hz)       # lowcut
    struct.pack_into("<f", h, 533, es.high_cut_hz)      # highcut
    struct.pack_into("<f", h, 551, es.xmin_ms / 1000.0)  # DisplayXmin
    struct.pack_into("<f", h, 555, es.xmax_ms / 1000.0)  # DisplayXmax
    struct.pack_into("<f", h, 800, 1.0)                 # fratio
    struct.pack_into("<i", h, 864, pnts)                # NumSamples
    struct.pack_into("<f", h, 869, es.low_cut_hz)       # LowCutoff
    struct.pack_into("<f", h, 875, es.high_cut_hz)      # HighCutoff

    elec = bytearray()
    for i, c in enumerate(es.channels):
        e = bytearray(ELECTLOC_SIZE)
        _put_str(e, 0, 10, c.label[:9])
        e[13] = 1                                       # display
        struct.pack_into("<H", e, 15, 1)                # n
        struct.pack_into("<f", e, 19, float(i))         # x_coord
        struct.pack_into("<h", e, 47, 0)                # baseline
        struct.pack_into("<f", e, 59, 204.8)            # sensitivity
        e[69] = i + 1 if i < 255 else 255               # PhysicalChnl
        struct.pack_into("<f", e, 71, 1.0)              # calib
        elec += e

    with open(path, "wb") as fh:
        fh.write(h)
        fh.write(elec)
        for c in es.channels:
            fh.write(b"\x00" * 5)
            fh.write(struct.pack("<%df" % pnts, *c.values[:pnts]))
        zeros = struct.pack("<%df" % pnts, *([0.0] * pnts))
        for _ in es.channels:
            fh.write(zeros)


@dataclass
class AvgFile:
    pnts: int
    nchan: int
    rate: int
    xmin_ms: float
    xmax_ms: float
    nsweeps: int
    labels: List[str]
    data: List[List[float]]
    patient: str = ""
    test_id: str = ""

    def times_ms(self) -> List[float]:
        if self.pnts < 2:
            return [self.xmin_ms]
        step = (self.xmax_ms - self.xmin_ms) / (self.pnts - 1)
        return [self.xmin_ms + i * step for i in range(self.pnts)]


def read_avg(path: str) -> AvgFile:
    """Read a Neuroscan .avg file the way loadavg/openavg do
    (data scaled by calib*sensitivity/204.8 after baseline removal, / n)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if len(raw) < HEADER_SIZE:
        raise ValueError("%s: file too short for a .avg header" % path)
    nsweeps = struct.unpack_from("<H", raw, 362)[0]
    pnts, nchan = struct.unpack_from("<HH", raw, 368)
    rate = struct.unpack_from("<H", raw, 376)[0]
    xmin, xmax = struct.unpack_from("<ff", raw, 505)
    labels, factors, baselines, ns = [], [], [], []
    for i in range(nchan):
        o = HEADER_SIZE + i * ELECTLOC_SIZE
        labels.append(raw[o:o + 10].split(b"\x00")[0].decode("latin-1").strip())
        n = struct.unpack_from("<H", raw, o + 15)[0] or 1
        base = struct.unpack_from("<h", raw, o + 47)[0]
        sens = struct.unpack_from("<f", raw, o + 59)[0]
        calib = struct.unpack_from("<f", raw, o + 71)[0]
        factors.append(calib * sens / 204.8 if sens else calib)
        baselines.append(base)
        ns.append(n)
    off = HEADER_SIZE + nchan * ELECTLOC_SIZE
    data = []
    for i in range(nchan):
        off += 5
        vals = struct.unpack_from("<%df" % pnts, raw, off)
        off += 4 * pnts
        data.append([(v - baselines[i]) * factors[i] / ns[i] for v in vals])
    patient = raw[121:141].split(b"\x00")[0].decode("latin-1")
    test_id = raw[21:41].split(b"\x00")[0].decode("latin-1")
    return AvgFile(pnts=pnts, nchan=nchan, rate=rate, xmin_ms=xmin * 1000.0,
                   xmax_ms=xmax * 1000.0, nsweeps=nsweeps, labels=labels,
                   data=data, patient=patient, test_id=test_id)
