# Evaluation methodology

What we measured, how, and what the numbers do **not** show. Results:
[`results/REPORT.md`](results/REPORT.md) (generated from `results/*.json` by `report.py`; no number
in the report is typed by hand).

## Running it

Everything runs inside the backend container against the loaded database (Stage 2 ingestion).

```powershell
# one-off downloads (git-ignored, under data/raw/)
#   CRESCENDDI (CC0): https://doi.org/10.6084/m9.figshare.c.5481408
#     positive.xlsx      <- https://ndownloader.figshare.com/files/28584873
#     negative.xlsx      <- https://ndownloader.figshare.com/files/28584876
#     drug_mappings.xlsx <- https://ndownloader.figshare.com/files/28584879
#     save in data/raw/crescenddi/ (the script checks the published MD5 sums)
#   Handwriting-style fonts (SIL OFL 1.1), from github.com/google/fonts, into data/raw/fonts/:
#     ofl/kalam/Kalam-Regular.ttf, ofl/caveat/Caveat[wght].ttf (saved as Caveat-VF.ttf)
docker compose run --rm backend python /evaluation/run.py            # all parts, ~2 min
docker compose run --rm backend python /evaluation/run.py ocr        # one part
```

All randomness is seeded; repeated runs give the same cases (timings vary slightly).

## 1. Name recognition (`eval_normalisation.py`)

**Question:** when staff type a medicine, does the app land on the right ingredient(s), and does it
ever silently pick a wrong one?

**Cases (222).** 166 written by hand in `data/normalisation_cases.csv` before the first run,
from common Indian prescribing: Indian brands (as typed, with strengths and dose patterns),
INN/BAN names that differ from US names (paracetamol, frusemide, adrenaline, lignocaine,
glibenclamide...), generics with salts and strengths, common misspellings, abbreviations,
combinations, US brands, and 11 lines that are not medicines (dose instructions, names, lab
tests). Plus 56 seeded single-edit typos (drop, swap, double, vowel change) of the generic
names in the file.

**Reference.** Each case lists the expected ingredient names. They are turned into RxCUIs by
**exact** name lookup in our ingredient table (never by the matcher being tested). If an expected
ingredient is not in our vocabulary at all, the case is reported as a coverage gap, not a
matcher error.

**Metrics.** Top-1: the first suggestion has exactly the expected ingredient set. Top-3: it is
among the first three. Status: *resolved* (added without asking), *confirm* (the user picks from
choices), *unknown*. **Wrong auto-accept** (the safety metric): resolved to the wrong ingredients,
or a non-medicine resolved to anything. External RxNav suggestions are switched off, so the run
is reproducible and offline.

**Limits.** The cases were written by the same team that built the matcher (not blinded); the
brand cases partly overlap the curated brand table (25 brands), so brand accuracy for brands
outside that table is low (see "not found"). Generated typos are single edits; real typos can be
worse.

**Changes after the first run (disclosed).** Two reference answers were wrong and were
corrected: *Shelcal 500* (its cited source lists elemental calcium + vitamin D3, which is what
the app returns; we had assumed calcium carbonate) and *valproate* (RxNorm's ingredient name is
"valproate", not "valproic acid"). The matcher was **not** tuned on these cases: the 9 "not
found" cases (uncurated brands such as Pan 40, Amlong, Rantac; "HCQ"; two combination phrasings;
Coumadin) are left as they are and listed in the report.

## 2. Interactions (`eval_interactions.py`)

**Question:** for pairs that independent drug-interaction references list as interacting, do
we warn, and at what level? For pairs they do not, how often do we warn anyway?

**Reference: CRESCENDDI** (Kontsioti, Maskell, Dutta & Pirmohamed, "A reference set of
clinically relevant adverse drug-drug interactions", *Scientific Data*, 2022,
doi:10.1038/s41597-022-01159-y; data CC0). Positive controls: drug pairs listed as interacting in the BNF and/or Micromedex
(10,286 pair-event rows), with severity from the BNF, the French ANSM thesaurus and Micromedex.
Negative controls: 4,544 pair-event rows with no interaction listed for that adverse event.
CRESCENDDI shares no source with our interaction data (DDInter 2.0, MED-RT, FDA labels).

**Mapping.** CRESCENDDI drugs map to our ingredients by their RxNorm code, or else by exact
name (never fuzzy). Rows collapse to unordered drug pairs: 4,276 positive and 3,888 negative
pairs. Negative pairs that also appear as positive (for another event) are dropped. The reference
severity of a pair is the most serious level any of the three sources gives it:
*serious* = Micromedex contraindicated/major, BNF severe, ANSM contre-indication/association
déconseillée; *moderate* = Micromedex/BNF moderate, ANSM précaution d'emploi.

**Procedure.** Each pair goes through the real engine (`check()`, all datasets, label text and
cumulative/duplicate rules, no patient context) as two medicines. "Any warning" = any finding;
our severity = the most severe finding. The app's sections: *needs attention* = contraindicated
or major; *worth checking* = moderate; minor and ungraded findings are shown collapsed.

**How to read the results.**
- About 88% of reference interactions get a warning. Only about 55% of *serious* reference pairs
  reach "needs attention", because DDInter often grades as moderate what the BNF/Micromedex call
  severe. Severity disagreement between compendia is well documented and is the reason
  CRESCENDDI was built from several of them.
- "Any finding" on negative controls (53%) is mostly DDInter listing the pair **without a
  severity grade**, which the app shows collapsed under "other listed interactions". At "worth
  checking or higher" the rate is 14%, and at "needs attention" 1.2%.
- A negative control means "no interaction known **for that adverse event** in these
  references", not "safe together", so these false-alarm rates are upper bounds.
- Precision depends on the ratio of positive to negative pairs in the reference set and does not
  carry over to real prescriptions.
- CRESCENDDI reflects UK/US/French practice, and so do our sources; neither is a ground truth
  for Indian prescribing.

**Not tested here:** patient-context contraindications, recall matching, and three-drug
cumulative rules (CRESCENDDI is pairwise).

## 3. Prescription reading (`eval_ocr.py`)

**Question:** from a photo of a prescription, are the medicine lines read and matched correctly,
and is anything wrongly added?

**Pages.** Rendered by `app/core/ocr/synthetic.py`: an invented clinic/doctor/patient header,
3–4 numbered medicine lines drawn (seeded) from 20 realistic lines (brand or generic, strength,
dose pattern, instructions), and footer text. Six pages for each of nine variants:
- *printed*: clean sans, serif, rotated 5°, Gaussian blur 1.2, 2% salt-and-pepper speckle,
  small low-resolution page;
- *handwriting-style*: two handwriting fonts (Kalam, Caveat; SIL OFL), one also rotated and
  blurred.

**Handwriting is NOT really tested.** We had no real, consented handwritten prescriptions, and
we did not want to invent "realistic" ones. Fonts are far more regular than a doctor's hand, so
the handwriting-style numbers are an **upper bound**. Real handwriting will do worse; the app
already warns about this and shows each crop next to its reading.

**Procedure.** The full pipeline runs: pre-processing, Tesseract, line classification, name
matching with the OCR confidence rule. Each written medicine line is matched to the closest OCR
line by edit distance. Outcomes: *added in one tap* (auto-resolved correctly), *found* (auto or
the right answer in the top 3 choices), **wrong auto-accept** (safety), *missed*. Also reported:
character error rate (CER, normalised Levenshtein distance), non-medicine lines wrongly offered
as medicines, and time per page.

**Change after the first run (disclosed).** The first run found that "Tab Thyronorm 50 1-0-0
empty stomach" was read perfectly (CER 0) but never matched: the instruction "empty stomach" was
not recognised as an instruction. We added common instruction phrases (empty stomach,
before/after breakfast/lunch/dinner, at bedtime, with food/milk/water, daily, weekly, alternate
days) to the parser, with unit tests. Before the fix: printed found 97.7%, handwriting-style
74.2%. After: 100% and 80.6%. The name-recognition results did not change.

**Not tested:** real phone photos (perspective, shadows, glare), multi-column layouts, and the
optional vision-LLM engine (off by default; it would need an API key and sends images off the
device).

## 4. Latency (`eval_latency.py`)

The real app runs in-process (FastAPI TestClient) against the loaded database: 50 sequential
calls per endpoint after a warm-up (10 for OCR), with rate limits off. Search queries, typed
lines and medicine lists are fixed and seeded. **Network time is not included**: on a slow
mobile connection, add the round trip and the transfer of the gzipped response sizes shown. The
offline pack's first build is timed once (it is then cached in memory and prebuilt at startup).
The machine was the development laptop (Windows 11, Docker Desktop), so absolute numbers depend
on the hardware.

## 5. Offline engine parity (Stage 9, recorded for completeness)

The TypeScript offline engine must give the same results as the Python engine. 17 shared test
vectors run in CI on both sides. A real-data check (`backend/scripts/offline_parity.py` then
`frontend/src/lib/offline/parity.test.ts`) ran 500 seeded random medicine lists (381 with
findings): 500/500 identical.

## What this evaluation does not cover

- **Usability with real pharmacists and nurses** (time to complete a check, understanding of the
  wording). It needs a small user study.
- **Clinical outcomes.** This is decision support; we measure agreement with references, not
  patient harm avoided.
- **Recall and alert matching.** It is exercised by unit and database tests against real openFDA
  and CDSCO records, but there is no independent reference set for Indian product recalls.
- **Hindi and Kannada wording.** These are machine translations awaiting native-speaker review.
