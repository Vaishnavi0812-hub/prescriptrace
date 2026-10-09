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
