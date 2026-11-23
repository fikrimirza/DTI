"""Minimal read-only reader for Microsoft Access Jet4 (.mdb) databases.

Pure Python, no ODBC driver, no Microsoft Access Database Engine needed.
It implements just enough of the Jet4 on-disk format to read the tables
written by the Bio-logic / Natus Navigator Pro AEP software
(``BLPatients.mdb`` and ``EPWinData.mdb``):

* table catalog (``MSysObjects``)
* table definitions spanning several pages
* data pages located through the table usage map (inline or reference map)
* fixed columns: BOOLEAN, BYTE, INT, LONG, MONEY, FLOAT, DOUBLE, DATETIME,
  GUID, NUMERIC
* variable columns: TEXT (incl. Jet4 "compressed unicode"), BINARY
* long values: MEMO and OLE (inline, single-page and multi-page LVAL chains)
* overflow rows (rows moved to another page after an update)

Only reading is supported; the file is opened read-only and never modified.
Encrypted / password protected databases are not supported.
"""

from __future__ import annotations

import datetime as _dt
import struct
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterator, List, Optional

PAGE_SIZE = 4096

# column types
T_BOOL = 0x01
T_BYTE = 0x02
T_INT = 0x03
T_LONG = 0x04
T_MONEY = 0x05
T_FLOAT = 0x06
T_DOUBLE = 0x07
T_DATETIME = 0x08
T_BINARY = 0x09
T_TEXT = 0x0A
T_OLE = 0x0B
T_MEMO = 0x0C
T_GUID = 0x0F
T_NUMERIC = 0x10
T_COMPLEX = 0x12

TYPE_NAMES = {
    T_BOOL: "BOOLEAN", T_BYTE: "BYTE", T_INT: "INT", T_LONG: "LONG",
    T_MONEY: "MONEY", T_FLOAT: "FLOAT", T_DOUBLE: "DOUBLE",
    T_DATETIME: "DATETIME", T_BINARY: "BINARY", T_TEXT: "TEXT", T_OLE: "OLE",
    T_MEMO: "MEMO", T_GUID: "GUID", T_NUMERIC: "NUMERIC", T_COMPLEX: "COMPLEX",
}

_FIXED_SIZES = {
    T_BYTE: 1, T_INT: 2, T_LONG: 4, T_MONEY: 8, T_FLOAT: 4, T_DOUBLE: 8,
    T_DATETIME: 8, T_GUID: 16, T_NUMERIC: 17, T_COMPLEX: 4,
}

_ROW_DELETED = 0x8000
_ROW_OVERFLOW = 0x4000
_ROW_OFFSET_MASK = 0x1FFF

_OLE_EPOCH = _dt.datetime(1899, 12, 30)


class Jet4Error(Exception):
    """Raised when the file is not a readable Jet4 database."""


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def decode_text(raw: bytes) -> str:
    """Decode a Jet4 text value (UCS-2LE, optionally 'compressed')."""
    if len(raw) >= 2 and raw[0] == 0xFF and raw[1] == 0xFE:
        out: List[str] = []
        compressed = True
        i = 2
        n = len(raw)
        while i < n:
            if raw[i] == 0:
                compressed = not compressed
                i += 1
                continue
            if compressed:
                out.append(chr(raw[i]))
                i += 1
            else:
                if i + 1 >= n:
                    break
                out.append(raw[i:i + 2].decode("utf-16-le", errors="replace"))
                i += 2
        return "".join(out)
    if len(raw) % 2:
        raw = raw[:-1]
    return raw.decode("utf-16-le", errors="replace")


def ole_date(value: float) -> _dt.datetime:
    """Convert an OLE automation date (days since 1899-12-30) to datetime."""
    days = int(value)  # truncates towards zero, as OLE dates do
    frac = abs(value - days)
    ms = round(frac * 86400000.0)
    return _OLE_EPOCH + _dt.timedelta(days=days, milliseconds=ms)


@dataclass
class Column:
    name: str
    type: int
    col_num: int
    var_index: int
    fixed_offset: int
    length: int
    flags: int

    @property
    def is_fixed(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type, "0x%02X" % self.type)


@dataclass
class TableDef:
    name: str
    page: int
    num_rows: int
    num_var_cols: int
    columns: List[Column] = field(default_factory=list)
    usage_map_ptr: int = 0

    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]


class Jet4Database:
    """Read-only access to a Jet4 ``.mdb`` file.

    Example::

        with Jet4Database("EPWinData.mdb") as db:
            for row in db.rows("Records"):
                print(row["RecordID"], row["TestType"])
    """

    def __init__(self, path: str):
        self.path = path
        self._fh = open(path, "rb")
        self._fh.seek(0, 2)
        self._size = self._fh.tell()
        self._page_cache: Dict[int, bytes] = {}
        hdr = self.page(0)
        if hdr[:4] != b"\x00\x01\x00\x00" or (
            b"Standard Jet DB" not in hdr[4:20] and b"Standard ACE DB" not in hdr[4:20]
        ):
            raise Jet4Error("%s is not a Microsoft Access database" % path)
        self.version = hdr[0x14]
        if self.version == 0:
            raise Jet4Error("Jet3 (Access 97) databases are not supported: %s" % path)
        self._tables: Optional[Dict[str, TableDef]] = None

    # -- context manager -------------------------------------------------
    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- low level -------------------------------------------------------
    def page(self, num: int) -> bytes:
        p = self._page_cache.get(num)
        if p is None:
            off = num * PAGE_SIZE
            if off + PAGE_SIZE > self._size:
                raise Jet4Error("page %d beyond end of file" % num)
            self._fh.seek(off)
            p = self._fh.read(PAGE_SIZE)
            if len(self._page_cache) > 4096:
                self._page_cache.clear()
            self._page_cache[num] = p
        return p

    @staticmethod
    def _row_bounds(pg: bytes, row: int):
        nrows = _u16(pg, 12)
        if row >= nrows:
            raise Jet4Error("row %d not on page (has %d rows)" % (row, nrows))
        raw = _u16(pg, 14 + 2 * row)
        start = raw & _ROW_OFFSET_MASK
        if row == 0:
            end = PAGE_SIZE
        else:
            end = _u16(pg, 14 + 2 * (row - 1)) & _ROW_OFFSET_MASK
        return start, end, raw

    def _read_row_ptr(self, ptr: int) -> bytes:
        """Read the raw bytes of a row addressed by a Jet row pointer."""
        pg = self.page(ptr >> 8)
        start, end, _ = self._row_bounds(pg, ptr & 0xFF)
        return pg[start:end]

    # -- table definitions ----------------------------------------------
    def _read_tdef(self, page_num: int, name: str) -> TableDef:
        pg = self.page(page_num)
        if pg[0] != 0x02:
            raise Jet4Error("page %d is not a table definition" % page_num)
        data = bytearray(pg)
        nxt = _u32(pg, 4)
        guard = 0
        while nxt:
            more = self.page(nxt)
            data += more[8:]
            nxt = _u32(more, 4)
            guard += 1
            if guard > 1000:
                raise Jet4Error("table definition chain loop")
        num_rows = _u32(data, 16)
        num_var_cols = _u16(data, 43)
        num_cols = _u16(data, 45)
        num_real_idx = _u32(data, 51)
        usage = _u32(data, 55)
        off = 63 + num_real_idx * 12
        cols = []
        for _ in range(num_cols):
            c = data[off:off + 25]
            cols.append(Column(
                name="", type=c[0], col_num=_u16(c, 5), var_index=_u16(c, 7),
                flags=c[15], fixed_offset=_u16(c, 21), length=_u16(c, 23)))
            off += 25
        for c in cols:
            n = _u16(data, off)
            c.name = bytes(data[off + 2:off + 2 + n]).decode("utf-16-le")
            off += 2 + n
        # Access lists columns in col_num order
        cols.sort(key=lambda c: c.col_num)
        return TableDef(name=name, page=page_num, num_rows=num_rows,
                        num_var_cols=num_var_cols, columns=cols,
                        usage_map_ptr=usage)

    def _data_pages(self, tdef: TableDef) -> List[int]:
        pages: List[int] = []
        try:
            umap = self._read_row_ptr(tdef.usage_map_ptr)
            if umap[0] == 0:
                start = _u32(umap, 1)
                for i, byte in enumerate(umap[5:]):
                    if byte:
                        for bit in range(8):
                            if byte & (1 << bit):
                                pages.append(start + i * 8 + bit)
            elif umap[0] == 1:
                per_page = (PAGE_SIZE - 4) * 8
                for j in range((len(umap) - 1) // 4):
                    mp = _u32(umap, 1 + 4 * j)
                    if not mp:
                        continue
                    bm = self.page(mp)[4:]
                    for i, byte in enumerate(bm):
                        if byte:
                            for bit in range(8):
                                if byte & (1 << bit):
                                    pages.append(j * per_page + i * 8 + bit)
            else:
                raise Jet4Error("unknown usage map type %d" % umap[0])
        except (Jet4Error, struct.error, IndexError):
            pages = []
        if not pages:  # fall back to a full scan of the file
            pages = list(range(1, self._size // PAGE_SIZE))
        out = []
        for p in pages:
            if p * PAGE_SIZE + PAGE_SIZE > self._size:
                continue
            pg = self.page(p)
            if pg[0] == 0x01 and _u32(pg, 4) == tdef.page:
                out.append(p)
        return out

    @property
    def tables(self) -> Dict[str, TableDef]:
        if self._tables is None:
            msys = self._read_tdef(2, "MSysObjects")
            tables: Dict[str, TableDef] = {}
            for row in self._iter_rows(msys):
                typ = row.get("Type")
                name = row.get("Name")
                flags = row.get("Flags") or 0
                if typ != 1 or not name:
                    continue
                if name.startswith("MSys") or (flags & 0x80000002):
                    continue
                pg = (row.get("Id") or 0) & 0x00FFFFFF
                try:
                    tables[name] = self._read_tdef(pg, name)
                except Jet4Error:
                    continue
            self._tables = tables
        return self._tables

    def table_names(self) -> List[str]:
        return sorted(self.tables, key=str.lower)

    def table(self, name: str) -> TableDef:
        for k, v in self.tables.items():
            if k.lower() == name.lower():
                return v
        raise KeyError("table %r not found in %s" % (name, self.path))

    # -- rows ------------------------------------------------------------
    def rows(self, name: str) -> Iterator[Dict[str, Any]]:
        """Yield every row of table *name* as a ``{column: value}`` dict."""
        return self._iter_rows(self.table(name))

    def _iter_rows(self, tdef: TableDef) -> Iterator[Dict[str, Any]]:
        for pnum in self._data_pages(tdef):
            pg = self.page(pnum)
            nrows = _u16(pg, 12)
            for r in range(nrows):
                start, end, raw = self._row_bounds(pg, r)
                if raw & _ROW_DELETED:
                    continue
                if raw & _ROW_OVERFLOW:
                    if end - start < 4:
                        continue
                    # row pointer: 1 byte row number + 3 byte page number
                    rowdata = self._read_row_ptr(_u32(pg, start))
                else:
                    rowdata = pg[start:end]
                if len(rowdata) < 2:
                    continue
                yield self._crack_row(tdef, rowdata)

    def _crack_row(self, tdef: TableDef, row: bytes) -> Dict[str, Any]:
        n = len(row)
        row_cols = _u16(row, 0)
        mask_sz = (row_cols + 7) // 8
        null_mask = row[n - mask_sz:] if mask_sz else b""
        var_offsets: List[int] = []
        row_var_cols = 0
        if tdef.num_var_cols > 0 and n >= mask_sz + 2:
            vpos = n - mask_sz - 2
            row_var_cols = _u16(row, vpos)
            for i in range(row_var_cols + 1):
                var_offsets.append(_u16(row, vpos - 2 - 2 * i))
        out: Dict[str, Any] = {}
        for col in tdef.columns:
            cn = col.col_num
            present = cn < row_cols
            notnull = present and bool(null_mask[cn // 8] & (1 << (cn % 8)))
            if col.type == T_BOOL:
                out[col.name] = notnull
                continue
            if not notnull:
                out[col.name] = None
                continue
            if col.is_fixed:
                size = _FIXED_SIZES.get(col.type, col.length)
                o = 2 + col.fixed_offset
                raw = row[o:o + size]
            else:
                vi = col.var_index
                if vi >= row_var_cols:
                    out[col.name] = None
                    continue
                raw = row[var_offsets[vi]:var_offsets[vi + 1]]
            out[col.name] = self._convert(col, raw)
        return out

    def _read_lval(self, raw: bytes) -> bytes:
        if len(raw) < 12:
            return b""
        hdr = _u32(raw, 0)
        length = hdr & 0x3FFFFFFF
        if hdr & 0x80000000:  # inline
            return raw[12:12 + length]
        ptr = _u32(raw, 4)
        if hdr & 0x40000000:  # single LVAL page
            return self._read_row_ptr(ptr)[:length]
        data = bytearray()
        guard = 0
        while ptr and len(data) < length:
            chunk = self._read_row_ptr(ptr)
            ptr = _u32(chunk, 0)
            data += chunk[4:]
            guard += 1
            if guard > 100000:
                raise Jet4Error("LVAL chain loop")
        return bytes(data[:length])

    def _convert(self, col: Column, raw: bytes) -> Any:
        t = col.type
        try:
            if t == T_BYTE:
                return raw[0]
            if t == T_INT:
                return struct.unpack("<h", raw[:2])[0]
            if t == T_LONG:
                return struct.unpack("<i", raw[:4])[0]
            if t == T_COMPLEX:
                return struct.unpack("<i", raw[:4])[0]
            if t == T_MONEY:
                return Decimal(struct.unpack("<q", raw[:8])[0]) / Decimal(10000)
            if t == T_FLOAT:
                return struct.unpack("<f", raw[:4])[0]
            if t == T_DOUBLE:
                return struct.unpack("<d", raw[:8])[0]
            if t == T_DATETIME:
                return ole_date(struct.unpack("<d", raw[:8])[0])
            if t == T_GUID:
                return "{%s}" % str(uuid.UUID(bytes_le=bytes(raw[:16]))).upper()
            if t == T_NUMERIC:
                scale = raw[1] if len(raw) > 1 else 0
                neg = raw[0] & 0x80
                # 16 byte magnitude stored as four little endian 32 bit words,
                # most significant word first
                mag = 0
                for k in range(4):
                    mag = (mag << 32) | _u32(raw, 1 + 4 * k)
                val = Decimal(mag).scaleb(-scale)
                return -val if neg else val
            if t == T_TEXT:
                return decode_text(raw)
            if t == T_BINARY:
                return bytes(raw)
            if t == T_MEMO:
                return decode_text(self._read_lval(raw))
            if t == T_OLE:
                return self._read_lval(raw)
        except (struct.error, IndexError):
            return None
        return bytes(raw)


def float32_clean(value: Optional[float]) -> Optional[float]:
    """Return the shortest decimal float equal to a single precision value
    (e.g. 74.66999816894531 -> 74.67)."""
    if value is None:
        return None
    for digits in range(6, 10):
        cand = float("%.*g" % (digits, value))
        if struct.pack("<f", cand) == struct.pack("<f", value):
            return cand
    return value
