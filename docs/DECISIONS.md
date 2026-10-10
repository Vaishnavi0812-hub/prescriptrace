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
