"""Graphical interface (tkinter) - follows the AEP2ASC workflow:

database location -> Patients -> AEP Tests -> AEP Test Records -> write file.
"""

from __future__ import annotations

import json
import os
import traceback
from dataclasses import asdict

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
except ImportError:  # pragma: no cover - Python without Tk
    tk = None

from . import __version__
from .ascii_aep2asc import AsciiOptions
from .biologic import BiologicDatabase, configured_data_paths
from .cli import export_records, ordered_records, parse_numbers, write_export_set
from .export import BASELINE_MODES, combine_records
from . import stimulus

SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".aep2cabr.json")
OTHER = "<Lainnya...>"
FORMAT_CHOICES = [
    ("Neuroscan AVG (cABR: Brainstem Toolbox / IHS)", "avg"),
    ("Teks 1 kolom (bt_txt2avg)", "txt"),
    ("CSV (waktu + gelombang)", "csv"),
    ("ASCII AEP2ASC", "ascii"),
]
COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b"]


def _load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_settings(data):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
    except OSError:
        pass


class App(tk.Tk if tk else object):
    def __init__(self):
        super().__init__()
        self.title("AEP2cABR %s - Bio-logic AEP ke cABR" % __version__)
        self.geometry("1180x780")
        self.minsize(900, 600)
        self.settings = _load_settings()
        self.ascii_opts = AsciiOptions(**{k: v for k, v in self.settings.get("ascii", {}).items()
                                          if k in AsciiOptions.__dataclass_fields__})
        self.db = None
        self.ordered = []
        self.numbers = {}
        self._build_menu()
        self._build_widgets()
        self._fill_locations()

    # -- layout ------------------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Buka folder database...", command=self.open_folder)
        f.add_command(label="Buka EPWinData.mdb...", command=self.open_file)
        f.add_separator()
        f.add_command(label="Keluar", command=self.destroy)
        m.add_cascade(label="File", menu=f)
        s = tk.Menu(m, tearoff=0)
        s.add_command(label="Opsi output ASCII...", command=self.setup_dialog)
        m.add_cascade(label="Setup", menu=s)
        t = tk.Menu(m, tearoff=0)
        t.add_command(label="Stimulus WAV -> AVG...", command=self.wav2avg)
        m.add_cascade(label="Alat", menu=t)
        h = tk.Menu(m, tearoff=0)
        h.add_command(label="Tentang", command=lambda: messagebox.showinfo(
            "Tentang", "AEP2cABR %s\nPenulisan ulang AEP2ASC 1.6.0 (Bio-logic)\n"
                       "Ekspor BLPatients.mdb + EPWinData.mdb ke format cABR." % __version__))
        m.add_cascade(label="Bantuan", menu=h)
        self.config(menu=m)

    def _tree(self, parent, cols, widths, select="browse", height=6):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=[c for c, _ in cols], show="headings",
                            selectmode=select, height=height)
        for (c, title), w in zip(cols, widths):
            tree.heading(c, text=title)
            tree.column(c, width=w, stretch=True, anchor="w")
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return frame, tree

    def _build_widgets(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Lokasi database:").pack(side="left")
        self.loc = ttk.Combobox(top, width=70, state="readonly")
        self.loc.pack(side="left", padx=6)
        self.loc.bind("<<ComboboxSelected>>", self._location_selected)
        self.only_cabr = tk.BooleanVar(value=self.settings.get("only_cabr", False))
        ttk.Checkbutton(top, text="Hanya rekaman cABR (speech/BioMAP)", variable=self.only_cabr,
                        command=self._refresh_records).pack(side="left", padx=10)

        self.status = tk.StringVar(value="Pilih lokasi database.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=3).pack(fill="x", side="bottom")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=1)
        self._body = body
        self.after(150, lambda: body.sashpos(0, int(max(self.winfo_width(), 900) * 0.56)))

        ttk.Label(left, text="Pasien").pack(anchor="w")
        f, self.t_pat = self._tree(left, [("pid", "Patient ID"), ("last", "Last Name"),
                                          ("first", "First Name"), ("birth", "Birth Date")],
                                   [110, 180, 160, 100], height=5)
        f.pack(fill="both", expand=True)
        self.t_pat.bind("<<TreeviewSelect>>", lambda e: self._refresh_tests())

        ttk.Label(left, text="AEP Tests").pack(anchor="w")
        f, self.t_test = self._tree(left, [("test", "Test ID"), ("date", "Test Date"),
                                           ("tech", "Technician"), ("n", "Records")],
                                    [90, 160, 200, 70], height=3)
        f.pack(fill="both", expand=False)
        self.t_test.bind("<<TreeviewSelect>>", lambda e: self._refresh_records())

        ttk.Label(left, text="AEP Test Records (Ctrl/Shift untuk pilih banyak)").pack(anchor="w")
        f, self.t_rec = self._tree(left, [("no", "#"), ("r", "Rec"), ("type", "Test Type"),
                                          ("ear", "Ear"), ("stim", "Stimulus"),
                                          ("pol", "Polarity"), ("int", "Intensity"),
                                          ("rate", "Rate"), ("epoch", "Epoch ms"),
                                          ("pts", "Pts"), ("banks", "Banks"),
                                          ("sw", "Sweeps"), ("cabr", "cABR")],
                                   [45, 40, 80, 50, 150, 90, 85, 55, 65, 45, 75, 80, 45],
                                   select="extended", height=10)
        f.pack(fill="both", expand=True)
        self.t_rec.bind("<<TreeviewSelect>>", lambda e: self._plot())

        # plot + options on the right
        ttk.Label(right, text="Tampilan gelombang").pack(anchor="w")
        self.canvas = tk.Canvas(right, background="white", height=300, highlightthickness=1,
                                highlightbackground="#bbb")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._plot())

        opt = ttk.LabelFrame(right, text="Opsi ekspor", padding=6)
        opt.pack(fill="x", pady=6)
        self.fmt = ttk.Combobox(opt, state="readonly", width=44,
                                values=[n for n, _ in FORMAT_CHOICES])
        self.fmt.current(0)
        ttk.Label(opt, text="Format:").grid(row=0, column=0, sticky="w")
        self.fmt.grid(row=0, column=1, columnspan=3, sticky="we", pady=2)
        ttk.Label(opt, text="Bank:").grid(row=1, column=0, sticky="w")
        self.bank = ttk.Entry(opt, width=12)
        self.bank.insert(0, self.settings.get("bank", ""))
        self.bank.grid(row=1, column=1, sticky="w")
        ttk.Label(opt, text="kosong = semua  (1 cond, 2 rare, 10 add, 11 sub)").grid(
            row=1, column=2, columnspan=2, sticky="w", padx=4)
        ttk.Label(opt, text="Baseline:").grid(row=2, column=0, sticky="w")
        self.baseline = ttk.Combobox(opt, state="readonly", width=10, values=list(BASELINE_MODES))
        self.baseline.set(self.settings.get("baseline", "none"))
        self.baseline.grid(row=2, column=1, sticky="w")
        self.insert_delay = tk.BooleanVar(value=self.settings.get("insert_delay", True))
        ttk.Checkbutton(opt, text="Koreksi insert delay", variable=self.insert_delay).grid(
            row=2, column=2, sticky="w")
        self.anon = tk.BooleanVar(value=self.settings.get("anonymize", False))
        ttk.Checkbutton(opt, text="Anonim (tanpa nama/ID/tanggal)", variable=self.anon).grid(
            row=3, column=2, columnspan=2, sticky="w")
        self.multi = tk.BooleanVar(value=self.settings.get("multi_channel", False))
        ttk.Checkbutton(opt, text="AVG: semua bank dalam satu file", variable=self.multi).grid(
            row=4, column=2, columnspan=2, sticky="w")
        opt.columnconfigure(3, weight=1)

        btn = ttk.Frame(right)
        btn.pack(fill="x")
        ttk.Button(btn, text="Tulis File...", command=self.write_files).pack(side="left")
        ttk.Button(btn, text="Gabung: Add", command=lambda: self.combine("add")).pack(side="left", padx=4)
        ttk.Button(btn, text="Gabung: Subtract", command=lambda: self.combine("subtract")).pack(side="left")
        ttk.Button(btn, text="Tutup", command=self.destroy).pack(side="right")


    # -- database ------------------------------------------------------------
    def _fill_locations(self):
        locs = []
        try:
            default, listed = configured_data_paths()
        except Exception:  # config file unreadable: carry on without it
            default, listed = None, []
        for _, p in listed:
            if p not in locs:
                locs.append(p)
        if default and default not in locs:
            locs.insert(0, default)
        last = self.settings.get("last_location")
        if last and last not in locs:
            locs.insert(0, last)
        self.loc["values"] = locs + [OTHER]
        if locs:
            self.loc.set(locs[0])
            self.after(50, lambda: self.load(locs[0]))

    def _location_selected(self, _e=None):
        v = self.loc.get()
        if v == OTHER:
            self.open_folder()
        else:
            self.load(v)

    def open_folder(self):
        d = filedialog.askdirectory(title="Folder berisi BLPatients.mdb dan EPWinData.mdb")
        if d:
            self.load(d)

    def open_file(self):
        f = filedialog.askopenfilename(title="Pilih EPWinData.mdb",
                                       filetypes=[("Bio-logic AEP Files", "EPWinData.mdb"),
                                                  ("Access database", "*.mdb"), ("All", "*.*")])
        if f:
            self.load(f)

    def load(self, path):
        self.status.set("Membuka %s ..." % path)
        self.update_idletasks()
        try:
            if os.path.isdir(path):
                db = BiologicDatabase.from_folder(path)
            else:
                db = BiologicDatabase(path)
        except Exception as e:
            messagebox.showerror("Gagal membuka database", "%s\n\n%s" % (path, e))
            self.status.set("Gagal membuka %s" % path)
            return
        self.db = db
        self.ordered = ordered_records(db)
        self.numbers = {id(r): i for i, r in enumerate(self.ordered, 1)}
        self.settings["last_location"] = path
        vals = list(self.loc["values"])
        if path not in vals:
            self.loc["values"] = [path] + vals
        self.loc.set(path)
        self._refresh_patients()
        warn = sum(len(r.warnings) for r in db.records)
        self.status.set("%d pasien, %d rekaman%s  -  %s" % (
            len(db.patient_list()), len(db.records),
            (", %d peringatan" % warn) if warn else "", db.epwin_path))

    def _refresh_patients(self):
        self.t_pat.delete(*self.t_pat.get_children())
        self.t_test.delete(*self.t_test.get_children())
        self.t_rec.delete(*self.t_rec.get_children())
        if not self.db:
            return
        first = None
        for p in self.db.patient_list():
            bd = p.birthdate.strftime("%Y-%m-%d") if hasattr(p.birthdate, "strftime") else ""
            iid = self.t_pat.insert("", "end", iid=p.blscid,
                                    values=(p.patient_id, p.last_name, p.first_name, bd))
            first = first or iid
        if first:
            self.t_pat.selection_set(first)
            self.t_pat.focus(first)

    def _refresh_tests(self):
        self.t_test.delete(*self.t_test.get_children())
        self.t_rec.delete(*self.t_rec.get_children())
        sel = self.t_pat.selection()
        if not sel or not self.db:
            return
        first = None
        for t in self.db.tests_for(sel[0]):
            n = len(self.db.records_for(sel[0], t.test_id))
            d = t.test_date.strftime("%Y-%m-%d %H:%M") if hasattr(t.test_date, "strftime") else ""
            iid = self.t_test.insert("", "end", iid="%s|%s" % (sel[0], t.test_id),
                                     values=(t.test_id, d, t.technician, n))
            first = first or iid
        if first:
            self.t_test.selection_set(first)

    def _refresh_records(self):
        self.t_rec.delete(*self.t_rec.get_children())
        sel = self.t_test.selection()
        if not sel or not self.db:
            return
        blscid, test_id = sel[0].split("|", 1)
        recs = sorted(self.db.records_for(blscid, test_id), key=lambda r: r.index)
        if self.only_cabr.get():
            recs = [r for r in recs if r.is_speech]
        for r in recs:
            self.t_rec.insert("", "end", iid=str(self.numbers[id(r)]), values=(
                self.numbers[id(r)], r.index, r.test_type_name, r.ear, r.stimulus,
                r.polarity, r.intensity, r.rate, "%g" % r.epoch_ms, r.n_points,
                ",".join(map(str, r.banks)),
                ",".join(str(w.averages or "") for w in r.waveforms),
                "ya" if r.is_speech else ""))
        self._plot()

    def selected_records(self):
        nums = sorted(int(i) for i in self.t_rec.selection())
        return [(n, self.ordered[n - 1]) for n in nums]

    # -- plot ------------------------------------------------------------------
    def _plot(self):
        c = self.canvas
        c.delete("all")
        sel = self.selected_records()
        if not sel:
            c.create_text(10, 10, anchor="nw", text="Pilih rekaman untuk melihat gelombang",
                          fill="#666")
            return
        n, rec = sel[0]
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 150)
        ml, mr, mt, mb = 50, 10, 40, 28
        t = rec.times_ms(self.insert_delay.get())
        waves = [(w, w.uv) for w in rec.waveforms]
        if not waves or not t:
            return
        ymin = min(min(v) for _, v in waves)
        ymax = max(max(v) for _, v in waves)
        if ymax - ymin < 1e-9:
            ymax, ymin = ymax + 1, ymin - 1
        pad = (ymax - ymin) * 0.05
        ymin, ymax = ymin - pad, ymax + pad
        x0, x1 = t[0], t[-1]

        def X(v):
            return ml + (v - x0) / (x1 - x0) * (W - ml - mr)

        def Y(v):
            return mt + (ymax - v) / (ymax - ymin) * (H - mt - mb)

        c.create_rectangle(ml, mt, W - mr, H - mb, outline="#999")
        if x0 < 0 < x1:
            c.create_line(X(0), mt, X(0), H - mb, fill="#bbb", dash=(3, 3))
        if ymin < 0 < ymax:
            c.create_line(ml, Y(0), W - mr, Y(0), fill="#ddd")
        for v in (x0, (x0 + x1) / 2, x1):
            c.create_text(X(v), H - mb + 4, anchor="n", text="%.1f" % v, fill="#444")
        c.create_text((ml + W - mr) / 2, H - 4, anchor="s", text="ms", fill="#444")
        for v in (ymin, ymax):
            c.create_text(ml - 4, Y(v), anchor="e", text="%.2f" % v, fill="#444")
        c.create_text(4, 20, anchor="nw", text="uV", fill="#444")
        legend = []
        for k, (w, v) in enumerate(waves):
            col = COLORS[k % len(COLORS)]
            pts = []
            for ti, vi in zip(t, v):
                pts.extend((X(ti), Y(vi)))
            if len(pts) >= 4:
                c.create_line(*pts, fill=col, width=1)
            legend.append((col, "B%d %s" % (w.bank, w.bank_name)))
        for m in rec.marked_points:
            w = rec.waveform(m.channel, m.bank)
            if w is None or m.latency_ms is None:
                continue
            idx = min(range(len(t)), key=lambda i: abs(t[i] - m.latency_ms))
            vx, vy = X(t[idx]), Y(w.uv[idx])
            c.create_text(vx, vy - 3, anchor="s", text=m.label, fill="#000")
        c.create_text(ml, 3, anchor="nw", fill="#222",
                      text="#%d  %s" % (n, rec.short_name()))
        xx = ml
        for col, txt in legend:
            item = c.create_text(xx, 20, anchor="nw", text=txt, fill=col)
            xx = c.bbox(item)[2] + 12

    # -- actions ---------------------------------------------------------------
    def _export_options(self):
        fmt = dict(FORMAT_CHOICES)[self.fmt.get()]
        banks = parse_numbers([self.bank.get()]) if self.bank.get().strip() else None
        self.settings.update(bank=self.bank.get(), baseline=self.baseline.get(),
                             insert_delay=self.insert_delay.get(), anonymize=self.anon.get(),
                             multi_channel=self.multi.get(), only_cabr=self.only_cabr.get())
        _save_settings(self.settings)
        return fmt, banks

    def write_files(self):
        sel = self.selected_records()
        if not sel:
            messagebox.showwarning("Tidak ada data dipilih",
                                   "Pilih satu atau lebih rekaman di tabel AEP Test Records.")
            return
        try:
            fmt, banks = self._export_options()
        except ValueError:
            messagebox.showerror("Bank", "Isi bank dengan angka, mis. 1,2 atau 10")
            return
        append = False
        if fmt == "ascii":
            out = filedialog.asksaveasfilename(title="File ASCII", initialfile="AEPASCII.txt",
                                               defaultextension=".txt",
                                               filetypes=[("Text Files", "*.txt")],
                                               confirmoverwrite=False)
            if not out:
                return
            if os.path.exists(out):
                ans = messagebox.askyesnocancel(
                    "File sudah ada", "File sudah ada.\nYa = tambahkan (append, seperti AEP2ASC)\n"
                                      "Tidak = timpa file")
                if ans is None:
                    return
                append = ans
        else:
            out = filedialog.askdirectory(title="Folder tujuan ekspor")
            if not out:
                return
        log = []
        try:
            files = export_records([r for _, r in sel], [n for n, _ in sel], fmt, out,
                                   banks=banks, baseline=self.baseline.get(),
                                   insert_delay_correction=self.insert_delay.get(),
                                   anonymize=self.anon.get(), multi_channel=self.multi.get(),
                                   ascii_opts=self.ascii_opts, append=append, log=log.append)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Gagal menulis file", str(e))
            return
        skipped = [l for l in log if l.startswith("skip")]
        msg = "Berhasil: %d file dari %d rekaman.\n%s" % (len(files), len(sel), out)
        if skipped:
            msg += "\n\nDilewati:\n" + "\n".join(skipped[:10])
        self.status.set("%d file ditulis ke %s" % (len(files), out))
        messagebox.showinfo("Selesai", msg)

    def combine(self, mode):
        sel = self.selected_records()
        if len(sel) < (2 if mode == "subtract" else 1) or (mode == "subtract" and len(sel) != 2):
            messagebox.showwarning("Gabung", "Add: pilih 1 rekaman atau lebih.\n"
                                             "Subtract: pilih tepat 2 rekaman.")
            return
        try:
            _fmt, banks = self._export_options()
            es = combine_records([r for _, r in sel], mode=mode,
                                 bank=banks[0] if banks else None,
                                 baseline=self.baseline.get(),
                                 insert_delay_correction=self.insert_delay.get(),
                                 anonymize=self.anon.get())
        except Exception as e:
            messagebox.showerror("Gabung", str(e))
            return
        out = filedialog.asksaveasfilename(
            title="Simpan hasil %s" % mode, initialfile=es.name + ".avg", defaultextension=".avg",
            filetypes=[("Neuroscan AVG", "*.avg"), ("Teks 1 kolom", "*.txt"), ("CSV", "*.csv")])
        if not out:
            return
        try:
            write_export_set(es, out)
        except Exception as e:
            messagebox.showerror("Gagal menulis file", str(e))
            return
        self.status.set("%s dari %d rekaman -> %s" % (mode, len(sel), out))

    def wav2avg(self):
        src = filedialog.askopenfilename(title="File stimulus WAV (mis. da.wav)",
                                         filetypes=[("WAV", "*.wav"), ("All", "*.*")])
        if not src:
            return
        rate = simpledialog.askfloat(
            "Sample rate", "Resample ke (Hz)?\nKosongkan/Cancel = tetap sample rate asli.",
            parent=self, minvalue=100, maxvalue=200000)
        dst = filedialog.asksaveasfilename(title="Simpan stimulus .avg",
                                           initialfile=os.path.splitext(os.path.basename(src))[0] + ".avg",
                                           defaultextension=".avg")
        if not dst:
            return
        try:
            es = stimulus.wav2avg(src, dst, rate=rate)
        except Exception as e:
            messagebox.showerror("WAV -> AVG", str(e))
            return
        self.status.set("%s -> %s (%d titik, %.0f Hz)" % (src, dst, es.n_points, es.sample_rate_hz))

    def setup_dialog(self):
        d = tk.Toplevel(self)
        d.title("Setup output ASCII (AEP2ASC)")
        d.transient(self)
        nb = ttk.Notebook(d)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        o1, o2 = ttk.Frame(nb, padding=8), ttk.Frame(nb, padding=8)
        nb.add(o1, text="Output Options")
        nb.add(o2, text="Output Format")
        cur = asdict(self.ascii_opts)
        vars_ = {}
        for frame, items in ((o1, [("patient_info", "Patient information"),
                                   ("record_info", "Record information"),
                                   ("stimulus_info", "Stimulus information"),
                                   ("amplifier_info", "Amplifier information"),
                                   ("mp_latency", "Marked point latency"),
                                   ("mp_amplitude", "Marked point amplitude"),
                                   ("wave_info", "Wave information")]),
                             (o2, [("tab_delimited", "Tab delimited (tidak = koma)"),
                                   ("columns", "Gelombang dalam kolom (tidak = baris)"),
                                   ("quotes", "Pakai tanda kutip"),
                                   ("header", "Baris header")])):
            for key, text in items:
                vars_[key] = tk.BooleanVar(value=cur[key])
                ttk.Checkbutton(frame, text=text, variable=vars_[key]).pack(anchor="w")

        def apply(close):
            for k, v in vars_.items():
                setattr(self.ascii_opts, k, v.get())
            self.settings["ascii"] = {k: getattr(self.ascii_opts, k) for k in vars_}
            _save_settings(self.settings)
            if close:
                d.destroy()

        b = ttk.Frame(d, padding=6)
        b.pack(fill="x")
        ttk.Button(b, text="OK", command=lambda: apply(True)).pack(side="right")
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="right", padx=4)
        ttk.Button(b, text="Apply", command=lambda: apply(False)).pack(side="right")


def run():
    if tk is None:
        raise SystemExit("tkinter tidak tersedia di Python ini; gunakan perintah CLI "
                         "(python -m aep2cabr --help)")
    app = App()
    app.mainloop()
    return 0
