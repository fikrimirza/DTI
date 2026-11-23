"""Code -> text tables for the Bio-logic Navigator Pro AEP database.

The texts are the ones used by Bio-logic's AEP2ASC 1.6.0.  The numeric codes
were inferred from the AEP2ASC string tables and checked against real data
(see ``docs/ANALISIS_AEP2ASC.md``):

* TestType 1/4/6/9 are confirmed by the matching stimulus tables
  (AEPStim / EXTStim / CalculatedStim / BioMAPStim).
* Transducer 2 = ER-3 insert earphone is confirmed by its 0.8 ms InsertDelay.
* StimType 1 = click (100 us click duration), 4 = tone burst (500 Hz),
  6 = custom (.wav) are confirmed by the other stimulus fields.
* StimPolarity 3 = alternating is confirmed by the 4 stored banks
  (condensation, rarefaction, added, subtracted).
* IntensityScaleName 0 = dB SPL, 2 = dB nHL fit the clinical protocols
  (BioMARK /da/ 80 dB SPL, click ABR in dB nHL).
* StimEar 1 = Left, 2 = Right could NOT be verified from data; the raw code
  is therefore always exported next to the text.
"""

TEST_TYPES = {
    1: "AEP",
    2: "P300",
    3: "Alternate Ear",
    4: "External Stimulus",
    5: "External Stimulus P300",
    6: "Calculated",
    7: "Self Test",
    8: "Stacked ABR",
    9: "BioMAP",
    10: "VEMP",
}

# stimulus table that holds the stimulus parameters of each test type
STIM_TABLES = {
    1: "AEPStim",
    2: "P300Stim",
    3: "AltEarStim",
    4: "EXTStim",
    5: "EXTP300Stim",
    6: "CalculatedStim",
    8: "SABRStim",
    9: "BioMAPStim",
    10: "VEMPStim",
}
ALL_STIM_TABLES = ["AEPStim", "BioMAPStim", "CalculatedStim", "EXTStim",
                   "EXTP300Stim", "P300Stim", "AltEarStim", "SABRStim",
                   "VEMPStim"]

STIM_EAR = {1: "Left", 2: "Right", 3: "Both", 4: "Alternating"}

TRANSDUCERS = {
    1: "Headphone",
    2: "Insert Earphone (ER3)",
    3: "Bone Oscillator",
    4: "Speaker",
    5: "Insert Earphone (ER2)",
    6: "OAE Probe",
    7: "Ear Muffin",
    8: "Insert Earphone (BB)",
}

STIM_TYPES = {
    1: "Click",
    2: "Filtered Click",
    3: "Single Sine",
    4: "Tone Burst",
    5: "Masked Click",
    6: "Custom",
}

POLARITY = {1: "Condensation", 2: "Rarefaction", 3: "Alternating",
            4: "Differential"}

INTENSITY_SCALE = {0: "dB SPL", 1: "dB HL", 2: "dB nHL"}

MASK_TYPES = {1: "White", 2: "Pink"}

# banks stored for alternating polarity recordings (AEP2ASC manual)
BANK_NAMES = {
    1: "Condensation",
    2: "Rarefaction",
    10: "Added (Cond+Rare)",
    11: "Subtracted (Cond-Rare)",
}
P300_BANK_NAMES = {1: "Frequent", 2: "Infrequent"}


def text(table, code, default="Unknown"):
    """Look up *code* in *table*; unknown codes keep their number."""
    if code is None:
        return ""
    try:
        return table[int(code)]
    except (KeyError, ValueError, TypeError):
        return "%s (%s)" % (default, code)
