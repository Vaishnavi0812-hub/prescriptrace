"""Resolve a messy medicine name to RxNorm ingredient(s) with a confidence score.

Deterministic and side-effect free. Strategy, strongest evidence first:
  1. exact match on the full line           ("Dolo 650")                   conf 1.00
  2. exact match on the core name           ("Augmentin 625" → augmentin)  conf 0.98
  3. curated abbreviation                   ("pcm" → paracetamol)          conf 0.95
  4. exact match after OCR digit fixes      ("Metf0rmin" → metformin)      conf 0.92
  5. combination: every part resolved       ("amox/clav")                  min(parts) x 0.98
  6. fuzzy match on short names             ("paracetmol")                 from similarity
  7. optional external candidates (RxNav)   capped at 0.75, never auto-accepted
Status: resolved ≥ auto_accept, confirm ≥ confirm_min, else unknown (user must pick).
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from rapidfuzz import fuzz, process

from app.core.normalise.parse import ParsedLine, Strength, ocr_variants, parse
from app.core.normalise.vocab import KIND_RANK, Entry, Vocabulary
from app.core.text import norm

# Common pharmacy shorthand. Each expansion must itself be an exact vocabulary name, so a
# wrong or missing expansion yields no match rather than a wrong one.
ABBREVIATIONS = {
    # Combinations ("+") are resolved part by part like a typed "amox/clav".
    "amoxyclav": "amoxicillin + clavulanate",
    "amoxiclav": "amoxicillin + clavulanate",
    "co amoxiclav": "amoxicillin + clavulanate",
    "co trimoxazole": "sulfamethoxazole + trimethoprim",
    "cotrimoxazole": "sulfamethoxazole + trimethoprim",
    "vit d3": "cholecalciferol",
    "vitamin d3": "cholecalciferol",
    "vit d": "cholecalciferol",
    "vit b12": "cyanocobalamin",
    "vitamin b12": "cyanocobalamin",
    "vit c": "ascorbic acid",
    "vitamin c": "ascorbic acid",
    "pcm": "paracetamol",
    "para": "paracetamol",
    "amox": "amoxicillin",
    "amoxy": "amoxicillin",
    "clav": "clavulanate",
    "hctz": "hydrochlorothiazide",
    "asa": "aspirin",
    "mtx": "methotrexate",
    "inh": "isoniazid",
    "cpm": "chlorpheniramine",
}

EXTERNAL_CAP = 0.75  # RxNav approximate matches: suggestions only
SHORT_QUERY = 4  # fuzzy matching on <=4 characters is unreliable
MEDIUM_QUERY = 6  # 5-6 characters: needs higher similarity and never auto-accepts
MIN_PREFIX = 4
CONFIRM_SIMILARITY = 87.0  # fuzzy similarity needed before a single guess is offered to confirm
PREFIX_SINGLE = 0.85  # every name starting with the query is the same drug: confirm
PREFIX_MANY = 0.55  # several drugs share the prefix: list them, pick none
TIE_MARGIN = 4.0  # similarity points; closer than this to a different drug = ambiguous
BRAND_KINDS = {"india_brand", "brand"}
FAMILY_CAP = 0.75  # another member of the same brand family: offer, never near auto-accept


@dataclass(frozen=True)
class Candidate:
    label: str
    kind: str
    ingredients: tuple[str, ...]  # RxCUIs
    ingredient_names: tuple[str, ...]
    confidence: float
    method: str
    ref: str
    source: str


@dataclass(frozen=True)
class NormalisedLine:
    raw: str
    query: str
    status: str  # resolved | confirm | unknown
    confidence: float
    best: Candidate | None
    candidates: tuple[Candidate, ...]
    strengths: tuple[Strength, ...]
    dose_form: str | None


ExternalSource = Callable[[str], Iterable[Candidate]]


class Normaliser:
    def __init__(
        self,
        vocab: Vocabulary,
        *,
        auto_accept: float = 0.90,
        confirm_min: float = 0.60,
        external: ExternalSource | None = None,
        max_candidates: int = 5,
    ) -> None:
        self.vocab = vocab
        self.auto_accept = auto_accept
        self.confirm_min = confirm_min
        self.external = external
        self.max_candidates = max_candidates

    # ------------------------------------------------------------------ public

    def normalise(self, raw: str) -> NormalisedLine:
        parsed = parse(raw)
        candidates = self._candidates(parsed)
        if not candidates and self.external is not None and parsed.core:
            candidates = [
                replace(c, confidence=min(c.confidence, EXTERNAL_CAP), method="external")
                for c in self.external(parsed.core)
            ]
        ranked = _dedupe(candidates)[: self.max_candidates]
        best = ranked[0] if ranked else None
        confidence = best.confidence if best else 0.0
        if confidence >= self.auto_accept:
            status = "resolved"
        elif confidence >= self.confirm_min:
            status = "confirm"
        else:
            status = "unknown"
        return NormalisedLine(
            raw=raw,
            query=parsed.core or parsed.full,
            status=status,
            confidence=round(confidence, 3),
            best=best if status != "unknown" else None,
            candidates=tuple(ranked),
            strengths=parsed.strengths,
            dose_form=parsed.dose_form,
        )

    def suggest(self, text: str, limit: int = 10) -> list[Candidate]:
        """Autocomplete: names starting with the typed text, then typo-tolerant matches.

        Unlike normalise(), several names for the same drug may appear (brand and generic shown
        together), but each name appears once. Never calls external services.
        """
        query = parse(text).full or norm(text)
        if len(query) < 2:
            return []
        keys = self.vocab.fuzzy_keys
        seen: set[str] = set()
        out: list[Candidate] = []
        for key in keys[bisect.bisect_left(keys, query) :]:
            if not key.startswith(query) or len(out) >= limit * 3:
                break
            for entry in self.vocab.exact[key]:
                if entry.ref not in seen:
                    seen.add(entry.ref)
                    out.append(self._candidate(entry, 1.0, "prefix"))
        out.sort(key=lambda c: (KIND_RANK.get(c.kind, 9), len(c.label), c.label.lower()))
        out = out[:limit]
        if len(out) < limit and len(query) >= MIN_PREFIX:
            for cand in self._fuzzy(parse(text).core or query):
                # Only genuine typo matches, never weak look-alikes ("telma" → "elm").
                if cand.confidence < self.confirm_min:
                    continue
                if cand.ref not in seen and len(out) < limit:
                    seen.add(cand.ref)
                    out.append(cand)
        return out

    # ------------------------------------------------------------------ steps

    def _candidates(self, parsed: ParsedLine) -> list[Candidate]:
        for text, conf, method in ((parsed.full, 1.0, "exact"), (parsed.core, 0.98, "exact_core")):
            hits = self._exact(text, conf, method)
            if hits:
                return hits
        expansion = ABBREVIATIONS.get(parsed.core)
        if expansion is not None:
            expanded = parse(expansion)
            hits = (
                [c] if expanded.components and (c := self._combination(expanded.components)) else []
            ) or self._exact(expanded.core, 0.95, "abbreviation")
            if hits:
                return [replace(h, method="abbreviation") for h in hits]
        for variant in ocr_variants(parsed.core):
            hits = self._exact(variant, 0.92, "ocr_fix")
            if hits:
                return hits
        if parsed.components:
            combo = self._combination(parsed.components)
            if combo is not None:
                return [combo]
        prefix = self._prefix(parsed.core)
        fuzzy = self._fuzzy(parsed.core)
        if prefix:
            # The query is the start of real names: a look-alike ("insulin" → inulin) must not
            # outrank that, and if several drugs share the prefix nothing may be auto-picked.
            ceiling = prefix[0].confidence
            fuzzy = [replace(c, confidence=min(c.confidence, ceiling)) for c in fuzzy]
        return prefix + fuzzy

    def _prefix(self, query: str) -> list[Candidate]:
        """Names that start with the query as a whole word ("insulin" → insulin glargine, …).

        One drug behind all of them → confirm; several different drugs → a list to pick from.
        """
        if len(query) < MIN_PREFIX:
            return []
        keys = self.vocab.fuzzy_keys  # sorted, so all keys with this prefix are contiguous
        matched: list[Entry] = []
        for key in keys[bisect.bisect_left(keys, query) :]:
            if not key.startswith(query) or len(matched) >= 25:
                break
            if key != query:
                matched.extend(self.vocab.exact[key])
        drugs = {e.ingredients for e in matched}
        conf = PREFIX_SINGLE if len(drugs) == 1 else PREFIX_MANY
        return [self._candidate(e, conf, "prefix") for e in matched]

    def _exact(self, text: str, conf: float, method: str) -> list[Candidate]:
        if not text:
            return []
        bucket = self.vocab.exact.get(text, [])
        out = [self._candidate(e, conf, method) for e in bucket]
        if len({c.ingredients for c in out}) > 1:
            # Same name, different drugs (e.g. Crocin): keep the preferred one first, but
            # never claim full certainty.
            out = [replace(c, confidence=min(c.confidence, 0.95)) for c in out]
            out[1:] = [replace(c, confidence=min(c.confidence, 0.6)) for c in out[1:]]
        return out

    def _combination(self, parts: tuple[str, ...]) -> Candidate | None:
        resolved: list[Candidate] = []
        for part in parts:
            hits = self._candidates(parse(part))
            if not hits or hits[0].confidence < self.auto_accept:
                return None
            resolved.append(hits[0])
        ingredients = tuple(sorted({r for c in resolved for r in c.ingredients}))
        return Candidate(
            label=" + ".join(c.label for c in resolved),
            kind="combination",
            ingredients=ingredients,
            ingredient_names=self.vocab.names_of(ingredients),
            confidence=round(min(c.confidence for c in resolved) * 0.98, 3),
            method="combination",
            ref=";".join(c.ref for c in resolved),
            source=";".join(sorted({c.source for c in resolved})),
        )

    def _fuzzy(self, query: str) -> list[Candidate]:
        if not query:
            return []
        scored: dict[str, float] = {}
        for scorer in (fuzz.ratio, fuzz.token_sort_ratio):
            for key, score, _ in process.extract(
                query, self.vocab.fuzzy_keys, scorer=scorer, limit=10, score_cutoff=70
            ):
                scored[key] = max(scored.get(key, 0.0), float(score))
        ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
        out: list[Candidate] = []
        top_score = ranked[0][1] if ranked else 0.0
        top_drug: tuple[str, ...] | None = None
        for key, score in ranked:
            for entry in self.vocab.exact[key]:
                conf = _fuzzy_confidence(query, score)
                if entry.kind in BRAND_KINDS and _other_family_member(query, key):
                    conf = min(conf, FAMILY_CAP)
                if top_drug is None:
                    top_drug = entry.ingredients
                elif entry.ingredients != top_drug and top_score - score < TIE_MARGIN:
                    # A different drug is almost as close: the best guess is not safe.
                    out = [replace(c, confidence=min(c.confidence, 0.75)) for c in out]
                out.append(self._candidate(entry, conf, "fuzzy"))
        return sorted(out, key=lambda c: -c.confidence)

    def _candidate(self, entry: Entry, conf: float, method: str) -> Candidate:
        return Candidate(
            label=entry.text,
            kind=entry.kind,
            ingredients=entry.ingredients,
            ingredient_names=self.vocab.names_of(entry.ingredients),
            confidence=round(conf, 3),
            method=method,
            ref=entry.ref,
            source=entry.source,
        )


def _fuzzy_confidence(query: str, similarity: float) -> float:
    """Map 0-100 similarity to a confidence. Short queries are capped below 'confirm'."""
    conf = 0.97 * float((similarity / 100.0) ** 1.5)
    length = len(query.replace(" ", ""))
    if length <= SHORT_QUERY:
        conf = min(conf, 0.55)
    elif length <= MEDIUM_QUERY:
        conf = min(conf, 0.75) if similarity >= 80 else min(conf, 0.55)
    if similarity < CONFIRM_SIMILARITY:
        # Weak look-alikes ("itopride" vs iopromide) are listed for the user to pick from but
        # never suggested as "is this what you meant?".
        conf = min(conf, 0.55)
    return conf


def _other_family_member(query: str, key: str) -> bool:
    """Same brand stem, different letter suffix: "zerodol sp" vs "zerodol p", "allegra m" vs
    "allegra". Indian brand families use such suffixes for different compositions (SP adds
    serratiopeptidase, M adds montelukast), so a close spelling is not the same medicine."""
    q_words, k_words = query.split(), key.split()
    if not q_words or not k_words or q_words[0] != k_words[0]:
        return False

    def letters(words: list[str]) -> set[str]:
        return {w for w in words[1:] if w.isalpha()}

    return letters(q_words) != letters(k_words)


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """One candidate per distinct ingredient set, keeping the best-ranked one."""
    seen: set[tuple[str, ...]] = set()
    out: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: -c.confidence):
        if c.ingredients in seen:
            continue
        seen.add(c.ingredients)
        out.append(c)
    return out
