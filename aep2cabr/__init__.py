"""aep2cabr - rewrite of Bio-logic AEP2ASC 1.6.0.

Reads the Bio-logic / Natus Navigator Pro AEP databases (BLPatients.mdb and
EPWinData.mdb) without ODBC or Microsoft Access and exports the waveforms
for complex-ABR (cABR) analysis: Neuroscan .avg (Brainstem Toolbox, IHS
cABR stand-alone tools), single column text for bt_txt2avg, CSV and the
classic AEP2ASC ASCII layout.
"""

__version__ = "2.0.0"
