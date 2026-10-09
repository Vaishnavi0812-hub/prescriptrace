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

**Status:** Stage 1 of 10 (skeleton). The full README (screenshots, architecture, data licences,
evaluation) comes in Stage 10. See [docs/PLAN.md](docs/PLAN.md) and
[docs/DATA_FEASIBILITY.md](docs/DATA_FEASIBILITY.md).

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

Other tasks: `.\scripts\dev.ps1 test | lint | fmt | migrate | logs | down`
(`make <target>` does the same from bash).

## Data licences (summary)

The interaction data (DDInter 2.0) is **CC BY-NC-SA 4.0: non-commercial use only**. See
[docs/DATA_FEASIBILITY.md](docs/DATA_FEASIBILITY.md) for every source and its licence.
