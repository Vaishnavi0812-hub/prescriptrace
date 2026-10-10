# PrescripTrace — project guide for Claude

Medication safety and counterfeit-risk *checker* for small pharmacies and rural/low-resource
clinics (India first). Users: pharmacists, clinic nurses, pharmacy students on cheap Android
phones with unreliable internet. Core journey (< 60 s): enter medicines (typed or photographed
prescription) → confirm recognised ingredients → optional patient context (age group,
pregnancy, renal/hepatic) → one prioritised, plain-language safety summary with sources.

## Status
- [x] Step 1: CLAUDE.md
- [x] Step 2: data feasibility report — approved 2026-10-09 (see `docs/DATA_FEASIBILITY.md`)
- [x] Step 3: schema / OpenAPI / folders / screen list — approved (`docs/PLAN.md`)
- [x] Stage 1: skeleton, docker-compose, DB + initial migration, CI
- [x] Stage 2: ingestion with real data (user will run everything together later)
- [x] Stage 3: normalisation module + tests (`app/core/normalise`, ADR-009)
- [x] Stage 4: interaction engine + tests (`app/core/engine`, rules in `rules.yaml`, ADR-010/011)
- [x] Stage 5: recall/alert flagging (`app/core/recalls`, CDSCO alerts, checklist; ADR-012/013)
- [x] Stage 6: API layer (`app/api/v1.py`, `app/services/check_service.py`, ADR-014)
- [x] Stage 7: frontend core flow (search, confirm, context, results, About; ADR-015/016)
- [ ] Stages 8–10 (see "Build stages" below). Stop for review after each stage; commit per stage.

## Approved data sources
- Interactions: DDInter 2.0 (CC BY-NC-SA 4.0, **non-commercial**; all 14 ATC files incl. unlisted
  C/G/J/M/N/S; server flaky → resumable download w/ backoff). Supplementary: openFDA label text.
- Names: RxNorm Prescribable Content (public domain, local) + RxNorm API fallback. RxNorm
  approximate match is **never** trusted alone for brand-like tokens (Crocin→saffron bug).
- Indian brands: curated table, every row cites a source. No Kaggle scrape.
- Classes: RxClass EPC + MED-RT; QT/serotonergic/CNS-depressant flags from label text with a
  committed human-review file.
- Recalls: openFDA enforcement bulk + CDSCO NSQ/spurious PDFs (validated; coverage ends mid-2025,
  newer CDSCO portal not accessible). WHO alerts deferred (not reliably extractable).
- Excluded: RxNav interaction API (404), TWOSIDES, DrugBank. Eval: CRESCENDDI (CC0).

## Honesty rules (non-negotiable)
1. Decision **support** only. Never instruct to stop/change therapy. Use phrasing like
   "Consider confirming with the prescriber." Show a non-intrusive disclaimer.
2. "Counterfeit risk" = matching against official recall/alert data + a physical-verification
   checklist. Never claim to detect fake pills.
3. Every warning must trace to a source record (dataset, record ID, dataset date). Unsourced → not shown.
4. An LLM (optional, off by default) may only rephrase facts already retrieved from the DB.
   It never adds interactions, severities or claims. The app must work fully with templates.
5. No patient names/IDs/free-text identifiers stored. Medication lists are session-only in the
   browser by default; saved history is opt-in, on-device, clearly labelled.
6. Never substitute mock/fake data for a real source. If a source is blocked or changed:
   stop, tell the user, propose the next-best free alternative.
7. Absence from our data ≠ proof of safety. Say so wherever "no issues found" is shown.
8. Below the normalisation confidence threshold, never guess — ask the user to pick.
9. Don't claim something works unless it was run; show real test output.

## Stack
- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, PostgreSQL + pg_trgm,
  rapidfuzz, pytesseract + OpenCV (Tesseract installed in the backend Docker image).
- Ingestion: idempotent CLI `python -m app.ingest <source>`; dataset metadata (source, version,
  download date, record counts, licence) stored in DB and surfaced in the UI.
- Frontend: React + Vite + TypeScript, Tailwind (design tokens), React Query, React Router,
  vite-plugin-pwa, i18n (English default; Hindi/Kannada marked "needs review").
- Dev: Windows + PowerShell + VS Code; `docker compose up` runs db + backend + frontend.
- Quality: pytest, ruff, mypy; Vitest + RTL, eslint, tsc; GitHub Actions CI.

## Conventions
- The interaction engine and normaliser are pure, deterministic modules with no web or DB imports
  in their core logic; they are unit-testable from plain data.
- Cumulative-risk rules live in a declarative, documented rule table (not hidden logic).
- Severity order: contraindicated > major > moderate > minor. Never rely on colour alone
  (icon + text label always).
- Design tokens (warm palette; no pure black, no cool grey): bg #FBF7F0, surface #FFFFFF,
  primary #1F5F4A (hover #164536), accent #E07A5F, text #2B2118, muted #6B5B4D,
  border #E6DCCB; severity: contraindicated #B3261E, major #D9622B, moderate #E3A72F,
  minor #7A9A3A, none = primary.
- Touch targets ≥ 44px, WCAG AA, works at 360px width, grade-8 reading level.
- Secrets only in `.env` (never committed); `.env.example` documents every variable.
- Architecture decisions go in `docs/DECISIONS.md` (ADR style).
- Downloaded datasets go under `data/raw/` (git-ignored); never edit raw files by hand.

## Commands
Windows PowerShell (`scripts/dev.ps1`; Makefile has the same targets for bash):
- `.\scripts\dev.ps1 up` — build + start db/backend/frontend (creates `.env` from `.env.example`)
  → frontend http://localhost:5173, API docs http://localhost:8000/api/docs
- `.\scripts\dev.ps1 test` — backend pytest (in Docker, against Postgres) + frontend Vitest
- `.\scripts\dev.ps1 lint` — ruff check, ruff format --check, mypy --strict; eslint, tsc
- `.\scripts\dev.ps1 fmt` · `migrate` · `logs` · `down` · `shell-db`
- New migration: `docker compose run --rm backend alembic revision --autogenerate -m "msg"`,
  then review it and run `fmt` (autogenerate output isn't ruff-clean).
- Frontend deps are installed on the host too (`cd frontend; npm ci`) for editor tooling and tests.

Data ingestion (run in the backend container; order matters, `all` runs them in order):
- `docker compose run --rm backend python -m app.ingest all` (or one of: rxnorm, ddinter,
  recalls, cdsco, labels, classes, india_brands, synonyms). Idempotent; `--refresh` re-downloads.
- Raw files → `data/raw/` with `<file>.complete` markers; API responses cached in `data/cache/`
  (delete a cache folder to refresh it). First full run ≈ 1–2 h (RxClass/RxNav API calls).
- India brands: edit `backend/data/curated/india_brands.csv`, then
  `docker compose run --rm backend python -m app.ingest.india_brands verify` (fetches every source
  page, writes `india_brands_verified.csv`), then `python -m app.ingest india_brands`.
- Label class flags: review `backend/data/reports/label_flag_candidates.csv`; record decisions in
  `backend/data/curated/label_flag_review.csv` (flag, ingredient_rxcui, decision=accepted|rejected).
- Reports (committed): `backend/data/reports/ddinter_unmapped.csv`, `label_flag_candidates.csv`.

Normaliser: `Normaliser(load_vocabulary(session)).normalise(text)`; thresholds in config
(`NORMALISE_AUTO_ACCEPT`, `NORMALISE_CONFIRM_MIN`). Add shorthand to `ABBREVIATIONS` in
`app/core/normalise/matcher.py` only if the expansion is an exact vocabulary name.

Engine: `check(medicines, load_snapshot(session, rxcuis), PatientContext(...))`. Rules live in
`backend/app/core/engine/rules.yaml` (validated on load; `tests/db/test_engine_real.py` checks every
selector exists in the data). Never write rule text that tells anyone to stop/change a medicine
(`FORBIDDEN_PHRASES` test).

Editing gotcha: do not use sed or Python heredocs to write backslash escapes (newline, word
boundary) into source files (Git Bash/Python turned them into real newlines/backspaces three times). Use the
Edit tool for such changes, and never `# fmt: skip` inside an expression (ruff RUF028).

API: `/api/v1/drugs/search`, `/normalise`, `/check`, `/datasets`, `/health`; docs at `/api/docs`.
The vocabulary loads at startup (`app/services/state.py`); after re-ingesting data, restart the
backend. Tests disable rate limits and RxNav calls via env in `tests/conftest.py`.

Ingestion gotchas: Alembic autogenerate misses CHECK-constraint changes (write those migrations by
hand with `op.f(name)`; `tests/db/test_constraints.py` catches drift). RxNorm RRF relation rows read
"RXCUI2 RELA RXCUI1". Never use approximate RxNorm matching when mapping between datasets.

Gotchas: Docker Desktop sometimes reports "unable to start" — quitting and relaunching it fixed
it. In PowerShell scripts don't use `$ErrorActionPreference = "Stop"` around docker/npm (PS 5.1
treats their stderr progress as errors). npm install on this machine is slow (~15 min).

## Build stages
1 skeleton/docker/DB/migrations/CI · 2 ingestion (real data) · 3 normalisation + tests ·
4 interaction engine + tests · 5 recall/alert flagging · 6 API · 7 frontend core flow ·
8 OCR flow · 9 PWA/offline, print/PDF, i18n, a11y · 10 evaluation harness, README, DECISIONS, polish.
