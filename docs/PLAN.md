# PrescripTrace — build plan (step 3, for approval)

## 1. Database schema (PostgreSQL 16 + pg_trgm)

Every row derived from a dataset carries `dataset_id` (FK → `dataset`) and the upstream record
key, so any warning can be traced back to its source record and dataset date.

### Provenance
| table | key columns |
|---|---|
| `dataset` | id, code (`rxnorm_prescribe`, `ddinter`, `openfda_enforcement`, `openfda_label`, `rxclass_epc`, `medrt`, `india_brands`, `cdsco_nsq`…), version, source_url, licence, licence_url, downloaded_at, record_count, sha256, notes |
| `ingest_run` | id, dataset_id, started_at, finished_at, status, rows_in, rows_out, rows_rejected, log |

### Drug vocabulary
| table | key columns | notes |
|---|---|---|
| `ingredient` | rxcui PK, name, name_norm | RxNorm IN/PIN level, the unit everything joins on |
| `drug_name` | id, text, text_norm (trigram GIN index), kind (`ingredient`/`brand`/`synonym`/`ddinter`/`india_brand`), rxcui → product or ingredient, country, dataset_id, source_ref | every searchable string: generic, US brand, Indian brand, INN synonym ("paracetamol", "acetylsalicylic acid") |
| `product` | rxcui PK, name, tty (SCD/SBD/GPCK/BPCK), dose_form, brand_name, dataset_id | |
| `product_ingredient` | product_rxcui, ingredient_rxcui, strength_value, strength_unit | handles combination products |
| `india_brand` | id, brand, strength_text, manufacturer, dose_form, source_type (`cdsco_list`/`manufacturer_page`/…), source_url, source_quote, verified_by, verified_at | curated; each row → ≥1 `india_brand_ingredient` |
| `india_brand_ingredient` | india_brand_id, ingredient_rxcui, strength_value, strength_unit | |

### Classes and flags
| table | key columns |
|---|---|
| `drug_class` | id, source (`EPC`/`MEDRT_MOA`/`ATC`/`LABEL_FLAG`), class_id, name |
| `ingredient_class` | ingredient_rxcui, drug_class_id, dataset_id, evidence (label set_id + quoted sentence for LABEL_FLAG), review_status (`auto`/`accepted`/`rejected`) |

### Interactions and context
| table | key columns | notes |
|---|---|---|
| `interaction` | id, ingredient_a, ingredient_b (a < b), severity (`contraindicated`/`major`/`moderate`/`minor`/`unknown`), provenance (`structured`/`label_text`), dataset_id, source_ref (DDInter IDs or label set_id), evidence_text, source_url | unique on (a, b, dataset_id) |
| `context_note` | id, ingredient_rxcui, context (`pregnancy`/`renal`/`hepatic`/`paediatric`/`geriatric`), kind (`contraindication` from MED-RT \| `check_label` from label section), text, dataset_id, source_ref | never a dose adjustment we wrote ourselves |
| `label_excerpt` | set_id PK, ingredient_rxcuis[], effective_time, sections jsonb (drug_interactions, contraindications, pregnancy, use_in_specific_populations, warnings…), dataset_id | trimmed subset of openFDA labels |

### Recalls / alerts
| table | key columns |
|---|---|
| `recall` | id, region (`US`/`IN`/`WHO`), source_record_id (openFDA recall_number / CDSCO row / WHO alert no.), classification, reason, firm, status, report_date, product_description, lot_info, dataset_id, source_url |
| `recall_link` | recall_id, ingredient_rxcui, product_rxcui (nullable), brand_text, match_basis (`rxcui`/`ndc`/`name`) |

No table stores patient data. Request logs keep only timing and counts, never medication lists.

## 2. Core modules (pure Python, no web/DB imports)

```
app/core/normalise/   tokenise → strip strength/form → candidate generation
                      (exact · India brand table · trigram · rapidfuzz · RxNorm API fallback)
                      → score fusion → {resolved | ambiguous(candidates) | unknown}
app/core/engine/      inputs: ingredients[], context, KnowledgeSnapshot (plain dataclasses)
                      pairwise.py · duplicates.py · cumulative.py (rules.yaml) · context.py
                      rank.py → list[Finding]
app/core/recalls/     match.py → exact_product | same_ingredient
app/core/explain/     templates (en/hi/kn keys) + optional LLM rephraser (validated: output may
                      not contain drug names/severities not present in the input facts)
app/core/ocr/         OcrEngine protocol; TesseractEngine (default); VisionLLMEngine (env flag)
```

- **Confidence** is our own, not RxNorm's score: exact or curated-brand match = 1.0. Fuzzy
  matches get a score from edit similarity plus agreement between methods, calibrated on the
  200-case eval set. Thresholds are set in config: ≥ 0.90 auto-resolve, 0.60–0.90 confirm,
  < 0.60 show candidates only. Calibration may change these.
- **Cumulative rules** live in `rules.yaml`, e.g.
  `{id: QT_STACK, classes_any: [LABEL_FLAG:qt_prolonging], min_count: 2, severity: major, explain_key: …}`,
  `{id: BLEED_STACK, groups: [[EPC:NSAID],[EPC:anticoagulant, EPC:platelet_inhibitor]], …}`.
  Each rule cites its rationale and is unit-tested.
- **Ranking:** severity, then provenance (structured before label text), then number of drugs involved.

## 3. API contract (FastAPI, OpenAPI generated at `/api/docs`)

| method | path | purpose |
|---|---|---|
| GET | `/api/v1/drugs/search?q=&limit=` | autocomplete: `[{display, generic, brand, ingredients[], strength, match_kind, confidence}]` |
| POST | `/api/v1/normalise` | `{lines: [str]}` → per line `{status, best, candidates[], confidence, parsed_strength}` |
| POST | `/api/v1/check` | `{items: [{rxcui \| india_brand_id \| ingredient_rxcuis}], context: {age_group?, pregnant?, renal?, hepatic?}, detail: simple\|professional, lang}` → `{headline, findings[], recalls[], duplicates[], context_notes[], no_issue_pairs[], data_versions}` |
| POST | `/api/v1/ocr` | multipart image (≤ 8 MB, jpeg/png/webp) → `{lines: [{text, bbox, ocr_confidence, crop_png_b64, normalised}]}`. The image is processed in memory and never stored |
| GET | `/api/v1/datasets` | dataset versions, dates, licences, record counts (footer + About) |
| GET | `/api/v1/offline-pack?since=` | compact JSON (or gzipped) snapshot for the PWA: names + top-N interactions (see §6) |
| GET | `/api/v1/health` | liveness + DB + data freshness |

`Finding` = `{id, type: interaction|duplicate|cumulative|context, severity, drugs[], title,
what_it_means, what_to_consider, evidence: [{dataset, record_id, dataset_date, url, quote?}],
provenance: structured|label_text, confidence}`.

Rate limiting via `slowapi` (per IP, e.g. 60/min check, 10/min OCR); Pydantic limits (≤ 20 items,
strings ≤ 120 chars); CORS locked to the frontend origin.

**Background work:** FastAPI `BackgroundTasks` + CLI only, with no queue. OCR on one photo takes
about 1–3 s, so it runs synchronously in a thread pool. Ingestion is an operator CLI
(`python -m app.ingest …`), not a user request. A queue (Celery/RQ + Redis) would add two
services for no user-visible benefit at this scale; revisit if OCR moves to a slow vision-LLM.

## 4. Folder structure

```
/
├─ CLAUDE.md  README.md  docker-compose.yml  .env.example  Makefile  scripts/*.ps1
├─ .github/workflows/ci.yml
├─ docs/  DATA_FEASIBILITY.md  PLAN.md  DECISIONS.md  architecture.md
├─ backend/
│  ├─ Dockerfile (python:3.12-slim + tesseract-ocr + tesseract-ocr-hin/kan)
│  ├─ pyproject.toml  alembic.ini  alembic/versions/
│  ├─ app/
│  │  ├─ main.py  config.py  db.py  models/ (SQLAlchemy)  schemas/ (Pydantic)
│  │  ├─ api/v1/ (drugs, normalise, check, ocr, datasets, offline)
│  │  ├─ core/ (normalise, engine, recalls, explain, ocr)   ← pure, unit-tested
│  │  ├─ repo/ (DB → KnowledgeSnapshot adapters)
│  │  └─ ingest/ (__main__.py, rxnorm.py, ddinter.py, openfda.py, classes.py, india_brands.py, cdsco.py)
│  ├─ data/curated/ india_brands.csv · label_flag_review.csv · rules.yaml (committed)
│  └─ tests/ unit/ (normalise, engine, rules, recalls, ocr preprocessing) · api/ · fixtures/
├─ frontend/
│  ├─ vite.config.ts (vite-plugin-pwa)  tailwind.config.ts (design tokens)
│  └─ src/ app/ routes/ components/ features/{search,meds,results,scan,about}/
│          i18n/{en,hi,kn}.json  lib/{api,offline-db (IndexedDB)}  tests/
├─ data/raw/ (git-ignored downloads, with checksums)
└─ evaluation/ METHODOLOGY.md · normalisation_cases.csv (≥200, hand-checked) · run_*.py · results/
```

## 5. UI screens (mobile-first, 360px+)

1. **Check (home):** large "Add medicine" search with autocomplete (brand + generic + strength),
   "Scan prescription" button, medication chips/cards (strength, "Contains: …", remove),
   collapsible "About the patient (optional)": age group, pregnancy, kidney, liver. "Check
   safety" button. Footer: data-updated indicator, disclaimer link.
2. **Confirm matches** (inline sheet): for ambiguous/low-confidence entries, pick from
   candidates, "None of these", or retype.
3. **Scan:** camera/upload, then a processing skeleton, then a list of recognised lines, each with
   the image crop beside it and tap to accept, edit or remove. Low-confidence lines are not
   pre-accepted. "Add missing medicine".
4. **Results:** headline ("2 things need attention") → severity cards (icon + label + colour,
   "What this means" / "What to consider") → recall & alert flags with exact/same-ingredient badge
   and the physical-verification checklist → duplicate-therapy notes → patient-context notes
   ("check label") → careful "No known issues found in our data" → expandable evidence &
   sources. Simple/Professional toggle. Buttons: Print/Save PDF, Edit list.
5. **Print view:** handout version of the results, with no identifiers, dataset dates and the disclaimer.
6. **About & data:** what the app does and doesn't do, datasets table (version, date, licence,
   record counts, limitations), the counterfeit-risk explanation, disclaimer.
7. **Settings:** language (en/hi/kn, with "needs review" badge), opt-in on-device history (off by
   default, clearly labelled, with "clear all"), offline data download/refresh.
8. **States:** skeletons, empty, error (retry), offline banner, "data last updated" indicator.

## 6. Offline scope (realistic)

| Works offline | Needs connection |
|---|---|
| App shell, all screens, i18n | OCR (server-side Tesseract) |
| Autocomplete over a cached name list (~25k most common names + all India brands) | Live recall refresh |
| Typed checks using a cached interaction subset (all major/contraindicated pairs + all moderate pairs among the ~1,500 most common ingredients), class flags and rules | Pairs outside the cached subset (results page then says "partial check, offline") |
| Last results of the session | Dataset updates |

The PWA reuses the same rule table, compiled to JSON, and runs a small TypeScript port of the
engine for offline use. The Python engine stays the reference. Shared test vectors (JSON
fixtures) run in both pytest and Vitest to guarantee identical output.

## Approved 2026-10-09
Plan approved as written. Decisions on the two open points:
- **Offline engine:** build the TypeScript port with shared JSON test vectors (Python is the reference).
- **OCR languages:** English only in the image by default; `TESS_LANGS` build arg can add `hin kan`.

## 7. Risks / open items
- DDInter has no "contraindicated" level and no explanation text: contraindicated comes only from
  label text or MED-RT, and explanations come from templates.
- Indian brand coverage depends on how many rows we can verify. Unknown brands produce
  "not recognised, enter the generic name".
- Label-derived class flags need a human review pass (`label_flag_review.csv`).
- No permissive public prescription image set: OCR evaluation uses synthetic printed
  prescriptions plus a small self-made handwritten set.
