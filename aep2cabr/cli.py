"""Command line interface: ``python -m aep2cabr <command> ...``"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .ascii_aep2asc import AsciiOptions, write_ascii
from .biologic import BiologicDatabase, Record, configured_data_paths
from .export import (BASELINE_MODES, COMBINE_MODES, ExportSet, combine_records,
                     record_to_export, safe_filename)
from . import neuroscan, stimulus, textout

FORMATS = ("avg", "txt", "csv", "tsv", "ascii")


# --------------------------------------------------------------------------
# helpers shared with the GUI
# --------------------------------------------------------------------------
def ordered_records(db: BiologicDatabase) -> List[Record]:
    """Records in display order: patient (last name) -> test -> record."""
    out: List[Record] = []
    for p in db.patient_list():
        for t in db.tests_for(p.blscid):
            out.extend(sorted(db.records_for(p.blscid, t.test_id), key=lambda r: r.index))
    seen = {id(r) for r in out}
    out.extend(r for r in db.records if id(r) not in seen)
    return out


def parse_numbers(specs: Sequence[str]) -> List[int]:
    nums: List[int] = []
    for spec in specs:
        for part in str(spec).replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                nums.extend(range(int(a), int(b) + 1))
            else:
                nums.append(int(part))
    return nums


def export_records(records: Sequence[Record], numbers: Sequence[int], fmt: str, out: str,
                   banks: Optional[Sequence[int]] = None,
                   channels: Optional[Sequence[int]] = None,
                   baseline: str = "none", insert_delay_correction: bool = True,
                   timebase: str = "navigator", anonymize: bool = False,
                   multi_channel: bool = False, ascii_opts: Optional[AsciiOptions] = None,
                   append: bool = False, log=print) -> List[str]:
    """Export *records*; returns the list of files written."""
    written: List[str] = []
    if fmt == "ascii":
        if os.path.isdir(out) or out.endswith(os.sep):
            os.makedirs(out, exist_ok=True)
            out = os.path.join(out, "AEPASCII.txt")
        parent = os.path.dirname(os.path.abspath(out))
        os.makedirs(parent, exist_ok=True)
        opt = ascii_opts or AsciiOptions()
        opt.insert_delay_correction = insert_delay_correction
        opt.timebase = timebase
        opt.anonymize = anonymize or opt.anonymize
        n = write_ascii(out, records, opt, append=append)
        log("%d record(s) -> %s" % (n, out))
        return [out]

    os.makedirs(out, exist_ok=True)
    manifest = []
    for rec, num in zip(records, numbers):
        try:
            es = record_to_export(rec, banks=banks, channels=channels,
                                  insert_delay_correction=insert_delay_correction,
                                  timebase=timebase, baseline=baseline,
                                  anonymize=anonymize, number=num)
        except ValueError as e:
            log("skip #%d: %s" % (num, e))
            continue
        if fmt in ("csv", "tsv"):
            groups = [es]
        elif multi_channel and fmt == "avg":
            groups = [es]
        else:  # one file per waveform
            groups = []
            for ch in es.channels:
                sub = ExportSet(**{**es.__dict__, "channels": [ch],
                                   "name": es.name + "_" + ch.label})
                groups.append(sub)
        for g in groups:
            ext = {"avg": ".avg", "txt": ".txt", "csv": ".csv", "tsv": ".tsv"}[fmt]
            path = os.path.join(out, g.name + ext)
            if fmt == "avg":
                neuroscan.write_avg(path, g)
            elif fmt == "txt":
                textout.write_single_column(path, g)
                textout.write_info(os.path.join(out, g.name + ".info.txt"), g,
                                   os.path.basename(path))
            else:
                textout.write_table(path, g, "," if fmt == "csv" else "\t")
            written.append(path)
            manifest.append({
                "#": num, "file": os.path.basename(path),
                "waveforms": " ".join(c.label for c in g.channels),
                "test_type": rec.test_type_name, "ear": rec.ear,
                "stimulus": rec.stimulus, "polarity": rec.polarity,
                "intensity": rec.intensity, "rate": rec.rate,
                "sweeps": " ".join(str(c.averages or "") for c in g.channels),
                "points": g.n_points, "fs_hz": "%.3f" % g.sample_rate_hz,
                "first_ms": "%.4f" % g.xmin_ms, "last_ms": "%.4f" % g.xmax_ms,
                "baseline": baseline,
                "record_id": "" if anonymize else rec.record_id,
            })
            log("#%d -> %s" % (num, path))
    if manifest:
        mpath = os.path.join(out, "manifest.csv")
        new = not os.path.exists(mpath)
        with open(mpath, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
            if new:
                w.writeheader()
            w.writerows(manifest)
    return written


def write_export_set(es: ExportSet, path: str, fmt: Optional[str] = None) -> str:
    fmt = fmt or os.path.splitext(path)[1].lstrip(".").lower() or "avg"
    if fmt == "avg":
        neuroscan.write_avg(path, es)
    elif fmt == "txt":
        textout.write_single_column(path, es)
        textout.write_info(os.path.splitext(path)[0] + ".info.txt", es, os.path.basename(path))
    elif fmt in ("csv", "tsv"):
        textout.write_table(path, es, "," if fmt == "csv" else "\t")
    else:
        raise ValueError("unsupported format %s" % fmt)
    return path


# --------------------------------------------------------------------------
# argument handling
# --------------------------------------------------------------------------
def _open_db(args) -> BiologicDatabase:
    if args.epwin:
        return BiologicDatabase(args.epwin, args.patients)
    folder = args.data
    if not folder:
        default, listed = configured_data_paths(args.config)
        folder = default or (listed[0][1] if listed else None)
        if not folder:
            raise SystemExit("no database given: use --data FOLDER or --epwin EPWinData.mdb")
    return BiologicDatabase.from_folder(folder)


def _select(db: BiologicDatabase, args):
    ordered = ordered_records(db)
    pairs = list(enumerate(ordered, 1))
    if getattr(args, "records", None):
        wanted = parse_numbers(args.records)
        bad = [n for n in wanted if not 1 <= n <= len(ordered)]
        if bad:
            raise SystemExit("record number(s) out of range 1..%d: %s" % (len(ordered), bad))
        pairs = [(n, ordered[n - 1]) for n in wanted]
    if getattr(args, "record_id", None):
        ids = {x.strip("{}").upper() for x in args.record_id}
        pairs = [(n, r) for n, r in pairs if (r.record_id or "").strip("{}").upper() in ids]
    if getattr(args, "patient", None):
        pairs = [(n, r) for n, r in pairs if r.patient and r.patient.patient_id == args.patient]
    if getattr(args, "test", None):
        pairs = [(n, r) for n, r in pairs if r.test_id == args.test]
    if getattr(args, "cabr", False):
        pairs = [(n, r) for n, r in pairs if r.is_speech]
    return pairs


def _add_db_args(p):
    g = p.add_argument_group("database")
    g.add_argument("--data", help="folder containing BLPatients.mdb and EPWinData.mdb")
    g.add_argument("--epwin", help="path of EPWinData.mdb")
    g.add_argument("--patients", help="path of BLPatients.mdb (default: next to EPWinData.mdb)")
    g.add_argument("--config", help="path of BLdbAppCfg.mdb (AEP program data paths)")


def _add_sel_args(p):
    g = p.add_argument_group("selection")
    g.add_argument("-r", "--records", nargs="+", metavar="N",
                   help="record numbers from 'list' (e.g. 3 5 10-14)")
    g.add_argument("--record-id", nargs="+", help="RecordID GUID(s)")
    g.add_argument("--patient", help="Patient ID")
    g.add_argument("--test", help="Test ID (e.g. EP00001)")
    g.add_argument("--cabr", action="store_true",
                   help="only complex-sound (speech /da/, BioMAP) records")


def _add_proc_args(p):
    g = p.add_argument_group("processing")
    g.add_argument("--bank", type=int, nargs="+",
                   help="bank(s) to export: 1=cond 2=rare 10=added 11=subtracted")
    g.add_argument("--channel", type=int, nargs="+", help="channel(s) to export")
    g.add_argument("--baseline", choices=BASELINE_MODES, default="none",
                   help="DC/baseline correction (default none = raw values)")
    g.add_argument("--no-insert-delay", action="store_true",
                   help="do not shift time zero by the insert earphone delay")
    g.add_argument("--timebase", choices=("navigator", "hardware"), default="navigator",
                   help="navigator: EpochTime/points (as on screen); hardware: 48 kHz/k")
    g.add_argument("--anonymize", action="store_true",
                   help="no patient names/IDs in files and file names")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="aep2cabr",
        description="AEP2ASC rewrite: Bio-logic Navigator Pro (BLPatients.mdb + "
                    "EPWinData.mdb) -> cABR files (Neuroscan .avg for Brainstem "
                    "Toolbox / IHS cABR), text, CSV and AEP2ASC ASCII.")
    ap.add_argument("--version", action="version", version="aep2cabr " + __version__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("paths", help="show the data paths configured in BLdbAppCfg.mdb")
    p.add_argument("--config")

    p = sub.add_parser("list", help="list patients, tests and records")
    _add_db_args(p)
    _add_sel_args(p)

    p = sub.add_parser("export", help="export records")
    _add_db_args(p)
    _add_sel_args(p)
    _add_proc_args(p)
    p.add_argument("-f", "--format", choices=FORMATS, default="avg")
    p.add_argument("-o", "--out", default="export", help="output folder (ascii: file)")
    p.add_argument("--multi-channel", action="store_true",
                   help="avg: all banks/channels of a record in one file")
    p.add_argument("--all", action="store_true", help="export every record")
    a = p.add_argument_group("ascii options (AEP2ASC Setup)")
    for flag, help_ in (("no-patient", "patient information"), ("no-record", "record information"),
                        ("no-stimulus", "stimulus information"), ("no-amplifier", "amplifier information"),
                        ("no-latency", "marked point latency"), ("no-amplitude", "marked point amplitude"),
                        ("no-wave", "waveform data")):
        a.add_argument("--" + flag, action="store_true", help="omit " + help_)
    a.add_argument("--comma", action="store_true", help="comma instead of tab")
    a.add_argument("--rows", action="store_true", help="waveforms in rows")
    a.add_argument("--quotes", action="store_true", help="enclose fields in quotes")
    a.add_argument("--no-header", action="store_true", help="no header lines")
    a.add_argument("--append", action="store_true", help="append to existing file")

    p = sub.add_parser("combine", help="add or subtract records (e.g. two polarities)")
    _add_db_args(p)
    _add_sel_args(p)
    p.add_argument("--mode", choices=COMBINE_MODES, default="add")
    p.add_argument("--bank", type=int, help="bank to use (default: first stored bank)")
    p.add_argument("--channel", type=int, default=1)
    p.add_argument("--baseline", choices=BASELINE_MODES, default="none")
    p.add_argument("--no-insert-delay", action="store_true")
    p.add_argument("--timebase", choices=("navigator", "hardware"), default="navigator")
    p.add_argument("--anonymize", action="store_true")
    p.add_argument("-o", "--out", required=True, help="output file (.avg, .txt, .csv, .tsv)")

    p = sub.add_parser("wav2avg", help="convert a stimulus .wav to .avg")
    p.add_argument("wav")
    p.add_argument("avg", nargs="?")
    p.add_argument("--rate", type=float, help="resample to this rate (Hz)")
    p.add_argument("--wav-channel", type=int, default=0)
    p.add_argument("--prestim", type=float, default=0.0,
                   help="prepend this many ms of silence")

    p = sub.add_parser("avginfo", help="show the header and data range of a .avg file")
    p.add_argument("avg", nargs="+")

    sub.add_parser("gui", help="start the graphical interface")
    return ap


def _ascii_options(args) -> AsciiOptions:
    return AsciiOptions(
        patient_info=not args.no_patient, record_info=not args.no_record,
        stimulus_info=not args.no_stimulus, amplifier_info=not args.no_amplifier,
        mp_latency=not args.no_latency, mp_amplitude=not args.no_amplitude,
        wave_info=not args.no_wave, tab_delimited=not args.comma,
        columns=not args.rows, quotes=args.quotes, header=not args.no_header)


def cmd_list(args):
    try:
        _cmd_list(args)
    except BrokenPipeError:  # e.g. piped into 'head'
        sys.stderr.close()


def _cmd_list(args):
    db = _open_db(args)
    pairs = _select(db, args)
    last = None
    for n, r in pairs:
        key = (r.blscid, r.test_id)
        if key != last:
            last = key
            p = r.patient
            who = "%s  %s" % (p.patient_id, p.display_name) if p else "(patient not in BLPatients.mdb)"
            date = r.test.test_date if r.test else ""
            print("\n%s   test %s  %s" % (who, r.test_id, date or ""))
        print("  #%-4d R%-3d %-10s %-6s %-22s %-12s %-12s %6.2f ms %5d pts banks %-12s %s" % (
            n, r.index, r.test_type_name[:10], r.ear[:6], r.stimulus[:22],
            r.polarity[:12], r.intensity, r.epoch_ms, r.n_points,
            ",".join(map(str, r.banks)), "cABR" if r.is_speech else ""))
    print("\n%d record(s)" % len(pairs))


def cmd_export(args):
    db = _open_db(args)
    if not (args.records or args.record_id or args.patient or args.test or args.cabr or args.all):
        raise SystemExit("select records with -r/--records, --record-id, --patient, --test, --cabr or --all")
    pairs = _select(db, args)
    if not pairs:
        raise SystemExit("no records selected")
    files = export_records([r for _, r in pairs], [n for n, _ in pairs], args.format, args.out,
                           banks=args.bank, channels=args.channel, baseline=args.baseline,
                           insert_delay_correction=not args.no_insert_delay,
                           timebase=args.timebase, anonymize=args.anonymize,
                           multi_channel=args.multi_channel,
                           ascii_opts=_ascii_options(args), append=args.append)
    print("%d file(s) written" % len(files))


def cmd_combine(args):
    db = _open_db(args)
    pairs = _select(db, args)
    if not (args.records or args.record_id):
        raise SystemExit("choose the records to combine with -r/--records or --record-id")
    es = combine_records([r for _, r in pairs], mode=args.mode, bank=args.bank,
                         channel=args.channel, baseline=args.baseline,
                         insert_delay_correction=not args.no_insert_delay,
                         timebase=args.timebase, anonymize=args.anonymize)
    path = write_export_set(es, args.out)
    print("%s of %d record(s) -> %s" % (args.mode, len(pairs), path))


def cmd_wav2avg(args):
    out = args.avg or os.path.splitext(args.wav)[0] + ".avg"
    es = stimulus.wav2avg(args.wav, out, rate=args.rate, channel=args.wav_channel,
                          prestim_ms=args.prestim)
    print("%s -> %s (%d points, %.1f Hz, %.2f..%.2f ms)" % (
        args.wav, out, es.n_points, es.sample_rate_hz, es.xmin_ms, es.xmax_ms))


def cmd_avginfo(args):
    for path in args.avg:
        a = neuroscan.read_avg(path)
        print(path)
        print("  points %d  channels %d  rate %d Hz  xmin %.4f ms  xmax %.4f ms  sweeps-field %d"
              % (a.pnts, a.nchan, a.rate, a.xmin_ms, a.xmax_ms, a.nsweeps))
        for lab, d in zip(a.labels, a.data):
            print("  %-10s min %.4f uV  max %.4f uV" % (lab, min(d), max(d)))


def cmd_paths(args):
    default, listed = configured_data_paths(args.config)
    if default is None and not listed:
        print("BLdbAppCfg.mdb not found (looked in the AEP program folder)")
        return
    print("default: %s" % default)
    for name, path in listed:
        print("  %-20s %s" % (name, path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.cmd in (None, "gui"):
        from .gui import run
        return run() or 0
    handler = {"list": cmd_list, "export": cmd_export, "combine": cmd_combine,
               "wav2avg": cmd_wav2avg, "avginfo": cmd_avginfo, "paths": cmd_paths}[args.cmd]
    handler(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
