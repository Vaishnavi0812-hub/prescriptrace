# PrescripTrace

Medication safety and counterfeit-risk **checker** for small pharmacies and clinics.
Enter or photograph a list of medicines and get one prioritised, plain-language safety summary:
known interactions, duplicated ingredients, and official recall/quality alerts. Every warning
cites its source.

> **Decision support only.** PrescripTrace is not a diagnostic or prescribing tool. The absence
> of a warning is not proof of safety. Consider confirming with the prescriber.
>
> **It does not detect fake pills.** "Counterfeit risk" means matching medicines against official
> recall and alert lists, plus a physical-verification checklist (packaging, batch, seal, price,
> supplier).

**Status:** Stages 1–4 of 10 done: real data loaded (RxNorm, DDInter, openFDA recalls and
labels, RxClass/MED-RT, curated Indian brands), drug-name normalisation and the interaction
engine are working and tested. The user interface arrives in Stage 7. The full README
(screenshots, architecture, evaluation) comes in Stage 10. See [docs/PLAN.md](docs/PLAN.md),
[docs/DATA_FEASIBILITY.md](docs/DATA_FEASIBILITY.md) and [docs/DECISIONS.md](docs/DECISIONS.md).

## Run it on Windows (Docker)

Prerequisites: Docker Desktop (WSL 2 backend) and Git. Node 22 is only needed to run the
frontend tests outside Docker. Tesseract OCR is installed inside the backend image, so you don't
need it on Windows.

```powershell
git clone <repo-url> prescriptrace; cd prescriptrace
.\scripts\dev.ps1 up        # creates .env from .env.example on first run
```

- App: http://localhost:5173
- API docs: http://localhost:8000/api/docs

Load the datasets (first run takes 1–2 hours, mostly API calls; later runs reuse the cache):

```powershell
docker compose run --rm backend python -m app.ingest all
```

Other tasks: `.\scripts\dev.ps1 test | lint | fmt | migrate | logs | down`
(`make <target>` does the same from bash).

## Data licences (summary)

The interaction data (DDInter 2.0) is **CC BY-NC-SA 4.0: non-commercial use only**. See
[docs/DATA_FEASIBILITY.md](docs/DATA_FEASIBILITY.md) for every source and its licence.
