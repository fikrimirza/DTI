"""Bio-logic / Natus Navigator Pro AEP database model.

Reads the two databases written by the Navigator Pro AEP program

* ``BLPatients.mdb``  - patient & test information (PTI database)
* ``EPWinData.mdb``   - AEP records, waveforms, stimulus/amplifier settings

and turns every AEP record into a :class:`Record` holding its waveforms in
microvolts together with a time axis in milliseconds.

Format facts used here (worked out from AEP2ASC 1.6.0 and verified against
the marked points stored by the Navigator, see docs/ANALISIS_AEP2ASC.md):

* ``Records.Data`` (OLE field) = int32 header followed, for every stored
  channel/bank, by ``int32 channel, int32 bank, int32 n`` and ``n`` int32
  averaged A/D samples (little endian).
* microvolts = A/D * (10 V / 2**ADBits) / AmplifierGain * 1e6
  (16 bit, gain 100000 -> 0.0015259 uV per count).
* ``PrePostPoints`` is expressed in 1/48 ms ticks (48 kHz base clock):
  pre-stimulus time [ms] = PrePostPoints / 48.
* the Navigator displays latencies corrected for the insert earphone tube
  delay: t = PrePostPoints/48 + i * EpochTime/NumberofPoints - InsertDelay.
"""

from __future__ import annotations

import array
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import codes
from .jet4 import Jet4Database, float32_clean

AD_RANGE_VOLTS = 10.0          # +/-5 V A/D input range
PREPOST_TICKS_PER_MS = 48.0    # PrePostPoints unit = 1/48 ms
DEFAULT_GAIN = 100000

DEFAULT_CONFIG_LOCATIONS = [
    r"C:\Program Files\Bio-logic Systems Corp\AEP\BLdbAppCfg.mdb",
    r"C:\Program Files (x86)\Bio-logic Systems Corp\AEP\BLdbAppCfg.mdb",
    r"C:\Program Files (x86)\Natus\AEP\BLdbAppCfg.mdb",
    r"C:\Program Files\Natus\AEP\BLdbAppCfg.mdb",
]
DEFAULT_DATA_LOCATIONS = [r"C:\p&ti\data"]

PATIENTS_DB = "BLPatients.mdb"
EPWIN_DB = "EPWinData.mdb"


class DataFormatError(Exception):
    """Raised when a waveform blob cannot be decoded."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _clean(v):
    return float32_clean(v) if isinstance(v, float) else v


def decode_data_blob(blob: bytes) -> Tuple[int, List[Tuple[int, int, array.array]]]:
    """Decode the ``Records.Data`` OLE field.

    Returns ``(header, [(channel, bank, samples), ...])`` where samples is an
    ``array('i')`` of averaged A/D values.
    """
    if not blob or len(blob) < 4:
        raise DataFormatError("empty waveform data")
    ints = array.array("i")
    if ints.itemsize != 4:  # pragma: no cover - exotic platforms
        raise DataFormatError("platform without 32 bit int")
    usable = len(blob) - (len(blob) % 4)
    ints.frombytes(blob[:usable])
    if sys.byteorder != "little":  # pragma: no cover
        ints.byteswap()
    header = ints[0]
    blocks = []
    pos = 1
    while pos < len(ints):
        if pos + 3 > len(ints):
            raise DataFormatError("truncated channel header")
        ch, bank, n = ints[pos], ints[pos + 1], ints[pos + 2]
        pos += 3
        if n < 0 or pos + n > len(ints) or not (0 <= ch < 256) or not (0 <= bank < 256):
            raise DataFormatError(
                "Data field format not recognised (AEP version 1.1.6 or above "
                "required)")
        blocks.append((ch, bank, ints[pos:pos + n]))
        pos += n
    return header, blocks


def ad_to_uv_scale(ad_bits: Optional[int], gain: Optional[float]) -> float:
    """Microvolts per A/D count."""
    bits = int(ad_bits) if ad_bits else 16
    g = float(gain) if gain else DEFAULT_GAIN
    return AD_RANGE_VOLTS / (2 ** bits) / g * 1e6


# --------------------------------------------------------------------------
# data classes
# --------------------------------------------------------------------------
@dataclass
class Patient:
    blscid: str
    patient_id: str = ""
    last_name: str = ""
    first_name: str = ""
    middle_initial: str = ""
    birthdate: Any = None
    sex: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> str:
        name = ", ".join(x for x in (self.last_name, self.first_name) if x)
        return name or "(no name)"


@dataclass
class Test:
    blscid: str
    test_id: str
    test_type: str = ""
    test_date: Any = None
    start_time: Any = None
    end_time: Any = None
    technician: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Waveform:
    channel: int
    bank: int
    ad: Sequence[int]
    scale_uv: float
    averages: Optional[int] = None
    rejected: Optional[int] = None
    comment: str = ""
    bank_name: str = ""

    @property
    def uv(self) -> List[float]:
        s = self.scale_uv
        return [v * s for v in self.ad]

    @property
    def label(self) -> str:
        return "C%dB%d" % (self.channel, self.bank)


@dataclass
class MarkedPoint:
    channel: int
    bank: int
    label_number: int
    label: str
    point: Optional[int]
    latency_ms: Optional[float]
    amplitude_uv: Optional[float]


@dataclass
class Record:
    raw: Dict[str, Any] = field(repr=False)
    index: int = 0                      # 1-based position inside its test
    patient: Optional[Patient] = None
    test: Optional[Test] = None
    stim: Optional[Dict[str, Any]] = field(default=None, repr=False)
    stim_table: Optional[str] = None
    amplifiers: Dict[int, Dict[str, Any]] = field(default_factory=dict, repr=False)
    waveforms: List[Waveform] = field(default_factory=list, repr=False)
    marked_points: List[MarkedPoint] = field(default_factory=list, repr=False)
    labels: Dict[int, str] = field(default_factory=dict, repr=False)
    warnings: List[str] = field(default_factory=list, repr=False)

    # -- raw fields ------------------------------------------------------
    def _r(self, key, default=None):
        v = self.raw.get(key)
        return default if v is None else _clean(v)

    record_id = property(lambda self: self.raw.get("RecordID"))
    blscid = property(lambda self: self.raw.get("BLSCID"))
    test_id = property(lambda self: self.raw.get("TestID"))
    test_type = property(lambda self: self.raw.get("TestType"))
    start_time = property(lambda self: self.raw.get("StartTime"))
    stop_time = property(lambda self: self.raw.get("StopTime"))
    comments = property(lambda self: self.raw.get("Comments") or "")
    n_channels = property(lambda self: self._r("NumberofChannels", 0))
    n_points = property(lambda self: self._r("NumberofPoints", 0))
    epoch_ms = property(lambda self: self._r("EpochTime", 0.0))
    collection_rate = property(lambda self: self._r("CollectionRate"))
    prepost_points = property(lambda self: self._r("PrePostPoints", 0))
    blocked_points = property(lambda self: self._r("BlockedPoints", 0))
    ad_bits = property(lambda self: self._r("ADBits", 16))
    software_version = property(lambda self: self.raw.get("SoftwareVersion") or "")

    # -- derived ---------------------------------------------------------
    @property
    def test_type_name(self) -> str:
        return codes.text(codes.TEST_TYPES, self.test_type)

    @property
    def sample_interval_ms(self) -> float:
        """Sample interval as used by the Navigator (EpochTime / points)."""
        return self.epoch_ms / self.n_points if self.n_points else 0.0

    @property
    def sample_rate_hz(self) -> float:
        dt = self.sample_interval_ms
        return 1000.0 / dt if dt else 0.0

    @property
    def hardware_sample_rate_hz(self) -> float:
        """Sampling rate assuming a 48 kHz base clock (48000/k Hz)."""
        fs = self.sample_rate_hz
        if not fs:
            return 0.0
        k = max(1, round(48000.0 / fs))
        exact = 48000.0 / k
        return exact if abs(exact - fs) / fs < 0.005 else fs

    @property
    def prestim_ms(self) -> float:
        return (self.prepost_points or 0) / PREPOST_TICKS_PER_MS

    @property
    def blocked_ms(self) -> float:
        return (self.blocked_points or 0) / PREPOST_TICKS_PER_MS

    @property
    def insert_delay_ms(self) -> float:
        if self.stim:
            v = self.stim.get("InsertDelay")
            if v is not None:
                return float(_clean(v))
        return 0.0

    def times_ms(self, insert_delay_correction: bool = True,
                 timebase: str = "navigator") -> List[float]:
        """Time of every sample in ms re. stimulus onset."""
        if timebase == "hardware" and self.hardware_sample_rate_hz:
            dt = 1000.0 / self.hardware_sample_rate_hz
        else:
            dt = self.sample_interval_ms
        t0 = self.prestim_ms - (self.insert_delay_ms if insert_delay_correction else 0.0)
        n = max((len(w.ad) for w in self.waveforms), default=self.n_points)
        return [t0 + i * dt for i in range(n)]

    def waveform(self, channel: int, bank: int) -> Optional[Waveform]:
        for w in self.waveforms:
            if w.channel == channel and w.bank == bank:
                return w
        return None

    @property
    def banks(self) -> List[int]:
        return sorted({w.bank for w in self.waveforms})

    # -- stimulus description ------------------------------------------
    def stim_value(self, key, default=None):
        if not self.stim:
            return default
        v = self.stim.get(key)
        return default if v is None else _clean(v)

    @property
    def is_external(self) -> bool:
        return self.stim_table in ("EXTStim", "EXTP300Stim")

    @property
    def ear(self) -> str:
        if self.is_external:
            return self.stim_value("Location", "") or ""
        return codes.text(codes.STIM_EAR, self.stim_value("StimEar"))

    @property
    def transducer(self) -> str:
        if self.is_external:
            return self.stim_value("Transducer", "") or ""
        return codes.text(codes.TRANSDUCERS, self.stim_value("Transducer"))

    @property
    def stimulus(self) -> str:
        if self.is_external:
            return str(self.stim_value("StimType", "") or "")
        st = self.stim_value("StimType")
        name = codes.text(codes.STIM_TYPES, st)
        if st == 6:
            fn = self.stim_value("CustomStimFileName", "") or ""
            return "Custom: %s" % fn.replace("/", "\\").split("\\")[-1]
        if st == 4:
            f = self.stim_value("StimFrequency")
            if f and f > 0:
                return "%s %s Hz" % (name, f)
        return name

    @property
    def custom_stim_file(self) -> str:
        return (self.stim_value("CustomStimFileName", "") or "") if self.stim else ""

    @property
    def polarity(self) -> str:
        if self.is_external:
            return ""
        return codes.text(codes.POLARITY, self.stim_value("StimPolarity"))

    @property
    def intensity(self) -> str:
        if self.is_external:
            return str(self.stim_value("StimIntensity", "") or "")
        v = self.stim_value("StimIntensity")
        if v is None:
            return ""
        scale = codes.INTENSITY_SCALE.get(self.stim_value("IntensityScaleName"), "dB")
        return "%s %s" % (v, scale)

    @property
    def rate(self) -> str:
        v = self.stim_value("StimRateValue")
        return "" if v is None else "%s/s" % v

    def masking(self, which: str = "contra") -> str:
        if self.is_external or not self.stim:
            return ""
        if which == "contra":
            mtype, level = self.stim_value("StimMaskType"), self.stim_value("StimMaskIntensity")
        else:
            mtype, level = self.stim_value("IpsiMaskType"), self.stim_value("IpsiMaskIntensityOffset")
        name = codes.MASK_TYPES.get(mtype)
        if not name:
            return "None"
        return "%s(%s)" % (name, level)

    @property
    def is_speech(self) -> bool:
        """True for complex-sound (cABR / speech ABR) recordings."""
        return self.test_type == 9 or (not self.is_external and self.stim_value("StimType") == 6)

    def bank_name(self, bank: int) -> str:
        if self.test_type in (2, 5):
            return codes.P300_BANK_NAMES.get(bank, "Bank %d" % bank)
        if len(self.banks) == 1:
            return self.polarity or "Bank %d" % bank
        return codes.BANK_NAMES.get(bank, "Bank %d" % bank)

    def short_name(self) -> str:
        """Short description used in file names / lists."""
        parts = [self.test_type_name, self.ear, self.intensity.replace(" ", "")]
        if self.is_speech:
            parts.append(os.path.splitext(self.stimulus.split(":")[-1].strip())[0])
        else:
            parts.append(self.stimulus)
        return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------
class BiologicDatabase:
    """Patients, tests and AEP records of one Navigator Pro data folder."""

    def __init__(self, epwin_path: str, patients_path: Optional[str] = None):
        if not os.path.isfile(epwin_path):
            raise FileNotFoundError(epwin_path)
        if patients_path is None:
            cand = os.path.join(os.path.dirname(os.path.abspath(epwin_path)), PATIENTS_DB)
            patients_path = cand if os.path.isfile(cand) else None
        self.epwin_path = epwin_path
        self.patients_path = patients_path
        self.patients: Dict[str, Patient] = {}
        self.tests: Dict[Tuple[str, str], Test] = {}
        self.records: List[Record] = []
        self._load()

    @classmethod
    def from_folder(cls, folder: str) -> "BiologicDatabase":
        ep = _find_file(folder, EPWIN_DB)
        if not ep:
            raise FileNotFoundError("%s not found in %s" % (EPWIN_DB, folder))
        return cls(ep, _find_file(folder, PATIENTS_DB))

    # -- loading ---------------------------------------------------------
    def _load(self):
        if self.patients_path:
            with Jet4Database(self.patients_path) as pdb:
                for row in pdb.rows("Patients"):
                    p = Patient(
                        blscid=row.get("BLSCID"),
                        patient_id=row.get("PatientID") or "",
                        last_name=row.get("LastName") or "",
                        first_name=row.get("FirstName") or "",
                        middle_initial=row.get("MiddleInitial") or "",
                        birthdate=row.get("Birthdate"),
                        sex=row.get("Sex") or "",
                        raw=row)
                    self.patients[p.blscid] = p
                for row in pdb.rows("Tests"):
                    t = Test(blscid=row.get("BLSCID"), test_id=row.get("TestID"),
                             test_type=row.get("TestType") or "",
                             test_date=row.get("TestDate"),
                             start_time=row.get("StartTime"),
                             end_time=row.get("EndTime"),
                             technician=row.get("Technician") or "", raw=row)
                    self.tests[(t.blscid, t.test_id)] = t

        with Jet4Database(self.epwin_path) as db:
            names = {n.lower(): n for n in db.table_names()}

            def table(name):
                real = names.get(name.lower())
                return list(db.rows(real)) if real else []

            stims: Dict[str, Tuple[str, Dict[str, Any]]] = {}
            for tname in codes.ALL_STIM_TABLES:
                for row in table(tname):
                    stims.setdefault(row.get("RecordID"), (tname, row))
            amps: Dict[str, Dict[int, Dict[str, Any]]] = {}
            for row in table("Amplifiers"):
                amps.setdefault(row.get("RecordID"), {})[row.get("ChannelNumber") or 1] = row
            epdata: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
            for row in table("EPData"):
                epdata[(row.get("RecordID"), row.get("ChannelNumber"), row.get("BankNumber"))] = row
            labels: Dict[str, Dict[int, str]] = {}
            for row in table("Labels"):
                labels.setdefault(row.get("RecordID"), {})[row.get("LabelNumber")] = row.get("LabelText") or ""
            marked: Dict[str, List[Dict[str, Any]]] = {}
            for row in table("MarkedPoints"):
                marked.setdefault(row.get("RecordID"), []).append(row)

            recs = []
            for row in table("Records"):
                rid = row.get("RecordID")
                rec = Record(raw={k: v for k, v in row.items() if k != "Data"})
                rec.patient = self.patients.get(rec.blscid)
                rec.test = self.tests.get((rec.blscid, rec.test_id))
                st = stims.get(rid)
                if st:
                    rec.stim_table, rec.stim = st
                rec.amplifiers = amps.get(rid, {})
                rec.labels = labels.get(rid, {})
                try:
                    _hdr, blocks = decode_data_blob(row.get("Data") or b"")
                except DataFormatError as e:
                    rec.warnings.append(str(e))
                    blocks = []
                for ch, bank, samples in blocks:
                    amp = rec.amplifiers.get(ch) or rec.amplifiers.get(1) or {}
                    gain = amp.get("AmplifierGain")
                    if not gain:
                        rec.warnings.append("no amplifier gain for channel %d, using %d" % (ch, DEFAULT_GAIN))
                    ep = epdata.get((rid, ch, bank), {})
                    rec.waveforms.append(Waveform(
                        channel=ch, bank=bank, ad=samples,
                        scale_uv=ad_to_uv_scale(rec.ad_bits, gain),
                        averages=ep.get("Averages"),
                        rejected=ep.get("ArtifactsRejected"),
                        comment=ep.get("Comments") or ""))
                for w in rec.waveforms:
                    w.bank_name = rec.bank_name(w.bank)
                for m in marked.get(rid, []):
                    ln = m.get("LabelNumber")
                    rec.marked_points.append(MarkedPoint(
                        channel=m.get("ChannelNumber"), bank=m.get("BankNumber"),
                        label_number=ln, label=rec.labels.get(ln, "") or str(ln),
                        point=m.get("MarkedPoint"),
                        latency_ms=_clean(m.get("MarkedLatency")),
                        amplitude_uv=_clean(m.get("MarkedAmplitude"))))
                recs.append(rec)

        # AEP2ASC lists records ordered by StopTime; number them per test
        import datetime as _dt
        _min = _dt.datetime.min
        recs.sort(key=lambda r: (r.stop_time or _min, r.start_time or _min))
        counters: Dict[Tuple[str, str], int] = {}
        for r in recs:
            key = (r.blscid, r.test_id)
            counters[key] = counters.get(key, 0) + 1
            r.index = counters[key]
        self.records = recs

    # -- queries -----------------------------------------------------------
    def patient_list(self) -> List[Patient]:
        """Patients ordered by last name (as AEP2ASC); patients that only
        exist in EPWinData (e.g. demo records) are added as placeholders."""
        pats = dict(self.patients)
        for r in self.records:
            if r.blscid not in pats:
                pats[r.blscid] = Patient(blscid=r.blscid, patient_id="?",
                                         last_name="(not in BLPatients)")
        return sorted(pats.values(), key=lambda p: ((p.last_name or "").lower(),
                                                    (p.first_name or "").lower()))

    def tests_for(self, blscid: str) -> List[Test]:
        tests = [t for (b, _), t in self.tests.items() if b == blscid]
        known = {t.test_id for t in tests}
        for r in self.records:
            if r.blscid == blscid and r.test_id not in known:
                known.add(r.test_id)
                tests.append(Test(blscid=blscid, test_id=r.test_id, test_type="EP"))
        import datetime as _dt
        return sorted(tests, key=lambda t: (t.test_date or _dt.datetime.min, t.test_id))

    def records_for(self, blscid: Optional[str] = None,
                    test_id: Optional[str] = None) -> List[Record]:
        return [r for r in self.records
                if (blscid is None or r.blscid == blscid)
                and (test_id is None or r.test_id == test_id)]

    def find(self, record_id: str) -> Record:
        rid = record_id.strip("{}").upper()
        for r in self.records:
            if (r.record_id or "").strip("{}").upper() == rid:
                return r
        raise KeyError("record %s not found" % record_id)


def _find_file(folder: str, name: str) -> Optional[str]:
    try:
        for f in os.listdir(folder):
            if f.lower() == name.lower():
                return os.path.join(folder, f)
    except OSError:
        return None
    return None


def configured_data_paths(config_path: Optional[str] = None) -> Tuple[Optional[str], List[Tuple[str, str]]]:
    """Read the AEP program's data paths from ``BLdbAppCfg.mdb``.

    Returns ``(default_path, [(name, path), ...])``; empty when the
    configuration database cannot be found.
    """
    paths = [config_path] if config_path else DEFAULT_CONFIG_LOCATIONS
    for p in paths:
        if p and os.path.isfile(p):
            with Jet4Database(p) as db:
                default = None
                listed: List[Tuple[str, str]] = []
                try:
                    for row in db.rows("Defaults"):
                        default = row.get("OpenPath") or default
                except KeyError:
                    pass
                try:
                    for row in db.rows("DataPaths"):
                        if row.get("FilePath"):
                            listed.append((row.get("PathName") or row["FilePath"], row["FilePath"]))
                except KeyError:
                    pass
                return default, listed
    return None, []
