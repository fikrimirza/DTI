# DTI – AEP2cABR

**AEP2cABR** adalah penulisan ulang program Bio-logic **AEP2ASC 1.6.0** agar
data Bio-logic / Natus Navigator Pro AEP (`BLPatients.mdb` + `EPWinData.mdb`)
dapat dipakai untuk analisis **cABR** (*complex/speech ABR*), mis. dengan
**IHS cABR Standalone** (`IHSPITCH.exe`, `IHS_Phaseogram.exe`) atau
**Brainstem Toolbox** (MATLAB).

* Membaca file `.mdb` langsung (Python murni) – **tidak perlu** driver ODBC
  Access, Microsoft Access, VB6 runtime, atau OCX lama.
* Ekspor ke **Neuroscan `.avg`** (format masukan Brainstem Toolbox / tool
  cABR IHS), teks 1 kolom + perintah `bt_txt2avg`, CSV, dan ASCII gaya
  AEP2ASC.
* Waveform dalam **µV** dengan sumbu waktu yang benar (pra-stimulus &
  koreksi *insert delay*), terverifikasi terhadap marked point Navigator.
* Gabung rekaman (**add** / **subtract**, mis. dua polaritas), konversi
  stimulus **WAV → AVG** (`da.wav`) untuk pitch tracking.
* GUI (alur sama seperti AEP2ASC) dan command line; opsi **anonim**.

Rincian analisis format dan program asli: [docs/ANALISIS_AEP2ASC.md](docs/ANALISIS_AEP2ASC.md).

## Instalasi

Butuh Python 3.8 atau lebih baru (Windows/macOS/Linux), tanpa paket tambahan.

```bat
:: Windows – dari folder repositori ini
AEP2cABR.bat                      & rem buka GUI
python -m aep2cabr --help         & rem command line
```

Opsional: `pip install .` lalu gunakan perintah `aep2cabr` / `aep2cabr-gui`.

## Pemakaian GUI

1. Jalankan `AEP2cABR.bat` (atau `python -m aep2cabr gui`).
2. **Lokasi database**: dipilih otomatis dari konfigurasi program AEP
   (`BLdbAppCfg.mdb`), atau pilih `<Lainnya...>` → folder berisi
   `BLPatients.mdb` dan `EPWinData.mdb`.
3. Pilih **Pasien** → **AEP Test** → satu/lebih **Record** (Ctrl/Shift).
   Centang *Hanya rekaman cABR* untuk menampilkan rekaman /da/ & BioMAP saja.
4. Pilih **Format** dan opsi, lalu **Tulis File...**:
   * *Neuroscan AVG* – untuk IHSPITCH / IHS_Phaseogram / Brainstem Toolbox.
   * *Teks 1 kolom* – untuk `bt_txt2avg` (file `.info.txt` berisi perintahnya).
   * *CSV* – waktu + semua bank (Excel, R, Python).
   * *ASCII AEP2ASC* – meniru output program lama (atur di menu *Setup*).
5. **Gabung: Add** (rata-rata berbobot jumlah sweep) atau **Gabung:
   Subtract** ((A−B)/2, tepat 2 rekaman) untuk rekaman berpolaritas
   berlawanan / blok berulang.
6. Menu **Alat → Stimulus WAV → AVG** untuk mengonversi `da.wav`
   (di PC Navigator: `C:\Program Files (x86)\Natus\AEP\da.wav`).

## Pemakaian command line

```bash
# daftar rekaman (nomor # dipakai untuk memilih)
python -m aep2cabr list --data "C:\p&ti\data" --cabr

# ekspor semua rekaman cABR ke .avg (satu file per bank)
python -m aep2cabr export --data "C:\p&ti\data" --cabr -f avg -o hasil_cabr

# rekaman tertentu, bank 10 (added), baseline pra-stimulus, anonim
python -m aep2cabr export --data D:\backup -r 26 27 --bank 10 --baseline prestim --anonymize -o hasil

# rata-rata dua blok /da/ telinga kiri, dan selisih dua polaritas
python -m aep2cabr combine --data D:\backup -r 26 27 --mode add -o kiri_add.avg
python -m aep2cabr combine --data D:\backup -r 30 31 --mode subtract -o tfs.avg

# stimulus untuk pitch tracking (opsional resample ke fs respons)
python -m aep2cabr wav2avg da.wav da.avg
python -m aep2cabr wav2avg da.wav da_6857.avg --rate 6857

# ASCII seperti AEP2ASC (tab, kolom, header) – di-append bila file sudah ada
python -m aep2cabr export --data D:\backup --test EP00001 --patient 12345678 -f ascii -o AEPASCII.txt --append

# cek file .avg
python -m aep2cabr avginfo hasil_cabr\*.avg
```

Pilihan penting:

| Opsi | Arti |
| --- | --- |
| `--bank 1 2 10 11` | 1 kondensasi, 2 rarefaksi, 10 added (A+B), 11 subtracted (A−B). Default: semua bank yang tersimpan |
| `--baseline none\|prestim\|mean` | Default `none` = nilai mentah (seperti database); `prestim` = kurangi rata-rata pra-stimulus |
| `--no-insert-delay` | Waktu nol = trigger (tanpa koreksi 0,8 ms tabung ER-3). Default: dikoreksi, sama dengan tampilan Navigator |
| `--timebase hardware` | Sampling 48 kHz/k (mis. 6.857,14 Hz) alih-alih EpochTime/points (6.856,84 Hz) |
| `--multi-channel` | `.avg`: semua bank dalam satu file (channel = bank) |
| `--anonymize` | Tanpa nama, ID pasien, tanggal, teknisi di isi maupun nama file |

Setiap ekspor juga menulis `manifest.csv` (file, telinga, stimulus,
polaritas, intensitas, sweep, fs, jendela waktu).

## Alur ke tool cABR IHS / Brainstem Toolbox

1. Ekspor rekaman cABR ke `.avg` (bila ada 2 blok per telinga, gabungkan
   dengan **add**).
2. Konversi stimulus `da.wav` → `da.avg` (**wav2avg**).
3. Jalankan `IHSStandAloneCaller.exe` → *Run IHS_Pitch* → pilih `.avg`
   respons (dan stimulus `.avg`); *Run IHS_Phaseogram* → pilih dua `.avg`.
   Di Brainstem Toolbox gunakan `bt_gui` / `bt_ptgui` dengan file yang sama.

> Catatan: pembaca file di dalam IHSPITCH/IHS_Phaseogram terenkripsi
> (MATLAB Compiler), sehingga kompatibilitasnya diturunkan dari Brainstem
> Toolbox yang menjadi dasarnya ("Stimulus file must be in '.avg' format").
> Bila tool IHS menolak file, kirim satu file contoh yang bisa dibuka IHS
> agar format dapat disesuaikan.

## Hasil yang sudah diverifikasi

* Pembaca `.mdb` cocok 100% dengan Jackcess untuk seluruh 30 tabel kedua
  database contoh (termasuk blob OLE, memo, GUID, tanggal).
* 2.270 waveform dari 674 rekaman terekspor tanpa error di semua format.
* Skala µV dan sumbu waktu cocok persis dengan 716 marked point Navigator;
  jendela BioMAP −15,8…69,45 ms sesuai literatur BioMARK.
* `.avg` dibaca balik identik (selisih ≤ 3·10⁻⁹ µV).

## Pengujian

```bash
python -m unittest discover -s tests
```

Tes memakai database **sintetis** di `tests/fixtures/` (pasien fiktif,
gelombang sinus), dibuat oleh `tests/fixtures/MakeFixtures.java` (Jackcess).
Database pasien asli tidak disimpan di repositori ini.

## Struktur kode

| File | Isi |
| --- | --- |
| `aep2cabr/jet4.py` | Pembaca Microsoft Access Jet4 (read-only, Python murni) |
| `aep2cabr/biologic.py` | Model pasien/tes/rekaman, dekode blob waveform, µV & waktu |
| `aep2cabr/codes.py` | Tabel kode → teks (dari AEP2ASC) |
| `aep2cabr/export.py` | Ekspor rekaman, baseline, gabung add/subtract |
| `aep2cabr/neuroscan.py` | Writer/reader Neuroscan `.avg` |
| `aep2cabr/textout.py` | Teks 1 kolom, CSV, `.info.txt` + `bt_txt2avg` |
| `aep2cabr/ascii_aep2asc.py` | Output ASCII gaya AEP2ASC |
| `aep2cabr/stimulus.py` | WAV → AVG (+ resampling) |
| `aep2cabr/cli.py`, `gui.py` | Command line dan GUI tkinter |
