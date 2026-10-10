"""The interaction engine: medicines + patient context + knowledge snapshot → ranked findings.

Pure and deterministic: the same inputs always give the same output, with no I/O. Every finding
carries the dataset records it is based on; nothing is reported without a source.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace

from app.core.engine import templates as t
from app.core.engine.model import (
    SEVERITY_RANK,
    CheckNote,
    CheckResult,
    ClassTag,
    Evidence,
    Finding,
    InteractionFact,
    KnowledgeSnapshot,
    Medicine,
    PatientContext,
)
from app.core.engine.rules import CumulativeRule, Group, RuleSet, Text, load_rules

DAILYMED = "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid={}"
PROVENANCE_RANK = {"structured": 0, "rule": 1, "label_text": 2}
MIN_MENTION_LEN = 5  # shorter ingredient names give false hits inside label prose
QUOTE_WINDOW = 220

Members = dict[str, tuple[Medicine, list[Evidence]]]  # rxcui -> (medicine, why it's in the group)
PairKey = tuple[str, str, str, str]  # (rx1, rx2, medicine1, medicine2), rx1 < rx2


def check(
    medicines: list[Medicine],
    snapshot: KnowledgeSnapshot,
    context: PatientContext | None = None,
    rules: RuleSet | None = None,
) -> CheckResult:
    return _Engine(medicines, snapshot, context or PatientContext(), rules or load_rules()).run()


class _Engine:
    def __init__(
        self, meds: list[Medicine], kb: KnowledgeSnapshot, ctx: PatientContext, rules: RuleSet
    ) -> None:
        self.meds = meds
        self.kb = kb
        self.ctx = ctx
        self.rules = rules
        self.facts: dict[tuple[str, str], list[InteractionFact]] = defaultdict(list)
        for fact in kb.interactions:
            self.facts[_pair(fact.a, fact.b)].append(fact)

    # ------------------------------------------------------------------ run

    def run(self) -> CheckResult:
        pairs, quiet, checked = self._pairwise()
        extra: list[Finding] = self._duplicate_ingredients()
        for finding in self._duplicate_classes() + self._cumulative():
            if not self._merge_into_pair(finding, pairs):
                extra.append(finding)
        extra += self._context_findings()
        findings = sorted([*pairs.values(), *extra], key=_rank)
        counts: dict[str, int] = defaultdict(int)
        for f in findings:
            counts[f.severity] += 1
        return CheckResult(
            findings=tuple(findings),
            notes=tuple(self._check_notes()),
            checked_pairs=checked,
            no_known_issue_pairs=tuple(quiet),
            counts=dict(counts),
        )

    # ------------------------------------------------------------------ pairwise

    def _pairwise(self) -> tuple[dict[PairKey, Finding], list[tuple[str, str]], int]:
        found: dict[PairKey, Finding] = {}
        quiet: list[tuple[str, str]] = []
        checked = 0
        for m1, m2 in itertools.combinations(self.meds, 2):
            hit = False
            for x, y in itertools.product(m1.ingredients, m2.ingredients):
                if x == y:
                    continue  # same ingredient twice: reported as a duplicate instead
                checked += 1
                finding = self._pair_finding(m1, m2, x, y)
                if finding is not None:
                    found[(*_pair(x, y), m1.id, m2.id)] = finding
                    hit = True
            if not hit:
                quiet.append((m1.label, m2.label))
        return found, quiet, checked

    def _pair_finding(self, m1: Medicine, m2: Medicine, x: str, y: str) -> Finding | None:
        facts = self.facts.get(_pair(x, y), [])
        quotes = [q for q in (self._label_mention(x, y), self._label_mention(y, x)) if q]
        if not facts and not quotes:
            return None
        a, b = self.kb.names.get(x, x), self.kb.names.get(y, y)
        if facts:
            severity = min((f.severity for f in facts), key=SEVERITY_RANK.__getitem__)
            sources = ", ".join(sorted({self._dataset_name(f.dataset) for f in facts}))
            texts = Text(
                title=t.PAIR_TITLE.format(a=_cap(a), b=_cap(b)),
                simple=t.PAIR_SIMPLE[severity],
                professional=t.PAIR_PROFESSIONAL[severity].format(sources=sources),
                consider=t.PAIR_CONSIDER[severity],
            )
            evidence = [self._fact_evidence(f) for f in facts] + quotes
            provenance, confidence = "structured", ("high" if severity != "unknown" else "medium")
        else:
            severity = "unknown"
            mentioner, other = (a, b) if quotes[0].record_id.endswith(f"ingredient={x}") else (b, a)
            texts = Text(
                title=t.PAIR_TITLE.format(a=_cap(a), b=_cap(b)),
                simple=t.LABEL_ONLY_SIMPLE.format(a=_cap(mentioner), b=other),
                professional=t.LABEL_ONLY_PROFESSIONAL.format(a=mentioner),
                consider=t.LABEL_ONLY_CONSIDER,
            )
            evidence, provenance, confidence = quotes, "label_text", "low"
        return Finding(
            id=f"interaction:{'-'.join(_pair(x, y))}:{m1.id}:{m2.id}",
            type="interaction",
            severity=severity,
            medicines=(m1.id, m2.id),
            drug_labels=(m1.label, m2.label),
            ingredients=(a, b),
            ingredient_ids=(x, y),
            title=texts.title,
            simple=texts.simple,
            professional=texts.professional,
            consider=texts.consider,
            evidence=tuple(evidence),
            provenance=provenance,
            confidence=confidence,
        )

    def _label_mention(self, mentioner: str, other: str) -> Evidence | None:
        """Quote from `mentioner`'s label drug-interactions section that names `other`."""
        label = self.kb.labels.get(mentioner)
        if label is None or not label.drug_interactions:
            return None
        for name in (self.kb.names.get(other, ""), *self.kb.synonyms.get(other, [])):
            if len(name) < MIN_MENTION_LEN:
                continue
            text = label.drug_interactions
            match = re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)
            if match:
                start = max(0, match.start() - QUOTE_WINDOW)
                quote = text[start : match.end() + QUOTE_WINDOW].strip()
                return self._evidence(
                    "openfda_label",
                    f"set_id={label.set_id};ingredient={mentioner}",
                    DAILYMED.format(label.set_id),
                    ("… " if start else "") + quote + " …",
                )
        return None

    # ------------------------------------------------------------------ duplicates

    def _duplicate_ingredients(self) -> list[Finding]:
        holders: dict[str, list[Medicine]] = defaultdict(list)
        for med in self.meds:
            for rx in dict.fromkeys(med.ingredients):
                holders[rx].append(med)
        out = []
        for rx, meds in holders.items():
            if len(meds) < 2:
                continue
            name = self.kb.names.get(rx, rx)
            labels = tuple(m.label for m in meds)
            tx = _texts(
                self.rules.dup_ingredient_text, {"ingredient": name, "drugs": _join(labels)}
            )
            out.append(
                Finding(
                    id=f"duplicate_ingredient:{rx}",
                    type="duplicate_ingredient",
                    severity=self.rules.dup_ingredient_severity,
                    medicines=tuple(m.id for m in meds),
                    drug_labels=labels,
                    ingredients=(name,),
                    ingredient_ids=(rx,),
                    title=tx.title,
                    simple=tx.simple,
                    professional=tx.professional,
                    consider=tx.consider,
                    evidence=(self._rule_evidence(self.rules.dup_ingredient_id),),
                    provenance="rule",
                    confidence="high",
                    rule_id=self.rules.dup_ingredient_id,
                )
            )
        return out

    def _duplicate_classes(self) -> list[Finding]:
        out = []
        for key, severity in self.rules.dup_class_groups.items():
            group = self.rules.groups[key]
            members = self._members(group)
            if len(members) < 2 or len({med.id for med, _ in members.values()}) < 2:
                continue
            out.append(
                self._group_finding(
                    "duplicate_class",
                    self.rules.dup_class_id,
                    severity,
                    self.rules.dup_class_text,
                    members,
                    [group],
                )
            )
        return out

    # ------------------------------------------------------------------ cumulative

    def _cumulative(self) -> list[Finding]:
        out = []
        for rule in self.rules.cumulative:
            groups = [self.rules.groups[g] for g in rule.groups]
            members: Members = {}
            covered: dict[str, set[str]] = defaultdict(set)  # rxcui -> group keys
            for group in groups:
                for rx, (med, ev) in self._members(group).items():
                    members.setdefault(rx, (med, []))[1].extend(ev)
                    covered[rx].add(group.key)
            if _triggers(rule, covered, members):
                out.append(
                    self._group_finding(
                        "cumulative", rule.id, rule.severity, rule.text, members, groups
                    )
                )
        return out

    def _members(self, group: Group) -> Members:
        out: Members = {}
        for med in self.meds:
            for rx in med.ingredients:
                evidence = self._group_evidence(rx, group)
                if evidence and rx not in out:
                    out[rx] = (med, evidence)
        return out

    def _group_evidence(self, rx: str, group: Group) -> list[Evidence]:
        tags = self.kb.classes.get(rx, [])
        out: list[Evidence] = []
        for sel in group.selectors:
            if sel.kind == "ING" and self.kb.names.get(rx) == sel.value:
                out.append(self._rule_evidence(f"group {group.key}: {sel.value}"))
            out.extend(
                self._tag_evidence(rx, tag)
                for tag in tags
                if _selector_matches(sel.kind, sel.value, tag)
            )
        return _unique(out)

    def _group_finding(
        self,
        ftype: str,
        rule_id: str,
        severity: str,
        text: Text,
        members: Members,
        groups: list[Group],
    ) -> Finding:
        rxs = tuple(sorted(members))
        names = tuple(self.kb.names.get(r, r) for r in rxs)
        labels = tuple(dict.fromkeys(members[r][0].label for r in rxs))
        fmt = {
            "count": str(len(rxs)),
            "drugs": _join(labels),
            "ingredients": _join(names),
            "group": groups[0].label,
            "groups": _join([g.label for g in groups]),
        }
        evidence = _unique([e for r in rxs for e in members[r][1]])
        from_flags = any(e.dataset == "openfda_label" for e in evidence)
        scope = groups[0].key if ftype == "duplicate_class" else ""
        tx = _texts(text, fmt)
        return Finding(
            id=f"{ftype}:{rule_id}:{scope}:{'-'.join(rxs)}",
            type=ftype,
            severity=severity,
            medicines=tuple(dict.fromkeys(members[r][0].id for r in rxs)),
            drug_labels=labels,
            ingredients=names,
            ingredient_ids=rxs,
            title=tx.title,
            simple=tx.simple,
            professional=tx.professional,
            consider=tx.consider,
            evidence=(*evidence, self._rule_evidence(rule_id)),
            provenance="rule",
            confidence="medium" if from_flags else "high",
            rule_id=rule_id,
        )

    def _merge_into_pair(self, finding: Finding, pairs: dict[PairKey, Finding]) -> bool:
        """A 2-drug rule finding about a pair that already has a pairwise finding becomes a
        note on that card instead of a second card (less alert fatigue, nothing lost)."""
        if len(finding.ingredient_ids) != 2 or len(finding.medicines) != 2:
            return False
        x, y = _pair(*finding.ingredient_ids)
        for key, pair in pairs.items():
            if key[:2] == (x, y) and set(key[2:]) == set(finding.medicines):
                pairs[key] = replace(
                    pair,
                    related=(*pair.related, f"{finding.title}. {finding.simple}"),
                    related_rules=(*pair.related_rules, finding.rule_id or finding.type),
                    evidence=(
                        *pair.evidence,
                        *(e for e in finding.evidence if e not in pair.evidence),
                    ),
                    severity=min(pair.severity, finding.severity, key=SEVERITY_RANK.__getitem__),
                )
                return True
        return False

    # ------------------------------------------------------------------ patient context

    def _context_findings(self) -> list[Finding]:
        active = self.ctx.active()
        present = {rx: med for med in self.meds for rx in med.ingredients}
        merged: dict[tuple[str, str], Finding] = {}
        for fact in self.kb.context:
            med = present.get(fact.rxcui)
            if fact.kind != "contraindication" or fact.context not in active or med is None:
                continue
            name = self.kb.names.get(fact.rxcui, fact.rxcui)
            ctx = t.CONTEXT_LABEL[fact.context]
            evidence = self._evidence(fact.dataset, fact.source_ref, None, fact.text)
            key = (med.id, f"{fact.rxcui}:{fact.context}")
            if key in merged:  # one card per drug and context, all MED-RT entries as evidence
                merged[key] = replace(merged[key], evidence=(*merged[key].evidence, evidence))
                continue
            merged[key] = Finding(
                id=f"context:{fact.context}:{fact.rxcui}:{med.id}",
                type="context",
                severity="contraindicated",
                medicines=(med.id,),
                drug_labels=(med.label,),
                ingredients=(name,),
                ingredient_ids=(fact.rxcui,),
                title=t.CONTEXT_TITLE.format(drug=_cap(name), context=ctx),
                simple=t.CONTEXT_SIMPLE.format(drug=_cap(name), context=ctx),
                professional=t.CONTEXT_PROFESSIONAL.format(detail=fact.text),
                consider=t.CONTEXT_CONSIDER.format(drug=name),
                evidence=(evidence,),
                provenance="structured",
                confidence="high",
            )
        return list(merged.values())

    def _check_notes(self) -> Iterable[CheckNote]:
        active = self.ctx.active()
        for med in self.meds:
            for fact in self.kb.context:
                if (
                    fact.kind != "check_label"
                    or fact.context not in active
                    or fact.rxcui not in med.ingredients
                ):
                    continue
                set_id = fact.source_ref.removeprefix("set_id=")
                yield CheckNote(
                    context=fact.context,
                    medicine=med.label,
                    ingredient=self.kb.names.get(fact.rxcui, fact.rxcui),
                    text=fact.text,
                    evidence=self._evidence(
                        fact.dataset, fact.source_ref, DAILYMED.format(set_id), fact.text
                    ),
                )

    # ------------------------------------------------------------------ evidence

    def _dataset_name(self, code: str) -> str:
        meta = self.kb.datasets.get(code)
        return meta.name if meta else code

    def _evidence(self, dataset: str, record: str, url: str | None, quote: str | None) -> Evidence:
        meta = self.kb.datasets.get(dataset)
        return Evidence(
            dataset,
            meta.name if meta else dataset,
            meta.version if meta else None,
            record,
            url,
            quote,
        )

    def _fact_evidence(self, fact: InteractionFact) -> Evidence:
        return self._evidence(fact.dataset, fact.source_ref, fact.source_url, fact.evidence_text)

    def _tag_evidence(self, rx: str, tag: ClassTag) -> Evidence:
        name = self.kb.names.get(rx, rx)
        if tag.source == "LABEL_FLAG":
            set_id, _, quote = (tag.evidence or "").partition(";")
            set_id = set_id.removeprefix("set_id=")
            return self._evidence(
                tag.dataset,
                f"{tag.class_id}: {name}",
                DAILYMED.format(set_id) if set_id else None,
                quote.strip() or None,
            )
        return self._evidence(
            tag.dataset, f"{tag.source} {tag.class_id} ({tag.name}): {name}", None, None
        )

    def _rule_evidence(self, rule_id: str) -> Evidence:
        return rule_evidence(self.rules, rule_id)


def _triggers(rule: CumulativeRule, covered: dict[str, set[str]], members: Members) -> bool:
    if len(covered) < rule.min_drugs or len({m.id for m, _ in members.values()}) < 2:
        return False
    if len(set().union(*covered.values())) < rule.min_groups:
        return False
    if not rule.require_groups:
        return True
    # Each required slot needs its own drug (lists are tiny, so brute force is fine).
    for combo in itertools.permutations(covered, len(rule.require_groups)):
        if all(covered[d] & set(slot) for d, slot in zip(combo, rule.require_groups, strict=True)):
            return True
    return False


def group_memberships(
    snapshot: KnowledgeSnapshot, rules: RuleSet
) -> dict[str, dict[str, list[Evidence]]]:
    """Every ingredient's rule-group membership, with the evidence the engine would cite:
    {group key: {rxcui: evidence}}. Used by the offline-pack builder so the offline engine
    uses exactly the same membership and sources as this one."""
    engine = _Engine([], snapshot, PatientContext(), rules)
    out: dict[str, dict[str, list[Evidence]]] = {}
    for key, group in rules.groups.items():
        members = {}
        for rx in sorted(snapshot.names):
            evidence = engine._group_evidence(rx, group)
            if evidence:
                members[rx] = evidence
        out[key] = members
    return out


def rule_evidence(rules: RuleSet, rule_id: str) -> Evidence:
    return Evidence("rules", "PrescripTrace rule table (rules.yaml)", f"v{rules.version}", rule_id)


def _selector_matches(kind: str, value: str, tag: ClassTag) -> bool:
    if kind == "EPC":
        return tag.source == "EPC" and tag.name == value
    if kind == "ATC":
        return tag.source == "ATC" and tag.class_id == value
    if kind == "FLAG":
        return (
            tag.source == "LABEL_FLAG"
            and tag.class_id == value
            and tag.review_status in ("auto", "accepted")
        )
    return False


def _texts(text: Text, fmt: dict[str, str]) -> Text:
    return Text(
        title=text.title.format(**fmt),
        simple=text.simple.format(**fmt),
        professional=text.professional.format(**fmt),
        consider=text.consider.format(**fmt),
    )


def _pair(x: str, y: str) -> tuple[str, str]:
    return (x, y) if x < y else (y, x)


def _rank(f: Finding) -> tuple[int, int, int, str]:
    return (SEVERITY_RANK[f.severity], PROVENANCE_RANK[f.provenance], -len(f.ingredients), f.title)


def _join(items: Iterable[str]) -> str:
    seq = list(items)
    return seq[0] if len(seq) == 1 else ", ".join(seq[:-1]) + " and " + seq[-1]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _unique(evidence: list[Evidence]) -> list[Evidence]:
    return list(dict.fromkeys(evidence))
