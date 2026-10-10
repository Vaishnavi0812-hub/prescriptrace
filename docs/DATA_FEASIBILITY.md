# Data feasibility report

All findings below come from live calls made on **2026-10-09** from this machine. Nothing is
taken on trust from memory. Raw probe files were kept outside the repo.

## Summary

| Need | Source tested | Live status | Licence | Verdict |
|---|---|---|---|---|
| Name normalisation (US/generic) | RxNorm REST API (v3.1.356, data 05-Oct-2026) | ✅ works, no key | Public domain (API) | **Use** for spelling/approximate match fallback |
| Local offline normalisation | RxNorm *Current Prescribable Content* zip (75 MB, 29-Sep-2026) | ✅ downloadable, no login | **Public domain, no licence needed** (NLM page) | **Use** as local copy |
| Full RxNorm release | RxNorm full monthly | requires UMLS licence | UMLS licence (some sources restricted) | **Skip**: Prescribable subset suffices |
| Interactions (RxNav) | `/REST/interaction/*` | ❌ **HTTP 404** on both endpoints | — | **Confirmed discontinued**. Not used |
| Interactions (primary) | DDInter 2.0 CSV downloads (14 ATC files, 234,981 pairs) | ✅ (slow, flaky server) | **CC BY-NC-SA 4.0** | **Proposed primary**, see licence implications |
| Interactions (signals) | TWOSIDES (nSIDES, S3) | ✅ 738 MB gz, last modified 2024-03-30 | not stated on site | **Do not use** for warnings (see below) |
| Interactions (DrugBank) | DrugBank 5.1.22 | account + approval | Academic licence: "solely for academic purposes"; open data CC BY-NC 4.0 | **Skip**: blocks public deployment |
| Interactions (supplementary) | openFDA `drug/label` `drug_interactions` | ✅ 68,768 labels have the section | openFDA: CC0 / public domain | **Use** as lower-confidence, text-sourced tier |
| Recalls (US) | openFDA `drug/enforcement` bulk | ✅ 18,002 records, export 2026-10-06, 4 MB | CC0 | **Use** |
| Adverse events | openFDA `drug/event` (FAERS) | ✅ API; bulk = 1,767 parts / ~110 GB | CC0 | API counts only, optional context; **not** used for warnings |
| Pharmacologic classes | RxClass (FDASPL EPC, ATC, MED-RT) | ✅ | EPC/MED-RT public domain; ATC codes are © WHOCC with their own reuse terms (not yet checked, so ATC is used for internal grouping only and not redistributed) | **Use** EPC + MED-RT; ATC for grouping only |
| QT / serotonergic / CNS-depressant flags | openFDA label text search | ✅ (see counts) | CC0 | **Use**, with a curated review step |
| Patient-context (pregnancy, renal, hepatic) | MED-RT `CI_with` via RxClass; openFDA label sections | ✅ | Public domain / CC0 | **Use**, label sections shown as "check label" notes |
| India: NSQ / spurious lists | CDSCO monthly PDFs | ✅ text-extractable PDFs | Govt. of India public notice (no explicit licence) | **Feasible (stretch)**, needs table parsing + validation |
| Global falsified alerts | WHO Medical Product Alerts | ✅ ~92 HTML alert pages | WHO website terms (non-commercial reuse with attribution) | **Feasible (stretch)**, small, could be curated per page |
| Indian brand → ingredient | RxNorm | ❌ mostly absent / **wrong matches** | — | Needs a separate source, **decision needed** |
| Interaction evaluation reference | CRESCENDDI (Sci Data 2022) | ✅ 10,286 positive controls; negatives file 403 on first try | **CC0** | **Use** as independent eval set |

## Key findings in detail

### 1. RxNav Drug Interaction API is gone (confirmed)
`GET /REST/interaction/list.json?rxcuis=11289+5640` → `404 Not found`;
`/REST/interaction/interaction.json?rxcui=11289` → `404`. The interaction engine will not depend on it.

### 2. RxNorm works well for generics and US brands, and is unsafe for Indian brands
Approximate-match results (`/REST/approximateTerm`):

| Input | RxNorm top result | Correct? |
|---|---|---|
| `paracetmol` | 161 acetaminophen (via ATC "paracetamol") | ✅ |
| `Metf0rmin` | 6809 metformin | ✅ |
| `amox/clav` | 19711 amoxicillin / clavulanate | ✅ |
| `Augmentin 625` | 151392 Augmentin (brand) | ✅ |
| `Crocin 650` | 2262278 **crocin** (saffron carotenoid, an ingredient) | ❌ **dangerous false match** (Crocin = paracetamol in India) |
| `Glycomet 500` | **glycogen** | ❌ (Glycomet = metformin) |
| `Telma 40` | **alcohol topical gel [Delma]** | ❌ (Telma = telmisartan) |
| `Dolo 650` | "No Dolo" | ❌ (Dolo = paracetamol) |
| `Calpol` | no result | ❌ |
| `Ecosprin 75` | "Easprin" (US aspirin brand), score 1.59 | ⚠ right ingredient by luck, very low score |

Implications:
- An India-specific brand table must be checked **before** RxNorm, and RxNorm approximate
  matches must never be accepted for brand-looking tokens without an independent signal.
- RxNorm's `score` is relative to the query, not an absolute confidence. We will compute our own
  confidence (exact/brand-table/trigram/RxNorm agreement) and calibrate it on the eval set.

### 3. Interaction data choice
- **DDInter 2.0**: licence (from `/terms/`): *"The DDInter data is made available under a Creative Commons
  Attribution-NonCommercial-ShareAlike 4.0 International license."* Download page lists 8 ATC-group CSVs
  (A, B, D, H, L, P, R, V) with columns `DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level`.
  The unlisted groups (C cardiovascular, J anti-infectives, N nervous system, G…) **also exist at
  the same URL pattern**, which matters because pairs like SSRI + tramadol (N–N) would
  otherwise be missing. All 14 files (A B C D G H J L M N P R S V) were downloaded and
  verified against Content-Length. The server is slow and starts refusing connections after
  repeated requests, so ingestion must use resumable downloads with backoff and keep a local copy.
  - Coverage measured: **1,971 drugs, 234,981 unique pairs**, 0 malformed rows, no
    conflicting severities across files. Only ~149k pairs are reachable from the 8 listed files.
  - Severity mix (unique pairs): Moderate 143,748 · Unknown 42,415 · Major 39,082 · Minor 9,736.
  - Spot check of 15 well-known pairs: 15/15 present. sertraline+tramadol, warfarin+ibuprofen,
    amiodarone+digoxin, simvastatin+clarithromycin, sildenafil+nitroglycerin,
    lisinopril+spironolactone, fluoxetine+linezolid, methotrexate+trimethoprim,
    clopidogrel+omeprazole, metformin+iohexol, citalopram+ondansetron, diazepam+morphine,
    ciprofloxacin+tizanidine, aspirin+ibuprofen = Major. acetaminophen+warfarin = Moderate.
  - Names mix INN and US conventions (aspirin is "Acetylsalicylic acid", but paracetamol is
    "Acetaminophen"), so an explicit DDInter-name → RxNorm-ingredient mapping step is required.
  - Severity levels: Major / Moderate / Minor / **Unknown** (no "contraindicated" level). We will
    not invent a contraindicated tier from DDInter; "contraindicated" will only come from label
    text (`contraindications` section) or MED-RT `ci_chemclass`, with that source shown.
  - The CSV has **no mechanism/management text**. Explanations will be templates built from
    severity + pharmacologic classes, plus label excerpts where they exist. DDInter's per-pair
    descriptions exist on its website but are not in the bulk files, and we will not scrape them.
  - No RxCUI in the file → map DDInter drug names to RxNorm ingredients at ingest (exact name,
    then RxNorm lookup); unmapped names reported, not guessed.
- **TWOSIDES**: statistical FAERS co-reporting signals (drug pair → side effect, PRR), no clinical
  severity, last updated 2024-03, licence not stated on the site, and the nSIDES page itself says the
  resources are "quite a bit out of date". Using these as warnings would cause alert fatigue
  and would not be defensible. **Proposal: exclude** (mention as related work in the paper).
- **DrugBank**: academic licence requires approval and "a tool solely for academic purposes";
  open subsets are CC BY-NC and contain no interactions. **Skip.**
- **openFDA labels**: the `drug_interactions` free text exists for 68,768 labels, CC0. It will be used as a
  **second, lower-confidence tier** ("mentioned in FDA label") when label text names the other
  ingredient, always shown with the label set_id and a quote.

### 4. Pharmacologic classes for cumulative-risk rules
- RxClass FDASPL EPC (762 classes) covers: NSAID, ACE inhibitor, ARB, potassium-sparing diuretic,
  potassium salt, platelet aggregation inhibitor, P2Y12 inhibitor, opioid agonist, benzodiazepine,
  serotonin reuptake inhibitor, etc. Verified: citalopram → "Serotonin Reuptake Inhibitor".
- **No open class exists for "QT-prolonging" or "serotonergic"** (CredibleMeds is the reference
  list but requires registration and restricts redistribution, so it is not used). Proposal:
  derive these flags from FDA label text, with evidence stored per drug:
  - `warnings_and_cautions` mentions "QT prolongation": 164 distinct generics; `warnings`: 27;
    boxed warning mentions QT: 14 (e.g. sotalol, methadone, ketoconazole, droperidol).
  - "serotonin syndrome" in `warnings_and_cautions`: 124 generics (sertraline, tramadol,
    ondansetron, mirtazapine…).
  - Boxed warning mentioning "CNS depressants": 57 generics (opioids).
  - Text mentions include negations ("no clinically relevant QT effect"), so flags go through
    a generated **review file committed to the repo** (drug, matched sentence, include yes/no) so
    the rule table stays auditable.
- MED-RT (via RxClass) gives `CI_with` diseases (e.g. ibuprofen → "Pregnancy Trimester, Third",
  asthma) and `ci_chemclass` (amiodarone → fluoroquinolones). These are public domain and usable for
  patient-context notes.

### 5. Recalls
- openFDA enforcement bulk: 18,002 records (export 2026-10-06). Records include `openfda.rxcui`,
  `product_ndc`, brand/generic, `classification`, `reason_for_recall`, `status`, `code_info`
  (lot numbers), firm, dates. This supports "exact product match" vs "same ingredient" distinction.
- Most records are **US products**. For an Indian pharmacy an "exact product" match will be rare.
  The UI will say "US FDA recall of a product with the same ingredient" rather than alarm.
- Limits (openFDA docs): no key 240 req/min & 1,000/day per IP; with free key 120,000/day. We
  use bulk downloads for ingestion, so the API is not hit at runtime.

### 6. India regional sources (stretch)
- **CDSCO** NSQ/spurious monthly lists: listing page → `download_file_division.jsp?num_id=…` →
  an `<iframe>` wrapping the real PDF URL. Tested "CDSCO NSQ June-2025" (6 pages) and "List
  of spurious drugs June-2025" (2 pages): **text is extractable** (not scanned), with columns
  S.No / product (brand in parentheses) / batch / mfg & expiry date / manufacturer / reason /
  reporting lab. Cells wrap across lines, so this needs table-aware extraction (pdfplumber) plus
  per-file validation (row count matches the S.No sequence). Batch numbers are present, so we
  can tell the user "check whether your strip's batch is X".
- A CDSCO notice (Aug-2025) announces NSQ alerts moving to a **new link**. That notice PDF is a
  scanned image (0 extractable chars). The newest listings on the old page are from mid-2025,
  so **recent months may now live elsewhere**. I have not yet found the new location, and this
  needs checking before Stage 5.
- **WHO Medical Product Alerts**: ~92 HTML alert pages (2021→2026, latest "N°3/2026 falsified
  Darzalex"). Each describes product, batch, and countries. Small enough to parse per page
  with manual validation.

### 7. Indian brand names (biggest gap)
No official, open, machine-readable Indian brand→composition registry was found:
- CDSCO approval lists are generic-level; Jan Aushadhi product list is a JS app (generic names only).
- Kaggle "A-Z Medicine Dataset of India" (~32 MB, Nov-2022 snapshot, brand + composition +
  manufacturer, ~7,600 companies): declared **CC BY-SA 4.0** by the uploader, but it appears to
  be scraped from a commercial e-pharmacy, so upstream rights are unclear. It needs a Kaggle account
  to download and is 4 years old.

### 8. Evaluation reference
- **CRESCENDDI** (Kontsioti et al., *Sci Data* 2022, doi:10.1038/s41597-022-01159-y; data
  figshare collection 5481408, **CC0**): 10,286 positive-control rows (drug pair + event) with
  independent severity labels from **BNF, ANSM and Micromedex**, plus a negative-control set.
  This is independent of DDInter and supports precision/recall/false-alarm by severity.
- For OCR eval there is no permissively licensed public prescription image set yet; the plan is
  to generate synthetic printed prescriptions and collect a small handwritten set made by us
  (no real patients).

## Decisions (approved 2026-10-09)
1. **DDInter 2.0 is the primary interaction source** under CC BY-NC-SA 4.0. Non-commercial use
   only; derived interaction data is shared under the same licence; shown in README + About page.
2. **Indian brands: a curated, hand-checked table** (~300 common brands to start). Every row
   cites a verifiable source (e.g. CDSCO NSQ/spurious lists, which print the brand next to the
   generic, such as "Cefixime Tablets IP (TAXIM-O 200)"; manufacturer product pages). No row
   without a source. The Kaggle A-Z dataset is not used.
3. **TWOSIDES excluded** from warnings; cited only as related work.
4. **CDSCO deferred to Stage 5** (stretch): locate the new NSQ link, parse PDFs with row-count
   validation, or document as future work.
5. Also adopted: RxNorm Prescribable Content (local) + RxNorm API fallback; openFDA enforcement
   (recalls) and label (supplementary interactions, class flags, patient-context notes);
   RxClass EPC + MED-RT; CRESCENDDI for evaluation; DrugBank skipped.

## Stage 2 load results (2026-10-10)

All counts are from `ingest_run` logs of the loaded database; rerun with
`docker compose run --rm backend python -m app.ingest all`.

| Dataset | Version | Loaded | Notes |
|---|---|---|---|
| RxNorm Prescribable | 2026-09-29 | 5,874 ingredients · 21,514 products · 4,140 brands · 29,373 product–ingredient links (with strength) · 70,323 searchable names | Augmentin → amoxicillin + clavulanate verified |
| DDInter 2.0 | 2.0 | 215,168 ingredient pairs | 1,761/1,971 drugs mapped; 168 route-specific entries excluded by design (ADR-005); 42 other unmapped (`backend/data/reports/ddinter_unmapped.csv`) |
| openFDA recalls | export 2026-10-06 | 18,001 recalls · 30,775 links | ingredient links: 3,100 via structured substance names, 10,681 via product-description text (20/20 random sample correct), 4,220 unlinked (mostly homeopathic products, kits, abbreviations like "HCG") |
| openFDA labels | export 2026-10-09 | 6,473 representative labels (2,686 single-ingredient) · 5,634 context notes | 178,036 of 262,893 labels have no harmonised `openfda` block (ingredients unidentifiable; mostly repackager duplicates); 431 of 6,143 substance names unmapped |
| Label class flags | — | QT-prolonging 141 · serotonergic 56 · CNS depressant 80 | 1 sent to human review (metoclopramide, differential-diagnosis mention); candidates in `backend/data/reports/label_flag_candidates.csv` |
| RxClass (FDA EPC/MOA) | fetched 2026-10-10 | 3,935 memberships | |
| MED-RT | fetched 2026-10-10 | 1,981 contraindicated pairs · 796 context contraindications | licence still to be confirmed |
| ATC (internal only) | fetched 2026-10-10 | 3,109 memberships | not shown or exported |
| India brands (curated) | verified 2026-10-10 | 25 brands | 25/26 sources verified; Storvas CV page now 404 (not loaded) |
| RxNav gap-fill | — | 2296 ingredients · 2815 synonyms | non-US ingredients (e.g. nimesulide, aceclofenac) and INN names (acetylsalicylic acid) |

Operational notes: the DDInter server and this connection are unreliable. Downloads resume and
write `.complete` markers; API calls are cached and retried for up to 10 minutes. A failed source
rolls back completely and a re-run reuses the cache (classes: 42 s fully cached).

### Stage 3 note: international names and coverage gaps
`backend/data/curated/inn_synonyms.csv` adds British/international names used in India
(paracetamol, salbutamol, frusemide, …). Each loads only if RxNav finds the exact name AND it maps
to the expected ingredient: 31 loaded, 7 rejected. **Not in RxNorm at all** (so not recognisable,
users must be told): itopride, teneligliptin, voglibose, cilnidipine, doxofylline. Ursodeoxycholic
acid is rejected because RxNorm has a separate "ursodeoxycholate" concept besides "ursodiol"
(merging could split its interactions). Common Indian combination names (amoxyclav,
co-trimoxazole) and vitamin shorthand (vit D3, vit B12) are handled as curated abbreviations.

## Stage 5 results: recall and alert sources (2026-10-10)
| Source | Result |
|---|---|
| CDSCO NSQ + spurious alerts | 60 alert PDFs listed since 2023-07; **42 parsed and validated**, 18 rejected whole (11 numbering problems, 7 layout problems; see `backend/data/reports/cdsco_files.csv`); 1,974 records, **439 unexpired batches kept**; 230 linked to ingredients by the normaliser, 100 with brand only. Includes spurious Telma 40 batches 05240226 and K18230707. **Coverage ends mid-2025** (newer portal not accessible). |
| WHO Medical Product Alerts | Assessed, **not loaded**: only ~10 alerts visible without JavaScript; batch details are narrative/images. Future work. |
| Checklist sources | CDSCO "Guidance for Identification and Verification of Spurious Drugs" and FAQ on G.S.R. 823(E) (Schedule H2 QR codes on top-300 brands since 2023-08-01); US FDA counterfeit-medicine page. |

Also fixed in Stage 5: 2,304 ingredients gap-filled from RxNav (domperidone, nimesulide,
aceclofenac, etoricoxib, ornidazole…) were not findable by their own names in the normaliser;
pharmacopoeia markers (IP/BP/USP), stray units and tablet descriptors are now ignored when
matching; weak fuzzy look-alikes (similarity < 87, e.g. itopride → iopromide) are listed but never
offered as a single "confirm" suggestion.
