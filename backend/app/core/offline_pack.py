"""Offline pack: the data the PWA needs to run typed checks without a connection (pure).

What goes in (ADR-018):
  * ingredient names, and the searchable names (generic, brand, India brand, synonym) so the
    offline app can look up exactly what was typed or picked;
  * interaction pairs whose overall severity is contraindicated or major, and moderate pairs
    where both ingredients are in common use (in an RxNorm prescribable product or an Indian
    brand). Each pair carries ALL its source records, so an offline warning cites the same
    dataset records as the online one;
  * rule-group membership with the evidence the engine itself would cite (computed by the
    engine, not re-implemented here), the rule table and the pair wording.
Not included, and said so on screen: minor/ungraded pairs, label-text mentions, patient-context
contraindications, label notes, and recalls. Offline results are a partial check.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.core.engine import templates
from app.core.engine.engine import group_memberships, rule_evidence
from app.core.engine.model import SEVERITY_ORDER, SEVERITY_RANK, InteractionFact, KnowledgeSnapshot
from app.core.engine.rules import RuleSet, Text
from app.core.normalise.vocab import FUZZY_KINDS, Entry

PACK_FORMAT = 1
ALWAYS = {"contraindicated", "major"}
IF_COMMON = {"moderate"}


def build_pack(
    snapshot: KnowledgeSnapshot,
    entries: Iterable[Entry],
    rules: RuleSet,
    common: set[str],
    generated_at: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`extra`: further JSON fields (fixed wording); included in the version hash."""
    names = snapshot.names
    facts: dict[tuple[str, str], list[InteractionFact]] = defaultdict(list)
    for fact in snapshot.interactions:
        facts[(fact.a, fact.b) if fact.a < fact.b else (fact.b, fact.a)].append(fact)

    kept: list[tuple[str, str, list[InteractionFact]]] = []
    for (a, b), pair_facts in sorted(facts.items()):
        # Same overall severity as the engine: the most severe of the pair's records.
        severity = min((f.severity for f in pair_facts), key=SEVERITY_RANK.__getitem__)
        if severity in ALWAYS or (severity in IF_COMMON and a in common and b in common):
            kept.append((a, b, pair_facts))

    order = sorted(names)
    index = {rx: i for i, rx in enumerate(order)}
    datasets = sorted({f.dataset for _, _, fs in kept for f in fs})
    ds_index = {code: i for i, code in enumerate(datasets)}
    sev_index = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    # Source URLs share a long per-dataset prefix; store it once (lossless: prefix + rest).
    prefixes = [
        os.path.commonprefix(  # noqa: RUF071 - URL text prefix, not path components
            [f.source_url for _, _, fs in kept for f in fs if f.dataset == code and f.source_url]
        )
        for code in datasets
    ]

    def url_rest(f: InteractionFact) -> str | None:
        return None if f.source_url is None else f.source_url[len(prefixes[ds_index[f.dataset]]) :]

    pairs = [
        [
            index[a],
            index[b],
            [
                [ds_index[f.dataset], sev_index[f.severity], f.source_ref, url_rest(f)]
                + ([f.evidence_text] if f.evidence_text else [])
                for f in sorted(pair_facts, key=lambda f: (f.dataset, f.source_ref, f.severity))
            ],
        ]
        for a, b, pair_facts in kept
        if a in index and b in index
    ]

    seen: set[tuple[str, tuple[str, ...]]] = set()
    name_rows: list[list[Any]] = []
    for e in sorted(entries, key=lambda e: (e.text_norm, e.kind, e.ref)):
        key = (e.text_norm, e.ingredients)
        if e.kind not in FUZZY_KINDS or not e.ingredients or key in seen:
            continue
        if not all(rx in index for rx in e.ingredients):
            continue
        seen.add(key)
        name_rows.append([e.text, e.kind, [index[rx] for rx in e.ingredients], e.ref])

    groups = {
        key: {
            "label": rules.groups[key].label,
            "members": [[index[rx], [asdict(ev) for ev in evs]] for rx, evs in members.items()],
        }
        for key, members in group_memberships(snapshot, rules).items()
    }

    body: dict[str, Any] = {
        "format": PACK_FORMAT,
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(timespec="seconds"),
        "datasets": [asdict(d) for d in sorted(snapshot.datasets.values(), key=lambda d: d.code)],
        "severities": list(SEVERITY_ORDER),
        "pair_datasets": datasets,
        "url_prefixes": prefixes,
        "ingredients": [[rx, names[rx]] for rx in order],
        "names": name_rows,
        "pairs": pairs,
        "groups": groups,
        "rules": _rules(rules),
        "templates": {
            "pair_title": templates.PAIR_TITLE,
            "pair_simple": templates.PAIR_SIMPLE,
            "pair_professional": templates.PAIR_PROFESSIONAL,
            "pair_consider": templates.PAIR_CONSIDER,
        },
    }
    body.update(extra or {})
    body["version"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    return body


def _text(t: Text) -> dict[str, str]:
    return {"title": t.title, "simple": t.simple, "professional": t.professional,
            "consider": t.consider}  # fmt: skip


def _rules(rules: RuleSet) -> dict[str, Any]:
    ids = [rules.dup_ingredient_id, rules.dup_class_id, *(r.id for r in rules.cumulative)]
    return {
        "version": rules.version,
        "evidence": {rid: asdict(rule_evidence(rules, rid)) for rid in ids},
        "dup_ingredient": {
            "id": rules.dup_ingredient_id,
            "severity": rules.dup_ingredient_severity,
            "text": _text(rules.dup_ingredient_text),
        },
        "dup_class": {
            "id": rules.dup_class_id,
            "text": _text(rules.dup_class_text),
            "groups": [[key, sev] for key, sev in rules.dup_class_groups.items()],
        },
        "cumulative": [
            {
                "id": r.id,
                "groups": list(r.groups),
                "min_drugs": r.min_drugs,
                "min_groups": r.min_groups,
                "require_groups": [list(slot) for slot in r.require_groups],
                "severity": r.severity,
                "text": _text(r.text),
            }
            for r in rules.cumulative
        ],
    }
