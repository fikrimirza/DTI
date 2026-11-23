# Analisis AEP2ASC 1.6.0 dan format database Bio-logic AEP

Dokumen ini merangkum hasil analisis yang menjadi dasar penulisan ulang
AEP2ASC menjadi **aep2cabr**. Semua angka di bawah diverifikasi terhadap
database Navigator Pro asli (`BLPatients.mdb` 33 pasien, `EPWinData.mdb`
674 rekaman / 2.270 waveform); data pasien itu sendiri **tidak** disimpan
di repositori ini.

## 1. Program asli: AEP2ASC 1.6.0

| Hal | Temuan |
| --- | --- |
| Pembuat | Bio-logic Systems Corp. (Ron Rolfsen), 2004–2008 |
| Teknologi | Visual Basic 6, ADO lewat ODBC *Microsoft Access Driver (\*.mdb)*, kontrol ComponentOne TrueDBGrid |
| Konfigurasi | `C:\Program Files\Bio-logic Systems Corp\AEP\BLdbAppCfg.mdb` (tabel `Defaults.OpenPath`, `DataPaths.PathName/FilePath`), data default di `C:\p&ti\data` |
| Opsi | Registry `HKLM\Software\Bio-logic Systems Corp\AEPTools`: OutputPatientInfo, OutputRecordInfo, OutputStimulusInfo, OutputAmplifierInfo, OutputMPLatencyInfo, OutputMPAmplitudeInfo, OutputWaveInfo, OutputFormatTab, OutputFormatCol, OutputFormatQuotes, OutputFormatHeader |
| Query | `Select * From Patients ORDER by LASTNAME`, `Select * From Tests ... TestType = 'EP'`, `Select * From Records ORDER by StopTime`, lalu `EPData`, `Amplifiers`, tabel stimulus (`AEPStim`, `P300Stim`, `AltEarStim`, `EXTStim`, `EXTP300Stim`, `CalculatedStim`, `SABRStim`, `BioMAPStim`, `VEMPStim`), `Labels`, `MarkedPoints` |
| Output | Satu file teks ASCII (default `AEPASCII.txt`), di-*append* bila sudah ada |

Keterbatasan yang membuat AEP2ASC tidak cocok untuk analisis cABR:

* Butuh Windows 32-bit + driver ODBC Access + OCX lama (TrueDBGrid, dll.)
  yang sering gagal di Windows 64-bit modern.
* Output hanya ASCII bebas; tool cABR (Brainstem Toolbox, IHS cABR
  stand-alone) membutuhkan **Neuroscan `.avg`** dengan sampling rate dan
  waktu pra-stimulus yang benar.
* Tidak ada penggabungan rekaman (polaritas berlawanan → *added* /
  *subtracted*), dan tidak ada konversi stimulus WAV → AVG.

## 2. Struktur database

### BLPatients.mdb (PTI)

* `Patients` – `BLSCID` (GUID, kunci), `PatientID`, `LastName`,
  `FirstName`, `Birthdate`, `Sex`, …
* `Tests` – `BLSCID` + `TestID` (mis. `EP00001`), `TestType='EP'`,
  `TestDate`, `Technician`, …

### EPWinData.mdb

* `Records` – satu baris per rekaman: `BLSCID`, `TestID`, `RecordID`
  (GUID), `TestType`, `StartTime`, `StopTime`, `NumberofChannels`,
  `EpochTime` (ms), `NumberofPoints`, `CollectionRate` (kHz, dibulatkan),
  `PrePostPoints`, `BlockedPoints`, `ADBits`, **`Data` (OLE, waveform)**,
  `SoftwareVersion`.
* `EPData` – per channel/bank: `Averages`, `ArtifactsRejected`.
* `Amplifiers` – per channel: `AmplifierGain`, `LowFilter`, `HighFilter`,
  `NotchFilter`, elektroda.
* Tabel stimulus per jenis tes (lihat di atas): `Transducer`, `StimEar`,
  `StimPolarity`, `StimIntensity`, `IntensityScaleName`, `StimRateValue`,
  `StimType`, `StimFrequency`, `CustomStimFileName`, `InsertDelay`, masking.
* `MarkedPoints` (+ `Labels`) – titik puncak yang ditandai (I, III, V, …)
  beserta latensi (ms) dan amplitudo (µV).

`Records.BLSCID/TestID` → `Tests` → `Patients`. Pada data contoh, 3 rekaman
BioMAP (data demo bawaan software) tidak punya pasien di `BLPatients.mdb`;
aep2cabr tetap menampilkannya sebagai "(not in BLPatients)".

## 3. Format blob waveform `Records.Data`

```
int32  header            (selalu 10 pada data ini)
ulangi untuk setiap channel/bank:
  int32  channel
  int32  bank
  int32  n               (= NumberofPoints)
  int32  sampel[n]       (nilai A/D yang sudah dirata-rata)
```

Little-endian. Contoh: 4 bank × 256 titik → 4 + 4×(12+1024) = 4.148 byte.

Bank: 1 = kondensasi, 2 = rarefaksi, 10 = *added* (A+B), 11 = *subtracted*
(A−B) untuk polaritas alternating; rekaman satu polaritas hanya menyimpan
bank 1; BioMAP menyimpan bank 10. (P300: 1 = frequent, 2 = infrequent.)

## 4. Konversi ke µV dan sumbu waktu (terverifikasi)

**Amplitudo**

```
µV = A/D × (10 V / 2^ADBits) / AmplifierGain × 10^6
   = A/D × 0,0015259 µV   (16 bit, gain 100.000)
```

Verifikasi: pada 48 waveform, `MarkedAmplitude` yang disimpan Navigator
sama persis dengan `A/D × 0,0015259` (relatif terhadap baseline tampilan
Navigator). Navigator mengurangi offset DC saat menampilkan; aep2cabr
mengekspor nilai mentah (default) dengan opsi `--baseline prestim|mean`.

**Waktu**

```
t[i] (ms) = PrePostPoints/48 + i × EpochTime/NumberofPoints − InsertDelay
```

* `PrePostPoints` dalam satuan 1/48 ms (jam dasar 48 kHz): −749 → −15,604
  ms (= 107 sampel @ 6.857 Hz), −720 → −15,0 ms (180 sampel @ 12 kHz),
  −965 → −20,104 ms (193 sampel @ 9.600 Hz) — semuanya bilangan bulat
  sampel.
* Navigator menampilkan latensi yang sudah dikoreksi *insert delay* ER-3
  (0,8 ms). Dengan rumus di atas, **716/716** marked point modul AEP &
  Calculated jatuh tepat pada sampel (selisih < 10⁻⁴ ms); BioMAP cocok dalam
  pembulatan 2 desimal.
* Hasilnya untuk BioMAP: jendela −15,8 … 69,45 ms — sama dengan jendela
  BioMARK standar di literatur (−15,8 … 69,5 ms).
* Sampling rate = `NumberofPoints/EpochTime` (cara Navigator; mis. 6.856,8
  Hz). Opsi `--timebase hardware` memakai 48 kHz/k (mis. 6.857,1 Hz).

## 5. Pemetaan kode (dipakai ulang dari AEP2ASC)

| Field | Kode → teks | Status |
| --- | --- | --- |
| TestType | 1 AEP, 2 P300, 3 Alternate Ear, 4 External Stimulus, 5 External Stimulus P300, 6 Calculated, 7 Self Test, 8 Stacked ABR, 9 BioMAP, 10 VEMP | 1/4/6/9 terkonfirmasi dari tabel stimulus |
| Transducer | 1 Headphone, 2 Insert ER3, 3 Bone, 4 Speaker, 5 Insert ER2, 6 OAE Probe, 7 Ear Muffin, 8 Insert BB | 2 terkonfirmasi (InsertDelay 0,8 ms) |
| StimType | 1 Click, 2 Filtered Click, 3 Single Sine, 4 Tone Burst, 5 Masked Click, 6 Custom (.wav) | 1/4/6 terkonfirmasi |
| StimPolarity | 1 Condensation, 2 Rarefaction, 3 Alternating, 4 Differential | 3 terkonfirmasi (4 bank) |
| IntensityScaleName | 0 dB SPL, 1 dB HL, 2 dB nHL | cocok dengan protokol klinis |
| StimEar | 1 Left, 2 Right, 3 Both, 4 Alternating | **belum terverifikasi** – kode mentah selalu ikut diekspor (`EarCode`) |

## 6. Rekaman cABR di database contoh

| Jenis | Jumlah | Titik / epoch | fs | Pra-stimulus | Bank |
| --- | --- | --- | --- | --- | --- |
| AEP, stimulus `da.wav`, 80 dB SPL, 10,9/s, rarefaksi | 119 | 512 / 74,67 ms | 6.857 Hz | −16,40 ms* | 1 |
| AEP, `da.wav`, 7,9/s | 4 | 1024 / 106,6 ms | 9.606 Hz | −20,90 ms* | 1 |
| Calculated (`da.wav`) | 3 | 512 / 74,67 ms | 6.857 Hz | −16,40 ms* | 1 |
| BioMAP (`BioMAP_da.wav`) | 3 | 1024 / 85,33 ms | 12 kHz | −15,80 ms* | 10 |

\* termasuk koreksi insert delay 0,8 ms.

Per pasien biasanya ada 2 rekaman /da/ per telinga (blok berulang). Untuk
analisis cABR keduanya dapat dirata-rata (`combine --mode add`, berbobot
jumlah sweep).

## 7. Tool cABR tujuan (cABR_Standalone dari IHS)

* `IHSStandAloneCaller.exe` – peluncur Delphi: tombol *Run IHS_Pitch*
  ("Please select the recording for pitch analysis") dan *Run
  IHS_Phaseogram* ("Please select the first/second recording"), lalu
  menjalankan exe MATLAB dengan path file.
* `IHSPITCH.exe`, `IHS_Phaseogram.exe` – MATLAB Compiler (R2008, MCR).
  Isinya adaptasi **Brainstem Toolbox** (Skoe & Kraus, Northwestern):
  `bt_ptgui_ihs`, `pitchtrack_ihs`, `phasetrack_ihs`, `openavg_ihs`,
  `openavg_pt_ihs`, `openavg_pt_stim_ihs`. File `.m` di dalamnya
  terenkripsi (format CTF MCR) dan tidak dibongkar.
* GUI pitch tracking menyatakan: *"Stimulus file must be in '.avg'
  format. Use wav2avg to convert."* — sehingga format yang dipilih
  untuk ekspor adalah **Neuroscan `.avg`**, format asli Brainstem
  Toolbox. aep2cabr juga menulis teks satu kolom + perintah
  `bt_txt2avg(...)` yang sesuai, dan perintah `wav2avg` untuk stimulus.

Catatan: pembaca respons versi IHS (`openavg_pt_ihs`) tidak dapat
diperiksa karena terenkripsi. Bila IHS ternyata memakai varian format
lain, kirimkan satu file contoh yang bisa dibuka IHSPITCH agar writer
dapat disesuaikan.

## 8. Format Neuroscan `.avg` yang ditulis

* Header SETUP 900 byte: `pnts` (368), `nchannels` (370), `rate` (376),
  `xmin`/`xmax` detik (505/509), `variance=1` (375), jumlah sweep di
  `acceptcnt` (364).
* ELECTLOC 75 byte per channel: label (mis. `C1B10`), `n=1`,
  `sensitivity=204.8`, `calib=1`, `baseline=0` → semua pembaca umum
  (EEGLAB `loadavg`, FieldTrip, Brainstem Toolbox `openavg`) mendapat µV
  tanpa skala tambahan.
* Data: per channel 5 byte header sweep + `pnts` float32; lalu blok
  variance (nol).
