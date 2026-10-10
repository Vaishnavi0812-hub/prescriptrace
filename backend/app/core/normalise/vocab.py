"""In-memory drug vocabulary: plain data, built once from the database (or by hand in tests)."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# Lower rank = preferred when several entries share the same text. India brands come first:
# RxNorm's "crocin" is a saffron carotenoid; for an Indian pharmacy "Crocin" is paracetamol.
KIND_RANK = {"india_brand": 0, "ingredient": 1, "synonym": 2, "brand": 3, "product": 4}
# Kinds searched by fuzzy matching. Long product names ("acetaminophen 500 MG Oral Tablet")
# would swamp short queries, so products are exact-match only.
FUZZY_KINDS = {"india_brand", "ingredient", "synonym", "brand"}


@dataclass(frozen=True)
class Entry:
    """One searchable name and the ingredients it stands for."""

    text: str
    text_norm: str
    kind: str
    ingredients: tuple[str, ...]  # RxCUIs, sorted
    ref: str  # e.g. "brand:151392", "india_brand:7", "ingredient:161"
    source: str  # dataset code, for provenance


@dataclass
class Vocabulary:
    ingredient_names: dict[str, str]  # rxcui -> name
    entries: list[Entry]
    exact: dict[str, list[Entry]] = field(init=False)
    fuzzy_keys: list[str] = field(init=False)

    def __post_init__(self) -> None:
        exact: dict[str, list[Entry]] = defaultdict(list)
        for entry in self.entries:
            if not entry.ingredients:
                continue
            exact[entry.text_norm].append(entry)
            alias = strength_free(entry.text_norm)
            if entry.kind == "india_brand" and alias and alias != entry.text_norm:
                # "dolo 650" is also findable as "dolo".
                exact[alias].append(entry)
        for bucket in exact.values():
            bucket.sort(key=lambda e: (KIND_RANK.get(e.kind, 9), e.text))
        self.exact = dict(exact)
        self.fuzzy_keys = sorted(
            key for key, bucket in self.exact.items() if any(e.kind in FUZZY_KINDS for e in bucket)
        )

    def names_of(self, rxcuis: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(self.ingredient_names.get(r, r) for r in rxcuis)


def strength_free(text_norm: str) -> str:
    return " ".join(t for t in text_norm.split() if not re.fullmatch(r"[\d.]+", t))
