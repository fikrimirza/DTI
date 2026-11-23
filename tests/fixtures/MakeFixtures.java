// Generates the synthetic test databases tests/fixtures/{BLPatients,EPWinData}.mdb
// (fake patients, synthetic waveforms - no real patient data).
//
// Requires Jackcess 4.x (+ commons-lang3, commons-logging) on the classpath:
//   javac -cp "jars/*" MakeFixtures.java
//   java  -cp "jars/*:." MakeFixtures tests/fixtures
//
// Layout mirrors the Bio-logic Navigator Pro AEP databases (only the columns
// aep2cabr uses).

import com.healthmarketscience.jackcess.*;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.time.LocalDateTime;
import java.util.*;

public class MakeFixtures {
  static final double UV_PER_COUNT = 10.0 / 65536 / 100000 * 1e6;

  static byte[] blob(int[][] chBankN, int[][] data) {
    int size = 4;
    for (int[] d : data) size += 12 + 4 * d.length;
    ByteBuffer b = ByteBuffer.allocate(size).order(ByteOrder.LITTLE_ENDIAN);
    b.putInt(10);
    for (int i = 0; i < data.length; i++) {
      b.putInt(chBankN[i][0]); b.putInt(chBankN[i][1]); b.putInt(data[i].length);
      for (int v : data[i]) b.putInt(v);
    }
    return b.array();
  }

  // sine of amplitude uv (microvolts) starting at stimulus onset (t >= 0)
  static int[] sine(int n, double dtMs, double t0Ms, double freqHz, double uv, double phase) {
    int[] out = new int[n];
    for (int i = 0; i < n; i++) {
      double t = t0Ms + i * dtMs;
      double v = t >= 0 ? uv * Math.sin(2 * Math.PI * freqHz * t / 1000.0 + phase) : 0.0;
      out[i] = (int) Math.round(v / UV_PER_COUNT) + 7; // +7 counts DC offset
    }
    return out;
  }

  public static void main(String[] a) throws Exception {
    File dir = new File(a.length > 0 ? a[0] : ".");
    dir.mkdirs();
    String P1 = "{11111111-2222-3333-4444-555555555555}";
    String P2 = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}";

    // ---------------------------------------------------------------- PTI
    File pf = new File(dir, "BLPatients.mdb"); pf.delete();
    try (Database db = DatabaseBuilder.create(Database.FileFormat.V2000, pf)) {
      Table pat = new TableBuilder("Patients")
          .addColumn(new ColumnBuilder("BLSCID", DataType.GUID))
          .addColumn(new ColumnBuilder("PatientID", DataType.TEXT).setLength(15 * 2))
          .addColumn(new ColumnBuilder("LastName", DataType.TEXT).setLength(25 * 2))
          .addColumn(new ColumnBuilder("MiddleInitial", DataType.TEXT).setLength(2 * 2))
          .addColumn(new ColumnBuilder("FirstName", DataType.TEXT).setLength(20 * 2))
          .addColumn(new ColumnBuilder("Birthdate", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("Sex", DataType.TEXT).setLength(2))
          .addColumn(new ColumnBuilder("Comment", DataType.MEMO))
          .toTable(db);
      StringBuilder longMemo = new StringBuilder();
      for (int i = 0; i < 700; i++) longMemo.append("Catatan uji ").append(i).append(". ");
      pat.addRow(P1, "TEST001", "PASIEN", null, "Contoh", LocalDateTime.of(2019, 1, 2, 0, 0), "F",
                 longMemo.toString());
      pat.addRow(P2, "TEST002", "DUMMY", "Q", "Kedua \u00e9\u00e8 \u4e2d", LocalDateTime.of(2018, 5, 6, 0, 0), "M", null);

      Table tests = new TableBuilder("Tests")
          .addColumn(new ColumnBuilder("BLSCID", DataType.GUID))
          .addColumn(new ColumnBuilder("PatientID", DataType.TEXT).setLength(30))
          .addColumn(new ColumnBuilder("TestID", DataType.TEXT).setLength(14))
          .addColumn(new ColumnBuilder("TestType", DataType.TEXT).setLength(10))
          .addColumn(new ColumnBuilder("Technician", DataType.TEXT).setLength(50))
          .addColumn(new ColumnBuilder("TestDate", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("StartTime", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("EndTime", DataType.SHORT_DATE_TIME))
          .toTable(db);
      tests.addRow(P1, "TEST001", "EP00001", "EP", "Teknisi Uji", LocalDateTime.of(2022, 3, 4, 9, 0, 0),
                   LocalDateTime.of(2022, 3, 4, 9, 0, 0), LocalDateTime.of(2022, 3, 4, 9, 30, 0));
      tests.addRow(P2, "TEST002", "EP00001", "EP", "Teknisi Uji", LocalDateTime.of(2022, 3, 5, 10, 0, 0),
                   LocalDateTime.of(2022, 3, 5, 10, 0, 0), LocalDateTime.of(2022, 3, 5, 10, 30, 0));
    }

    // ---------------------------------------------------------------- EPWin
    File ef = new File(dir, "EPWinData.mdb"); ef.delete();
    try (Database db = DatabaseBuilder.create(Database.FileFormat.V2000, ef)) {
      Table rec = new TableBuilder("Records")
          .addColumn(new ColumnBuilder("BLSCID", DataType.GUID))
          .addColumn(new ColumnBuilder("TestID", DataType.TEXT).setLength(14))
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("TestType", DataType.BYTE))
          .addColumn(new ColumnBuilder("StartTime", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("StopTime", DataType.SHORT_DATE_TIME))
          .addColumn(new ColumnBuilder("Comments", DataType.TEXT).setLength(510))
          .addColumn(new ColumnBuilder("NumberofChannels", DataType.BYTE))
          .addColumn(new ColumnBuilder("EpochTime", DataType.FLOAT))
          .addColumn(new ColumnBuilder("NumberofPoints", DataType.INT))
          .addColumn(new ColumnBuilder("CollectionRate", DataType.LONG))
          .addColumn(new ColumnBuilder("PrePostPoints", DataType.INT))
          .addColumn(new ColumnBuilder("BlockedPoints", DataType.INT))
          .addColumn(new ColumnBuilder("ADBits", DataType.BYTE))
          .addColumn(new ColumnBuilder("Data", DataType.OLE))
          .addColumn(new ColumnBuilder("SoftwareVersion", DataType.TEXT).setLength(32))
          .toTable(db);
      Table epd = new TableBuilder("EPData")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("ChannelNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("BankNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("Averages", DataType.LONG))
          .addColumn(new ColumnBuilder("ArtifactsRejected", DataType.LONG))
          .addColumn(new ColumnBuilder("Comments", DataType.TEXT).setLength(510))
          .toTable(db);
      Table amp = new TableBuilder("Amplifiers")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("ChannelNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("AmplifierGain", DataType.LONG))
          .addColumn(new ColumnBuilder("HighFilter", DataType.INT))
          .addColumn(new ColumnBuilder("LowFilter", DataType.FLOAT))
          .addColumn(new ColumnBuilder("NotchFilter", DataType.BOOLEAN))
          .toTable(db);
      Table stim = new TableBuilder("AEPStim")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("InsertDelay", DataType.FLOAT))
          .addColumn(new ColumnBuilder("Transducer", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimEar", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimPolarity", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimIntensity", DataType.INT))
          .addColumn(new ColumnBuilder("IntensityScaleName", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimRateValue", DataType.FLOAT))
          .addColumn(new ColumnBuilder("StimType", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimFrequency", DataType.INT))
          .addColumn(new ColumnBuilder("StimMaskType", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimMaskIntensity", DataType.INT))
          .addColumn(new ColumnBuilder("CustomStimFileName", DataType.TEXT).setLength(510))
          .toTable(db);
      Table bio = new TableBuilder("BioMAPStim")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("InsertDelay", DataType.FLOAT))
          .addColumn(new ColumnBuilder("Transducer", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimEar", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimPolarity", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimIntensity", DataType.INT))
          .addColumn(new ColumnBuilder("IntensityScaleName", DataType.BYTE))
          .addColumn(new ColumnBuilder("StimRateValue", DataType.FLOAT))
          .addColumn(new ColumnBuilder("StimType", DataType.BYTE))
          .addColumn(new ColumnBuilder("CustomStimFileName", DataType.TEXT).setLength(510))
          .toTable(db);
      Table mp = new TableBuilder("MarkedPoints")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("ChannelNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("BankNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("LabelNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("MarkedPoint", DataType.INT))
          .addColumn(new ColumnBuilder("MarkedLatency", DataType.FLOAT))
          .addColumn(new ColumnBuilder("MarkedAmplitude", DataType.FLOAT))
          .toTable(db);
      Table lab = new TableBuilder("Labels")
          .addColumn(new ColumnBuilder("RecordID", DataType.GUID))
          .addColumn(new ColumnBuilder("LabelNumber", DataType.BYTE))
          .addColumn(new ColumnBuilder("LabelText", DataType.TEXT).setLength(10))
          .toTable(db);

      String DA = "C:\\Program Files (x86)\\Natus\\AEP\\da.wav";
      // R1, R2: cABR /da/ 512 pts, 74.67 ms, prestim -749/48 ms, rarefaction / condensation
      double dt = 74.67 / 512;
      double t0 = -749 / 48.0;
      String[] ids = {"{00000000-0000-0000-0000-000000000001}", "{00000000-0000-0000-0000-000000000002}",
                      "{00000000-0000-0000-0000-000000000003}", "{00000000-0000-0000-0000-000000000004}",
                      "{00000000-0000-0000-0000-000000000005}"};
      int[] polarity = {2, 1};
      for (int k = 0; k < 2; k++) {
        int[] w = sine(512, dt, t0, 100.0, 0.2, k == 0 ? 0 : Math.PI);
        rec.addRow(P1, "EP00001", ids[k], 1, LocalDateTime.of(2022, 3, 4, 9, 10 + k, 0),
                   LocalDateTime.of(2022, 3, 4, 9, 11 + k, 0), null, 1, 74.67f, 512, 6, -749, 672, 16,
                   blob(new int[][]{{1, 1}}, new int[][]{w}), "ver 7.2.1");
        epd.addRow(ids[k], 1, 1, 1000 + k * 24, 3, null);
        amp.addRow(ids[k], 1, 100000, 2000, 100.0f, false);
        stim.addRow(ids[k], 0.8f, 2, 1, polarity[k], 80, 0, 10.9f, 6, -100, 0, 80, DA);
      }
      // R3: click ABR alternating, 4 banks
      double dtc = 10.66 / 256;
      int[][] banks = new int[4][];
      for (int b = 0; b < 4; b++) banks[b] = sine(256, dtc, 0, 1000.0, 0.3 + 0.05 * b, 0);
      rec.addRow(P1, "EP00001", ids[2], 1, LocalDateTime.of(2022, 3, 4, 9, 20, 0),
                 LocalDateTime.of(2022, 3, 4, 9, 21, 0), "click 70", 1, 10.66f, 256, 24, 0, 62, 16,
                 blob(new int[][]{{1, 1}, {1, 2}, {1, 10}, {1, 11}}, banks), "ver 7.2.1");
      int[] bk = {1, 2, 10, 11};
      int[] avg = {768, 768, 1536, 1536};
      for (int b = 0; b < 4; b++) epd.addRow(ids[2], 1, bk[b], avg[b], 0, null);
      amp.addRow(ids[2], 1, 100000, 1500, 100.0f, false);
      stim.addRow(ids[2], 0.8f, 2, 2, 3, 70, 2, 44.7f, 1, -100, 0, 80, null);
      lab.addRow(ids[2], 1, "V");
      // marked point at sample 112 of bank 10 (latency shown re. insert delay)
      double lat = 112 * dtc - 0.8;
      mp.addRow(ids[2], 1, 10, 1, 0, (float) lat, (float) (banks[2][112] * UV_PER_COUNT));
      // R4: BioMAP 1024 pts, 2 banks (8 KB blob -> multi page long value)
      double dtb = 85.33 / 1024;
      int[][] bb = {sine(1024, dtb, -15.0, 100.0, 0.25, 0), sine(1024, dtb, -15.0, 100.0, 0.25, Math.PI)};
      rec.addRow(P2, "EP00001", ids[3], 9, LocalDateTime.of(2022, 3, 5, 10, 5, 0),
                 LocalDateTime.of(2022, 3, 5, 10, 6, 0), null, 1, 85.33f, 1024, 12, -720, 0, 16,
                 blob(new int[][]{{1, 10}, {1, 11}}, bb), "6.2.4");
      epd.addRow(ids[3], 1, 10, 4096, 0, null);
      epd.addRow(ids[3], 1, 11, 4096, 0, null);
      amp.addRow(ids[3], 1, 100000, 2000, 100.0f, false);
      bio.addRow(ids[3], 0.8f, 2, 2, 3, 80, 2, 10.9f, 6, "BioMAP_da.wav");
      // R5: record of a patient missing from BLPatients (demo data case)
      rec.addRow("{99999999-9999-9999-9999-999999999999}", "EP00001", ids[4], 9,
                 LocalDateTime.of(2021, 1, 1, 8, 0, 0), LocalDateTime.of(2021, 1, 1, 8, 1, 0), null, 1,
                 85.33f, 1024, 12, -720, 0, 16, blob(new int[][]{{1, 10}}, new int[][]{bb[0]}), "6.1.1");
      epd.addRow(ids[4], 1, 10, 4096, 0, null);
      amp.addRow(ids[4], 1, 100000, 2000, 100.0f, false);
      bio.addRow(ids[4], 0.8f, 2, 2, 3, 80, 2, 10.9f, 6, "BioMAP_da.wav");
    }
    System.out.println("fixtures written to " + dir);
  }
}
