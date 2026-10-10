"""Optional online fallback: RxNorm approximate-term suggestions for names we do not know.

Used by the Normaliser only when the local vocabulary has no candidate. Suggestions are capped
below the auto-accept threshold by the Normaliser, so they always need the user's confirmation.
Brand-like names are especially risky (RxNorm's "crocin" is saffron), which is why this is a
suggestion source and never a resolver. Network errors return no suggestions.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from app.core.normalise import Candidate, Vocabulary

log = logging.getLogger(__name__)

RXNAV = "https://rxnav.nlm.nih.gov/REST"
Fetch = Callable[[str], Any]


def _fetch(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "PrescripTrace/0.1"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class RxNavSuggestions:
    def __init__(self, vocab: Vocabulary, fetch: Fetch = _fetch, max_results: int = 3) -> None:
        self.vocab = vocab
        self.fetch = fetch
        self.max_results = max_results

    def __call__(self, query: str) -> list[Candidate]:
        try:
            return self._suggest(query)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            log.info("RxNav suggestions unavailable: %s", exc)
            return []

    def _suggest(self, query: str) -> list[Candidate]:
        params = urllib.parse.urlencode({"term": query, "maxEntries": 8})
        data = self.fetch(f"{RXNAV}/approximateTerm.json?{params}")
        found: list[Candidate] = []
        seen: set[str] = set()
        for cand in (data.get("approximateGroup") or {}).get("candidate") or []:
            rxcui = cand.get("rxcui")
            if not rxcui or rxcui in seen:
                continue
            seen.add(rxcui)
            ingredients = self._ingredients(rxcui)
            # Only suggest drugs our knowledge base knows, so a warning check can follow.
            if not ingredients or not all(i in self.vocab.ingredient_names for i in ingredients):
                continue
            found.append(
                Candidate(
                    label=cand.get("name") or ", ".join(self.vocab.names_of(ingredients)),
                    kind="external",
                    ingredients=ingredients,
                    ingredient_names=self.vocab.names_of(ingredients),
                    confidence=0.7,
                    method="external",
                    ref=f"rxnav:{rxcui}",
                    source="rxnav_approximate",
                )
            )
            if len(found) >= self.max_results:
                break
        return found

    def _ingredients(self, rxcui: str) -> tuple[str, ...]:
        if rxcui in self.vocab.ingredient_names:
            return (rxcui,)
        data = self.fetch(f"{RXNAV}/rxcui/{rxcui}/related.json?tty=IN")
        groups = (data.get("relatedGroup") or {}).get("conceptGroup") or []
        ids = {c["rxcui"] for g in groups for c in g.get("conceptProperties") or []}
        return tuple(sorted(ids))
