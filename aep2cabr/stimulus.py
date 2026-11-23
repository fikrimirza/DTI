"""Convert a stimulus .wav file (e.g. Bio-logic ``da.wav`` /
``BioMAP_da.wav``) to Neuroscan .avg - the stimulus format required by the
pitch tracking module (Brainstem Toolbox ``bt_ptgui`` / IHS ``IHSPITCH``:
"Stimulus file must be in '.avg' format.  Use wav2avg to convert.").
"""

from __future__ import annotations

import math
import struct
import wave
from typing import List, Optional, Tuple

from .export import Channel, ExportSet, safe_filename
from . import neuroscan


def read_wav(path: str, channel: int = 0) -> Tuple[List[float], int]:
    """Read a PCM .wav file; returns (samples scaled to -1..1, rate)."""
    try:
        with wave.open(path, "rb") as w:
            nch, width, rate, nframes = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(nframes)
    except wave.Error:
        return _read_float_wav(path, channel)
    if channel >= nch:
        raise ValueError("wav has only %d channel(s)" % nch)
    out: List[float] = []
    step = nch * width
    if width == 1:
        for i in range(channel, len(raw) // step * step, step):
            out.append((raw[i] - 128) / 128.0)
    elif width == 2:
        vals = struct.unpack("<%dh" % (len(raw) // 2), raw[:len(raw) // 2 * 2])
        out = [v / 32768.0 for v in vals[channel::nch]]
    elif width == 3:
        for i in range(channel * 3, len(raw) // step * step, step):
            v = int.from_bytes(raw[i:i + 3], "little", signed=True)
            out.append(v / 8388608.0)
    elif width == 4:
        vals = struct.unpack("<%di" % (len(raw) // 4), raw[:len(raw) // 4 * 4])
        out = [v / 2147483648.0 for v in vals[channel::nch]]
    else:
        raise ValueError("unsupported sample width %d" % width)
    return out, rate


def _read_float_wav(path: str, channel: int) -> Tuple[List[float], int]:
    """Minimal reader for IEEE float (format 3) wav files."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("%s is not a wav file" % path)
    pos = 12
    fmt = None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data" and fmt:
            tag, nch, rate, _, _, bits = fmt
            if tag not in (3, 0xFFFE) or bits not in (32, 64):
                raise ValueError("unsupported wav encoding (tag %d, %d bits)" % (tag, bits))
            code = "f" if bits == 32 else "d"
            n = len(body) // (bits // 8)
            vals = struct.unpack("<%d%s" % (n, code), body[:n * bits // 8])
            return list(vals[channel::nch]), rate
        pos += 8 + size + (size & 1)
    raise ValueError("no audio data in %s" % path)


def resample(x: List[float], fs_in: float, fs_out: float, half_width: int = 16) -> List[float]:
    """Band-limited (windowed sinc, Blackman) resampling."""
    if fs_in == fs_out:
        return list(x)
    ratio = fs_out / fs_in
    cutoff = min(1.0, ratio) * 0.95          # fraction of the input Nyquist
    support = half_width / cutoff
    n_out = int(math.floor(len(x) * ratio))
    out = []
    nin = len(x)
    for j in range(n_out):
        t = j / ratio
        lo = max(0, int(math.ceil(t - support)))
        hi = min(nin - 1, int(math.floor(t + support)))
        acc = 0.0
        for k in range(lo, hi + 1):
            d = t - k
            u = d / support
            if abs(u) >= 1.0:
                continue
            arg = math.pi * cutoff * d
            sinc = 1.0 if arg == 0 else math.sin(arg) / arg
            win = 0.42 + 0.5 * math.cos(math.pi * u) + 0.08 * math.cos(2 * math.pi * u)
            acc += x[k] * cutoff * sinc * win
        out.append(acc)
    return out


def wav_to_export(path: str, rate: Optional[float] = None, channel: int = 0,
                  prestim_ms: float = 0.0, scale: float = 1.0) -> ExportSet:
    samples, fs = read_wav(path, channel)
    if rate and abs(rate - fs) > 1e-9:
        samples = resample(samples, fs, rate)
        fs = rate
    pad = int(round(prestim_ms * fs / 1000.0)) if prestim_ms > 0 else 0
    samples = [0.0] * pad + [s * scale for s in samples]
    t0 = -pad * 1000.0 / fs
    times = [t0 + i * 1000.0 / fs for i in range(len(samples))]
    import os
    return ExportSet(name=safe_filename(os.path.splitext(os.path.basename(path))[0]),
                     times_ms=times, channels=[Channel(label="STIM", values=samples)],
                     sample_rate_hz=fs,
                     info={"Source": "stimulus wav: %s" % os.path.basename(path),
                           "SampleRate_Hz": "%g" % fs})


def wav2avg(wav_path: str, avg_path: str, rate: Optional[float] = None,
            channel: int = 0, prestim_ms: float = 0.0) -> ExportSet:
    es = wav_to_export(wav_path, rate=rate, channel=channel, prestim_ms=prestim_ms)
    neuroscan.write_avg(avg_path, es)
    return es
