# Architecture decisions

Short ADR-style records. New entries are appended as decisions are made; the remaining required
topics (local DB vs live APIs, Tesseract vs vision-LLM, rule-based vs ML, precision vs recall
thresholds, privacy, PWA vs native, template vs LLM explanations) are written up as each is
implemented and finalised in Stage 10.

## ADR-001 Interaction data source
- **Context:** The RxNav interaction API returns HTTP 404 (verified 2026-10-09). We need
  structured, severity-graded drug–drug interactions that can be stored locally.
- **Options:** DDInter 2.0 (CC BY-NC-SA 4.0, 234,981 pairs); TWOSIDES (FAERS signals, no
  severity, last updated 2024); DrugBank (academic-only licence); openFDA label text (CC0, free text).
- **Decision:** DDInter 2.0 as primary; openFDA label text as a lower-confidence supplementary tier.
- **Consequences:** Non-commercial use only; derived data shared under the same licence. No
  "contraindicated" level and no explanation text in the bulk files, so contraindicated comes only
  from labels/MED-RT and explanations are templates.

## ADR-002 Indian brand names
- **Context:** RxNorm lacks Indian brands and produces dangerous false matches
  (Crocin → saffron carotenoid, Glycomet → glycogen).
- **Decision:** A curated, hand-checked brand table where every row cites a verifiable source;
  it is checked before RxNorm, and RxNorm approximate matches are never accepted alone for
  brand-like input. The scraped Kaggle dataset is not used (unclear upstream rights).
- **Consequences:** Smaller coverage at first; unknown brands ask the user for the generic name.

## ADR-003 Background work without a queue
- **Context:** OCR of one photo takes ~1–3 s; ingestion is an operator task.
- **Decision:** Synchronous OCR in FastAPI's thread pool, ingestion as a CLI, FastAPI
  `BackgroundTasks` for small follow-ups. No Celery/RQ/Redis.
- **Consequences:** Two fewer services to run on a modest machine. Revisit if a slow vision-LLM
  OCR adapter becomes the default.

## ADR-004 Offline checks
- **Context:** Users often have poor connectivity; checking medicines is the core task.
- **Decision:** The PWA caches names plus an interaction subset and runs a TypeScript port of the
  engine. The Python engine is the reference; shared JSON test vectors must pass in both.
- **Consequences:** Two implementations to maintain; offline results on uncached pairs are
  labelled "partial check".

## ADR-005 Route-specific DDInter entries are excluded
- **Context:** DDInter lists route-specific entries separately, e.g. "Timolol (ophthalmic)" next to
  "Timolol". 168 of 1,971 DDInter drugs are route-specific. Our model works at ingredient level
  and cannot tell whether a user's timolol is eye drops or tablets.
- **Options:** merge them into the base ingredient; exclude them; model route per medicine.
- **Decision:** Exclude (the systemic entry is still loaded). Non-route qualifiers such as
  "Insulin human (zinc)" or "Salicylic acid (sodium)" do map to the base ingredient.
- **Consequences:** No eye-drop/skin-cream warnings are attributed to tablets (fewer false alarms),
  but interactions specific to topical/ophthalmic forms are missed. Listed in
  `backend/data/reports/ddinter_unmapped.csv`; revisit when dose form is captured per medicine.

## ADR-006 Conservative name mapping between datasets
- **Context:** DDInter, openFDA and the India brand table name drugs differently from RxNorm
  ("Acetylsalicylic acid", "METFORMIN HYDROCHLORIDE").
- **Decision:** Map only by exact normalised name: locally (ingredients, salt forms), then the
  RxNav API restricted to *exact* matches in any source vocabulary (cached on disk). Never
  approximate matching. Names learned this way are saved as synonyms (dataset `rxnorm_api`).
- **Consequences:** Some drugs stay unmapped (reported, not guessed); no warning is ever
  attached to the wrong ingredient by a fuzzy guess.

## ADR-007 Contraindicated pairs from MED-RT
- **Context:** DDInter has no "contraindicated" level. MED-RT lists drug-class contraindications
  (e.g. amiodarone with fluoroquinolones).
- **Decision:** Load MED-RT `CI_ChemClass` as `contraindicated` pairs; a class is expanded to
  ingredients via FDA chemical-structure membership in RxClass. Each pair cites the MED-RT class.
- **Consequences:** Contraindicated warnings are sourced, not invented. MED-RT's licence is not
  yet confirmed (NLM page needs JavaScript); flagged as an open item before public deployment.

## ADR-008 Indian brand sources and verification
- **Context:** No open Indian brand registry exists; most composition pages are pharmacy listings.
- **Decision:** Hand-curated rows (`india_brands.csv`) cite a source page and its type
  (`manufacturer` / `regulator` / `pharmacy_listing`). A script fetches every page and records the
  composition quote and date (`india_brands_verified.csv`). Only verified rows whose ingredients
  all map to RxNorm are loaded; a partially mapped combination is rejected.
- **Consequences:** Small coverage (25 brands at first), but every brand shown can be traced to
  a page anyone can open. Rows still need a pharmacist's review (recorded in `verified_by`).

## ADR-009 Name normalisation: in-memory, layered, confidence-gated
- **Context:** Input is messy ("Crocin 650", "paracetmol", "amox/clav", OCR "Metf0rmin").
  A wrong match silently changes which warnings a pharmacist sees.
- **Options:** Postgres pg_trgm queries; in-memory rapidfuzz; an ML/embedding matcher.
- **Decision:** A pure, deterministic in-memory matcher (`app/core/normalise`) over ~73k names
  (~14.5k short names for fuzzy search), loaded once from the database (<1 s; ~1.6 ms per line).
  Layers, strongest first: exact full line (1.00) → exact without strength/form (0.98) →
  curated abbreviation incl. combinations (0.95) → OCR digit fixes (0.92) → typed combinations
  (min of parts × 0.98) → whole-word prefix (0.85 if one drug, 0.55 if several) → fuzzy
  (similarity-based; ≤4 chars capped at 0.55, 5–6 chars at 0.75) → optional RxNav approximate
  suggestions (capped at 0.75). Thresholds: ≥0.90 resolved, 0.60–0.90 confirm, <0.60 the user
  picks from candidates. India brands rank first on exact ties (Crocin = paracetamol).
  pg_trgm stays indexed for future server-side search, but isn't used by the matcher.
- **Consequences:** Same input → same output, testable without a database, and the same logic
  can be ported to the offline PWA. Thresholds are provisional; Stage 10 calibrates them on the
  ≥200-case evaluation set. A near-tie between different drugs or a prefix shared by several
  drugs is never auto-accepted (e.g. "insulin" lists insulin types instead of guessing "inulin").

## ADR-010 Rule-based, deterministic interaction engine (not ML)
- **Context:** Output is safety-critical and must be explainable to a pharmacist and auditable
  for a research paper.
- **Options:** learned DDI prediction (e.g. embedding/graph models); deterministic lookups plus a
  declarative rule table.
- **Decision:** `app/core/engine` is pure and deterministic. Pairwise findings come only from
  datasets (DDInter, MED-RT, FDA label text); duplicate-therapy and 3+ drug rules come only from
  `app/core/engine/rules.yaml` (groups by FDA EPC, exact WHO ATC level-4 codes, reviewed label
  flags, or named ingredients). Every finding carries its evidence records; the rule table
  itself is cited (`rules.yaml` v1) for rule-based findings.
- **Consequences:** No predictions of unknown interactions (recall is bounded by the sources),
  but every warning is reproducible and traceable, and changes are reviewable diffs. ATC prefix
  matching is deliberately unsupported: ATC lists aspirin under N02AJ ("opioids in combination")
  and glucosamine under M01AX; exact codes avoid both traps (tested).

## ADR-011 Alert-fatigue controls in the engine
- **Decision:** (1) A 2-drug rule or duplicate-class finding about a pair that already has a
  pairwise finding is merged into that card (`related`, `related_rules`), raising its severity if
  the rule is stricter, instead of a second card. (2) Ingredients inside one combination product
  are not paired with each other (the combination is intended). (3) DDInter "Unknown" grades and
  label-text-only mentions are reported with severity `unknown` and are not counted in
  `attention_count`. (4) Patient-context MED-RT contraindications are findings; label excerpts
  for the selected context are separate "check the label" notes, never ranked warnings.
- **Consequences:** Fewer duplicate cards while nothing is dropped. The results screen (Stage 7)
  still needs a headline policy; proposed: headline = contraindicated + major; moderate shown as
  "worth checking"; unknown collapsed. Thresholds are revisited with evaluation data in Stage 10.

## ADR-012 Recall and alert flagging in three tiers
- **Context:** Most recalls concern other products. Flagging every same-ingredient recall as a
  warning would alarm staff about medicines that are fine (alert fatigue), while a listed batch
  in the pharmacist's hand needs immediate attention.
- **Decision:** `app/core/recalls` matches each medicine against recall/alert records in tiers:
  **batch** (the batch number the user enters is listed; always "serious"), **product** (same
  brand or RxNorm product; level from the alert: CDSCO spurious / US Class I = serious, CDSCO
  NSQ / US Class II = warning, Class III = info), and **ingredient** (different product, same
  ingredient; information only, summarised per medicine and region, 3 most recent shown).
  Brand matching is exact or prefix-with-space on strength-free names ("telma" matches
  "Telma 40" and "Telma H", not "Telmax"). Batches shorter than 5 characters are ignored.
  A physical-verification checklist accompanies every result; each item names its source (CDSCO
  QR-code guidance and FAQ, US FDA counterfeit-medicine page) or says "general good practice".
- **Consequences:** The app never claims to detect fakes; it points to official alerts and an
  inspection checklist. Batch matching only works if staff type the batch number.

## ADR-013 CDSCO alerts: partial coverage, strict validation
- **Context:** CDSCO's NSQ/spurious lists are monthly PDF tables. The listing page stops in
  mid-2025; an Aug-2025 scanned notice (OCR'd with our Tesseract) points to a "new searchable
  link" at the same URL, but no newer machine-readable alerts could be found (the alternative
  `cdsco.mohfw.gov.in` host has a certificate mismatch; its consumer page is a 2018 archive).
- **Decision:** Load the alert PDFs published since 2023-07 that pass validation (serial numbers
  1..N with section restarts allowed, product + batch on every record, column counts match the
  header); reject whole files otherwise; keep only unexpired batches; link ingredients only when
  the Stage 3 normaliser resolves the generic name; keep brand names from parentheses.
- **Consequences:** India alerts are incomplete and end in mid-2025; this is stated in the
  dataset limitations and must be shown in the UI. WHO Medical Product Alerts were assessed and
  deferred: the list exposes only ~10 alerts without JavaScript, and affected batches are in
  narrative text or images, so extraction would be unreliable (future work).

## ADR-014 API shape: one check call, never guess, compact responses
- **Context:** Cheap phones on slow networks; staff need one answer, and unclear items must not
  silently change the result.
- **Decision:** `POST /api/v1/check` returns everything for one screen (headline, findings,
  check-the-label notes, recall flags, checklist, data versions, disclaimer). Items that are not
  "resolved" (≥0.90) and have no user selection are returned in `unresolved` with candidates and
  are excluded until the user picks one. A selection must name known RxCUIs (422 otherwise).
  Headline (`app/core/summary.py`): needs attention = contraindicated/major findings + medicines
  with a serious recall flag (counted once per medicine); worth checking = moderate findings +
  medicines with recall warnings. Recall brand matching applies only to medicines identified as
  a brand (generics would otherwise match US records whose "brand" field is the generic name);
  same brand name = "product", same brand family (e.g. Telma H for Telma 40) = "related", capped
  at warning. Responses are gzip-compressed (5-drug check: 71 KB → 12 KB). Per-IP rate limits
  (slowapi; search 120/min, normalise 60/min, check 30/min). Invalid input is always 422, even
  before data is loaded (the normaliser is fetched inside handlers, not as a dependency).
- **Consequences:** Measured on this machine: 5-drug check p50 ~130 ms, p95 ~190 ms. No accounts,
  no request bodies stored or logged.

## ADR-015 Accessible colour use of the brief's palette
- **Context:** Measured WCAG 2.1 contrast on white: moderate amber #E3A72F 2.1:1 (fails even for
  icons, which need 3:1), accent #E07A5F 2.95:1, major #D9622B 3.7:1 and minor #7A9A3A 3.2:1
  (fail for text, which needs 4.5:1), border #E6DCCB 1.4:1 (too faint for form fields).
- **Decision:** Keep the brief's colours for fills, tints and card stripes; add "-ink" shades of
  the same hues for text, icons and focus rings (major #B04A18 5.5:1, moderate #8A5B00 5.9:1,
  minor #56702A 5.6:1, accent #B5523A 4.7:1 on cream) and a form-field border #9C866D (≥3.2:1).
  Severity is always icon + text label + colour.
- **Consequences:** The warm character is preserved and every text/icon pairing meets AA.

## ADR-016 Results screen built for small phones
- **Decision:** Order = headline → needs attention → recalls/alerts (+ checklist) → duplicates →
  worth checking → check-the-label notes → other (collapsed) → careful "no known issues" →
  sources. One recall card per medicine (its most serious alert), further alerts for that
  medicine collapsed; label quotes collapsed to one line each; Simple/Professional toggle (a
  per-device preference in localStorage, not patient data); medicine list in sessionStorage only.
  Verified in a real browser at 360 px: no horizontal overflow, interactive targets ≥44 px.

## ADR-017 Prescription OCR: Tesseract by default, vision-LLM optional
- **Context:** Staff photograph prescriptions on cheap phones; many are handwritten. Misread
  names would produce wrong safety results.
- **Options:** Tesseract (free, runs on our server, private, weak on handwriting); a vision-LLM
  (better on handwriting, costs money per image, sends the image to a third party).
- **Decision:** `app/core/ocr` with a pluggable `OcrEngine`. Default `TesseractEngine` (psm 4)
  after pre-processing: 3x3 median (speckle, before upscaling), upscale to ~1800 px, non-local-means
  denoise, CLAHE, deskew (median angle of line blobs, ±15°), adaptive threshold. Optional
  `VisionLLMEngine` (Claude, `claude-opus-5-5`, low effort, strict JSON schema, server-side refusal
  fallback) only with `OCR_ENGINE=vision_llm` + key + `pip install -e ".[llm]"`; the API reports
  `sends_image_off_device`. Safety: a line is "resolved" only if the name resolves AND Tesseract's
  confidence is ≥75 and the name has ≥4 letters; vision-LLM lines are never auto-resolved; a line
  is a medicine candidate only if it looks like an order ("Tab…", "1.") or fully resolves; header
  lines (patient, doctor, clinic, phone) are never cropped; nothing is added without a tap. Images
  are processed in memory (8 MB cap, type checked by decoding) and never stored.
- **Consequences:** Printed prescriptions work well in tests (clean, rotated ±7°, speckled, serif,
  small photos). Handwriting will often fail: the UI says so and shows each crop beside its
  reading. Accuracy by printed/handwritten is measured in Stage 10.

## ADR-018 Offline pack: contents, format and parity with the Python engine
- **Context:** ADR-004 chose an offline subset plus a TypeScript engine. The full interaction
  table (215k DDInter rows + MED-RT) is too big for a cheap phone, and every offline warning must
  still cite its source records (honesty rule 3).
- **Decision:** `GET /api/v1/offline-pack` (built by the pure `app/core/offline_pack.py`, cached
  gzipped in memory, prebuilt in the background at startup, ETag = content hash) holds:
  every ingredient name; the searchable names (India brands, generics, synonyms, US brands);
  pairs whose overall severity is contraindicated or major, plus moderate pairs where both
  ingredients are "common" (in an RxNorm prescribable product or a curated Indian brand); each
  pair with ALL its source records (dataset, record id, URL; URLs stored as per-dataset prefix +
  rest, lossless); rule-group membership with the evidence the engine itself cites (computed by
  calling the engine, not re-implemented); the rule table, pair wording, disclaimer, absence note
  and the pack-verification checklist. Real data: 130,615 pairs, 16,828 names, 8.6 MB JSON,
  1.43 MB gzipped. It is downloaded only when the user taps "Save for offline use" and kept in
  Cache Storage (status record in localStorage; drug data only, nothing about patients).
- **Not offline (said on screen, never silently):** minor/ungraded pairs, label-text mentions,
  patient-context checks, label notes, recalls and alerts (the checklist is still shown), OCR.
  Typed names resolve offline only on an exact name match; otherwise the user picks (rule 8).
- **Parity:** `src/lib/offline/engine.ts` is a line-by-line port of `engine.py`. Shared vectors
  (`backend/tests/vectors/offline_engine.json`, 17 cases covering every finding type and merging)
  are generated by the Python engine from facts decoded out of the pack; pytest fails if they are
  stale, Vitest requires identical output. A real-data check (`backend/scripts/offline_parity.py`
  + `parity.test.ts`) gave identical results on 500/500 random medicine lists (381 with findings).
- **Consequences:** Two engines to keep in step, enforced by tests. Offline results are clearly
  labelled partial and recommend re-checking online. Distributing the pack distributes DDInter
  data: the pack carries the CC BY-NC-SA notice.

## ADR-019 PWA, printing and languages
- **PWA:** vite-plugin-pwa (generateSW, autoUpdate) precaches the app shell only; API responses
  are never cached by the service worker (stale safety answers are worse than none). Queries
  with an offline path use React Query `networkMode: "always"`, otherwise they pause while the
  phone reports no network (found by the browser audit; regression-tested).
- **Print / save as PDF:** print CSS (white page, link URLs written out, controls hidden), every
  collapsed section opened on `beforeprint` and restored after; the printout lists the medicines
  checked (names only) and the print time.
- **Languages:** English is the source. Hindi and Kannada cover all interface text and are
  machine translations not yet reviewed by native speakers; whenever one is selected a banner
  says so and that medicine warnings and sources stay in English (finding text is generated by
  the server from English templates; translating it safely needs reviewed templates). Keys and
  placeholders are tested to match English. Choice stored per device; `<html lang>` follows it.
- **Accessibility:** `scripts/a11y_audit.py` runs axe-core (WCAG 2.0/2.1/2.2 A+AA) in Chromium at
  360 px on 13 screens/states (incl. offline result, print, OCR results, Hindi, Kannada) and
  checks overflow and 44 px targets: 0 problems after fixes (small About-page links; a malformed
  dataset source URL now shown as a repository path).

## ADR-020 Evaluation harness
- **Decision:** `/evaluation` (mounted into the backend container) measures the real modules
  against the loaded data: name recognition (222 cases, hand-written + seeded typos, references
  resolved by exact name only), interactions against CRESCENDDI (independent BNF/ANSM/Micromedex
  reference set, CC0), OCR on synthetic printed pages and handwriting-style fonts (explicitly an
  upper bound; no real handwriting was available), and server latency. Results are JSON;
  `REPORT.md` is generated from them, never typed by hand. Safety metrics come first: wrong
  auto-accepts (names and OCR) and "needs attention" false alarms.
- **Rules for ourselves:** no tuning of the matcher on the evaluation cases; reference errors and
  bugs found by the evaluation are fixed only with a regression test and disclosed in
  METHODOLOGY.md with before/after numbers (one parser fix: instruction phrases such as "empty
  stomach").
- **Consequences:** The numbers are reproducible (seeded) but not blinded (the same team wrote
  the cases). Usability with real staff and real handwritten prescriptions remain unmeasured
  and are listed as such.
