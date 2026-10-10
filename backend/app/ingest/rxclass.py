"""Drug classes and contraindications from NLM RxClass (one API call per ingredient, cached).

Loads three datasets so each keeps its own licence and provenance:
  * rxclass_fdaspl: FDA Established Pharmacologic Class (EPC) and mechanism (MOA), from labels.
  * medrt:          VA MED-RT contraindications: with diseases (→ pregnancy/renal/hepatic notes)
                    and with drug classes (→ 'contraindicated' interaction pairs).
  * atc:            WHO ATC level 1-4 groups, used internally for duplicate-therapy grouping only
                    (WHOCC reuse terms unverified, so ATC codes are never shown or exported).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import DatasetInfo, cached_json, chunks, ingest_run, upsert_dataset
from app.models import ContextNote, DrugClass, Ingredient, IngredientClass, Interaction

log = logging.getLogger("ingest.rxclass")

RXCLASS = "https://rxnav.nlm.nih.gov/REST/rxclass"
FDASPL = DatasetInfo(
    code="rxclass_fdaspl",
    name="FDA Established Pharmacologic Classes and mechanisms (via NLM RxClass)",
    source_url="https://lhncbc.nlm.nih.gov/RxNav/applications/RxClassIntro.html",
    licence="U.S. FDA data (public domain); NLM RxNav terms of service",
    licence_url="https://lhncbc.nlm.nih.gov/RxNav/TermsofService.html",
    region="US",
)
MEDRT = DatasetInfo(
    code="medrt",
    name="MED-RT contraindications (VA, via NLM RxClass)",
    source_url="https://lhncbc.nlm.nih.gov/RxNav/applications/RxClassIntro.html",
    licence="U.S. Government (VA) work; licence terms TO BE CONFIRMED (see DATA_FEASIBILITY.md)",
    region="US",
    limitations="Drug-class contraindications are expanded to ingredients using FDA "
    "chemical-structure class membership; a pair is shown as 'contraindicated' only where "
    "MED-RT lists the class.",
)
ATC = DatasetInfo(
    code="atc",
    name="WHO ATC groups, levels 1-4 (via NLM RxClass)",
    source_url="https://www.whocc.no/atc_ddd_index/",
    licence="© WHO Collaborating Centre; used internally for grouping only, not redistributed",
    limitations="Not shown in the UI or exported in offline data until reuse terms are checked.",
)

CONTEXT_WORDS = {
    "pregnan": "pregnancy",
    "renal": "renal",
    "kidney": "renal",
    "hepatic": "hepatic",
    "liver": "hepatic",
}
THREADS = 5  # with ~0.3 s latency this stays under NLM's 20 requests/second


def _classes_for(rxcui: str) -> list[dict[str, Any]]:
    data = cached_json(f"{RXCLASS}/class/byRxcui.json?rxcui={rxcui}", f"rxclass/byrxcui/{rxcui}")
    return (data.get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo") or []


def _chem_members(class_id: str) -> list[str]:
    url = (
        f"{RXCLASS}/classMembers.json?classId={class_id}"
        "&relaSource=FDASPL&rela=has_chemical_structure"
    )
    data = cached_json(url, f"rxclass/members_chem/{class_id}")
    members = (data.get("drugMemberGroup") or {}).get("drugMember") or []
    return [m["minConcept"]["rxcui"] for m in members]


def run(session: Session, refresh: bool = False) -> None:
    del refresh  # API responses are cached per call; delete data/cache/rxclass to refresh
    now = datetime.now(UTC)
    # RxClass has no release number; record the date responses were first fetched (cached).
    version = f"RxClass API, fetched {now.date().isoformat()}"
    ds_fda = upsert_dataset(session, FDASPL, downloaded_at=now, version=version)
    ds_medrt = upsert_dataset(session, MEDRT, downloaded_at=now, version=version)
    ds_atc = upsert_dataset(session, ATC, downloaded_at=now, version=version)
    ingredients: dict[str, str] = {
        r: n for r, n in session.execute(select(Ingredient.rxcui, Ingredient.name_norm))
    }
    by_name = {name: rxcui for rxcui, name in ingredients.items()}

    with ingest_run(session, ds_medrt) as stats:
        log.info("fetching RxClass for %s ingredients", len(ingredients))
        with ThreadPoolExecutor(THREADS) as pool:
            infos = dict(zip(ingredients, pool.map(_classes_for, ingredients), strict=True))
        stats.rows_in = sum(len(v) for v in infos.values())

        class_rows: dict[tuple[str, str], str] = {}
        memberships: list[tuple[str, str, str, int]] = []  # rxcui, source, class_id, dataset
        ci_disease: list[tuple[str, str, str]] = []
        ci_chem: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for rxcui, items in infos.items():
            for item in items:
                concept = item["rxclassMinConceptItem"]
                cid, cname, ctype = concept["classId"], concept["className"], concept["classType"]
                src, rela = item.get("relaSource"), (item.get("rela") or "").lower()
                if src == "FDASPL" and rela in ("has_epc", "has_moa"):
                    source = "EPC" if rela == "has_epc" else "MOA"
                    class_rows[(source, cid)] = cname
                    memberships.append((rxcui, source, cid, ds_fda.id))
                elif src == "ATC" and ctype == "ATC1-4":
                    class_rows[("ATC", cid)] = cname
                    memberships.append((rxcui, "ATC", cid, ds_atc.id))
                elif src == "MEDRT" and rela == "ci_with" and ctype == "DISEASE":
                    ci_disease.append((rxcui, cid, cname))
                elif src == "MEDRT" and rela == "ci_chemclass":
                    ci_chem[rxcui].add((cid, cname))

        class_ids = _upsert_classes(session, class_rows)
        for ds in (ds_fda.id, ds_atc.id):
            session.execute(delete(IngredientClass).where(IngredientClass.dataset_id == ds))
        ic_rows = [
            {
                "ingredient_rxcui": r,
                "drug_class_id": class_ids[(s, c)],
                "dataset_id": d,
                "evidence": None,
                "review_status": "auto",
            }
            for r, s, c, d in {(m[0], m[1], m[2], m[3]) for m in memberships}
        ]
        for batch in chunks(ic_rows):
            session.execute(insert(IngredientClass), list(batch))
        stats.note(f"class memberships (EPC/MOA/ATC): {len(ic_rows)}; classes: {len(class_ids)}")

        notes = _context_notes(session, ds_medrt.id, ci_disease)
        pairs = _contraindicated_pairs(session, ds_medrt.id, ci_chem, by_name, ingredients)
        stats.rows_out = notes + pairs
        stats.note(f"MED-RT context contraindications: {notes}; contraindicated pairs: {pairs}")
    for dataset_row, count in (
        (ds_fda, len([m for m in memberships if m[3] == ds_fda.id])),
        (ds_atc, len([m for m in memberships if m[3] == ds_atc.id])),
    ):
        dataset_row.record_count = count
    session.commit()


def _upsert_classes(
    session: Session, rows: dict[tuple[str, str], str]
) -> dict[tuple[str, str], int]:
    values = [{"source": s, "class_id": c, "name": n} for (s, c), n in rows.items()]
    for batch in chunks(values):
        stmt = pg_insert(DrugClass).values(list(batch))
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["source", "class_id"], set_={"name": stmt.excluded.name}
            )
        )
    return {
        (s, c): i
        for i, s, c in session.execute(select(DrugClass.id, DrugClass.source, DrugClass.class_id))
    }


def _context_notes(session: Session, ds: int, ci_disease: list[tuple[str, str, str]]) -> int:
    session.execute(delete(ContextNote).where(ContextNote.dataset_id == ds))
    rows, seen = [], set()
    for rxcui, cid, cname in ci_disease:
        lowered = cname.lower()
        context = next((c for w, c in CONTEXT_WORDS.items() if w in lowered), None)
        if context is None or (rxcui, context, cname) in seen:
            continue
        seen.add((rxcui, context, cname))
        rows.append(
            {
                "ingredient_rxcui": rxcui,
                "context": context,
                "kind": "contraindication",
                "text": f"Listed as contraindicated in: {cname}",
                "dataset_id": ds,
                "source_ref": f"MED-RT CI_with {cid}",
            }
        )
    for batch in chunks(rows):
        session.execute(insert(ContextNote), list(batch))
    return len(rows)


def _contraindicated_pairs(
    session: Session,
    ds: int,
    ci_chem: dict[str, set[tuple[str, str]]],
    by_name: dict[str, str],
    ingredients: dict[str, str],
) -> int:
    session.execute(delete(Interaction).where(Interaction.dataset_id == ds))
    pairs: dict[tuple[str, str], str] = {}
    for rxcui, classes in ci_chem.items():
        for cid, cname in classes:
            # A "class" that is one ingredient (e.g. "Moxifloxacin") maps by exact name;
            # a real class (e.g. "Fluoroquinolones") is expanded via FDA chemical structure.
            direct = by_name.get(norm(cname))
            members = [direct] if direct else _chem_members(cid)
            for other in members:
                if other == rxcui or other not in ingredients:
                    continue
                key = (rxcui, other) if rxcui < other else (other, rxcui)
                pairs.setdefault(key, f"MED-RT CI_ChemClass {cid} ({cname})")
    rows = [
        {
            "ingredient_a": a,
            "ingredient_b": b,
            "severity": "contraindicated",
            "provenance": "structured",
            "dataset_id": ds,
            "source_ref": ref[:200],
            "evidence_text": None,
            "source_url": None,
        }
        for (a, b), ref in pairs.items()
    ]
    for batch in chunks(rows):
        session.execute(insert(Interaction), list(batch))
    return len(rows)
