"""Interaction checking against CRESCENDDI (Kontsioti et al., Sci Data 2022; CC0).

CRESCENDDI is independent of our sources: positive controls are drug pairs listed as
interacting by the BNF and/or Micromedex (with severities from BNF, the French ANSM thesaurus
and Micromedex); negative controls are pairs with no listed interaction in those resources for a
given adverse event. Each pair is run through the real engine (all datasets, rules and label
text) as two medicines, with no patient context.

Caveats (also in METHODOLOGY.md): negative controls mean "no interaction known for that event",
not "safe together", so the false-alarm rate is an upper bound; CRESCENDDI is built from UK/US/
French compendia, so it reflects their judgement of severity, not ground truth.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

import openpyxl
from app.core.engine import Medicine, check
from app.models import Ingredient
from app.repo.knowledge import load_snapshot
from sqlalchemy import func, select

from common import RAW, pct, session, write_result

DIR = RAW / "crescenddi"
FILES = {  # figshare collection 10.6084/m9.figshare.c.5481408, md5 as published
    "positive.xlsx": "1f86f8a7d7c10d70a68f06ab252df0af",
    "negative.xlsx": "f1eec95b57255ed9865192cd416dd049",
    "drug_mappings.xlsx": "a1c289dcc5da3ad89ebb9d205538ed7c",
}
DOWNLOAD = {
    "positive.xlsx": "https://ndownloader.figshare.com/files/28584873",
    "negative.xlsx": "https://ndownloader.figshare.com/files/28584876",
    "drug_mappings.xlsx": "https://ndownloader.figshare.com/files/28584879",
}

# Reference severity tiers (most severe level any source gives the pair).
SERIOUS = {
    "contraindicated",
    "major",
    "severe",
    "contre-indication",
    "contraindication",
    "association deconseillee",
    "association déconseillée",
    "not recommended",
}
MODERATE = {"moderate", "precaution d'emploi", "précaution d'emploi", "precaution for use"}
ATTENTION = {"contraindicated", "major"}
SEV_ORDER = ["contraindicated", "major", "moderate", "minor", "unknown"]


def rows(name: str) -> list[dict[str, Any]]:
    path = DIR / name
    if not path.exists():
        raise SystemExit(f"missing {path}: download it from {DOWNLOAD[name]} (see METHODOLOGY.md)")
    digest = hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 - checksum as published
    if digest != FILES[name]:
        raise SystemExit(f"{path} does not match the published checksum; re-download it")
    sheet = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    it = sheet.iter_rows(values_only=True)
    header = [str(h) for h in next(it)]
    return [dict(zip(header, r, strict=False)) for r in it]


def tier(levels: list[str | None]) -> str:
    found = {str(x).strip().lower() for x in levels if x}
    if found & SERIOUS:
        return "serious"
    if found & MODERATE:
        return "moderate"
    return "minor_or_other" if found else "not_graded"


def run() -> dict[str, Any]:
    positive, negative, mappings = (
        rows("positive.xlsx"),
        rows("negative.xlsx"),
        rows("drug_mappings.xlsx"),
    )
    s = session()
    try:
        # Map CRESCENDDI drug concepts to our ingredients: RxNorm code first, else exact name.
        ours = dict(s.execute(select(func.lower(Ingredient.name), Ingredient.rxcui)).tuples().all())
        known = set(ours.values())
        code = {
            str(m["DRUG_CONCEPT_NAME"]).lower(): str(m["RXNORM_CODE/RXNORM_EXTENSION_CODE (OHDSI)"])
            for m in mappings
            if m["DRUG_CONCEPT_NAME"]
        }

        def to_rx(name: str) -> str | None:
            n = name.strip().lower()
            if code.get(n) in known:
                return code[n]
            return ours.get(n)

        pos: dict[frozenset[str], dict[str, Any]] = {}
        unmapped: Counter[str] = Counter()
        levels: dict[frozenset[str], list[str | None]] = defaultdict(list)
        for r in positive:
            a, b = to_rx(r["DRUG_1_CONCEPT_NAME"]), to_rx(r["DRUG_2_CONCEPT_NAME"])
            for name, rx in ((r["DRUG_1_CONCEPT_NAME"], a), (r["DRUG_2_CONCEPT_NAME"], b)):
                if rx is None:
                    unmapped[name.lower()] += 1
            if a and b and a != b:
                key = frozenset((a, b))
                pos.setdefault(key, {"names": (r["DRUG_1_CONCEPT_NAME"], r["DRUG_2_CONCEPT_NAME"])})
                levels[key] += [r["BNF_SEV_LEVEL"], r["ANSM_SEV_LEVEL"], r["MICROMEDEX_SEV_LEVEL"]]
        for key in pos:
            pos[key]["tier"] = tier(levels[key])
        neg: dict[frozenset[str], dict[str, Any]] = {}
        for r in negative:
            a, b = to_rx(r["DRUG_1_CONCEPT_NAME"]), to_rx(r["DRUG_2_CONCEPT_NAME"])
            if a and b and a != b and frozenset((a, b)) not in pos:
                neg.setdefault(
                    frozenset((a, b)),
                    {"names": (r["DRUG_1_CONCEPT_NAME"], r["DRUG_2_CONCEPT_NAME"])},
                )

        all_rx = {rx for k in (*pos, *neg) for rx in k}
        kb = load_snapshot(s, all_rx)
        by_pair: dict[frozenset[str], list[Any]] = defaultdict(list)
        for fact in kb.interactions:
            by_pair[frozenset((fact.a, fact.b))].append(fact)
    finally:
        s.close()

    def predict(key: frozenset[str]) -> dict[str, Any]:
        a, b = sorted(key)
        # Only this pair's facts (same result; avoids re-indexing every fact on each call).
        pair_kb = replace(kb, interactions=by_pair.get(key, []))
        result = check([Medicine("1", "A", (a,)), Medicine("2", "B", (b,))], pair_kb)
        if not result.findings:
            return {"flagged": False, "severity": None, "provenance": None, "source": None}
        top = result.findings[0]  # sorted most severe first
        source = (
            "rule"
            if top.provenance == "rule"
            else "+".join(sorted({e.dataset for e in top.evidence if e.dataset != "rules"}))
        )
        return {
            "flagged": True,
            "severity": top.severity,
            "provenance": top.provenance,
            "source": source,
        }

    for key, item in pos.items():
        item.update(predict(key))
    for key, item in neg.items():
        item.update(predict(key))

    def recall(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "pairs": len(items),
            "flagged_pct": pct(sum(i["flagged"] for i in items), len(items)),
            "needs_attention_pct": pct(sum(i["severity"] in ATTENTION for i in items), len(items)),
            "worth_checking_or_higher_pct": pct(
                sum(i["severity"] in ATTENTION | {"moderate"} for i in items), len(items)
            ),
        }

    pos_items, neg_items = list(pos.values()), list(neg.values())
    tp = sum(i["flagged"] for i in pos_items)
    fp = sum(i["flagged"] for i in neg_items)
    tp_att = sum(i["severity"] in ATTENTION for i in pos_items)
    fp_att = sum(i["severity"] in ATTENTION for i in neg_items)
    confusion: dict[str, dict[str, int]] = {}
    for t in ("serious", "moderate", "minor_or_other", "not_graded"):
        c = Counter(i["severity"] or "not flagged" for i in pos_items if i["tier"] == t)
        confusion[t] = {k: c.get(k, 0) for k in [*SEV_ORDER, "not flagged"]}
    missed_serious = sorted(
        " + ".join(i["names"]) for i in pos_items if i["tier"] == "serious" and not i["flagged"]
    )
    return {
        "reference": "CRESCENDDI (Kontsioti et al. 2022), "
        "figshare 10.6084/m9.figshare.c.5481408, CC0",
        "positive_rows": len(positive),
        "negative_rows": len(negative),
        "positive_pairs_mapped": len(pos_items),
        "negative_pairs_mapped": len(neg_items),
        "drug_names_unmapped": len(unmapped),
        "unmapped_examples": [n for n, _ in unmapped.most_common(15)],
        "recall_all_positive": recall(pos_items),
        "recall_by_reference_tier": {
            t: recall([i for i in pos_items if i["tier"] == t])
            for t in ("serious", "moderate", "minor_or_other", "not_graded")
        },
        "false_alarm_any_pct": pct(fp, len(neg_items)),
        "false_alarm_needs_attention_pct": pct(fp_att, len(neg_items)),
        "false_alarm_worth_checking_or_higher_pct": pct(
            sum(i["severity"] in ATTENTION | {"moderate"} for i in neg_items), len(neg_items)
        ),
        "negative_flagged_by_our_severity": dict(
            Counter(i["severity"] for i in neg_items if i["flagged"])
        ),
        "precision_any_pct": pct(tp, tp + fp),
        "precision_needs_attention_pct": pct(tp_att, tp_att + fp_att),
        "flagged_positive_by_source": dict(Counter(i["source"] for i in pos_items if i["flagged"])),
        "flagged_negative_by_source": dict(Counter(i["source"] for i in neg_items if i["flagged"])),
        "confusion_reference_tier_vs_our_severity": confusion,
        "missed_serious_count": len(missed_serious),
        "missed_serious_examples": missed_serious[:40],
        # Negative controls we grade moderate or higher (ungraded DDInter listings are many and
        # are shown collapsed in the app, so they are counted above but not listed here).
        "false_alarm_moderate_or_higher_examples": sorted(
            f"{' + '.join(i['names'])} → {i['severity']} ({i['source']})"
            for i in neg_items
            if i["severity"] in ATTENTION | {"moderate"}
        )[:40],
    }


def main() -> None:
    result = run()
    path = write_result("interactions", result)
    for k, v in result.items():
        if not k.endswith("examples"):
            print(f"{k}: {v}")
    print("missed serious (first 15):", result["missed_serious_examples"][:15])
    print(
        "false alarms ≥ moderate (first 15):",
        result["false_alarm_moderate_or_higher_examples"][:15],
    )
    print("written", path)


if __name__ == "__main__":
    main()
