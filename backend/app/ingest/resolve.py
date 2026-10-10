"""Map a drug name from another dataset to an RxNorm ingredient, conservatively.

Order: local exact match on ingredient names and synonyms, then the RxNorm API restricted to
*exact* (normalised) string matches in any RxNorm source vocabulary (e.g. ATC "acetylsalicylic
acid" → aspirin). Approximate matching is never used here: a wrong ingredient mapping would
produce a wrong interaction warning. Unresolved names are reported, not guessed.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.core.text import norm
from app.ingest.common import DatasetInfo, cached_json, upsert_dataset, upsert_rows
from app.models import DrugName, Ingredient

RXNAV = "https://rxnav.nlm.nih.gov/REST"

RXNORM_API = DatasetInfo(
    code="rxnorm_api",
    name="RxNorm ingredients fetched via RxNav API (gap fill)",
    source_url=RXNAV,
    licence="Public domain (RxNorm SAB=RXNORM content); NLM RxNav terms of service",
    licence_url="https://lhncbc.nlm.nih.gov/RxNav/TermsofService.html",
    limitations="Only ingredients referenced by other datasets but absent from the "
    "US Prescribable subset (e.g. drugs marketed in India but not the US).",
)


@dataclass(frozen=True)
class Resolved:
    rxcui: str
    name: str
    via: str  # local | rxnav_exact


class IngredientResolver:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._local: dict[str, tuple[str, str]] = {}
        for rxcui, name, name_norm in session.execute(
            select(Ingredient.rxcui, Ingredient.name, Ingredient.name_norm)
        ):
            self._local[name_norm] = (rxcui, name)
        # Synonyms (precise-ingredient salts, INN names) loaded by the RxNorm ingest.
        names = {rxcui: name for _, (rxcui, name) in self._local.items()}
        for text_norm, rxcui in session.execute(
            select(DrugName.text_norm, DrugName.ingredient_rxcui).where(
                DrugName.kind == "synonym", DrugName.ingredient_rxcui.is_not(None)
            )
        ):
            if rxcui in names:
                self._local.setdefault(text_norm, (rxcui, names[rxcui]))
        self._added: list[dict[str, Any]] = []
        self._synonyms: list[tuple[str, str]] = []

    def resolve(self, raw_name: str) -> Resolved | None:
        key = norm(raw_name)
        if not key:
            return None
        if key in self._local:
            rxcui, name = self._local[key]
            return Resolved(rxcui, name, "local")
        found = self._via_api(raw_name)
        if found is not None:
            self._local[key] = (found.rxcui, found.name)
            if key != norm(found.name):  # e.g. "acetylsalicylic acid" → aspirin
                self._synonyms.append((raw_name, found.rxcui))
        return found

    def _via_api(self, raw_name: str) -> Resolved | None:
        query = urllib.parse.urlencode({"name": raw_name, "search": 2, "allsrc": 1})
        data = cached_json(f"{RXNAV}/rxcui.json?{query}", f"rxnav/rxcui/{norm(raw_name)}")
        ids = data.get("idGroup", {}).get("rxnormId") or []
        ingredients: set[tuple[str, str]] = set()
        for rxcui in ids:
            ingredients |= self._to_ingredients(rxcui)
        if len(ingredients) != 1:  # none, or ambiguous (combination / multiple concepts)
            return None
        rxcui, name = ingredients.pop()
        if norm(name) not in self._local:
            self._added.append(
                {"rxcui": rxcui, "name": name, "name_norm": norm(name), "dataset_id": None}
            )
            self._local[norm(name)] = (rxcui, name)
        return Resolved(rxcui, name, "rxnav_exact")

    def _to_ingredients(self, rxcui: str) -> set[tuple[str, str]]:
        props = cached_json(f"{RXNAV}/rxcui/{rxcui}/properties.json", f"rxnav/props/{rxcui}")
        prop = props.get("properties") or {}
        tty = prop.get("tty")
        if tty == "IN":
            return {(rxcui, prop["name"])}
        if tty == "PIN":  # salt/precise form → its base ingredient
            rel = cached_json(
                f"{RXNAV}/rxcui/{rxcui}/related.json?tty=IN", f"rxnav/related_in/{rxcui}"
            )
            out: set[tuple[str, str]] = set()
            for group in rel.get("relatedGroup", {}).get("conceptGroup") or []:
                for c in group.get("conceptProperties") or []:
                    out.add((c["rxcui"], c["name"]))
            return out
        return set()  # MIN (multi-ingredient), BN, products: not a single ingredient

    def flush_new_ingredients(self) -> int:
        """Persist ingredients and synonyms learned from the API (FKs + offline lookup)."""
        if not self._added and not self._synonyms:
            return 0
        dataset = upsert_dataset(self.session, RXNORM_API)
        count = 0
        if self._added:
            for row in self._added:
                row["dataset_id"] = dataset.id
            table = Ingredient.__table__
            count = upsert_rows(self.session, table, self._added, ["rxcui"])  # type: ignore[arg-type]
        existing = set(
            self.session.execute(
                select(DrugName.text_norm, DrugName.ingredient_rxcui).where(
                    DrugName.dataset_id == dataset.id
                )
            ).tuples()
        )
        rows = []
        for raw, rxcui in self._synonyms:
            key = (norm(raw), rxcui)
            if key in existing:
                continue
            existing.add(key)
            rows.append(
                {
                    "text": raw[:300],
                    "text_norm": key[0][:300],
                    "kind": "synonym",
                    "ingredient_rxcui": rxcui,
                    "dataset_id": dataset.id,
                    "source_ref": f"RxNav exact match: {raw}"[:200],
                }
            )
        if rows:
            self.session.execute(insert(DrugName), rows)
        self._added, self._synonyms = [], []
        return count
