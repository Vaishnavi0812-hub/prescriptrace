import type { Evidence, Finding, Severity } from "../api";
import { pairKey, type Fact, type Knowledge, type RuleText } from "./pack";

/**
 * Offline interaction engine: a direct port of backend app/core/engine/engine.py, limited to what
 * the offline pack holds (no label-text mentions, no patient context). Kept in step with the
 * Python engine by shared test vectors (backend/tests/vectors/offline_engine.json): the same
 * medicines on the same data must give identical findings.
 */

export interface OfflineMedicine {
  id: string;
  label: string;
  ingredients: string[]; // RxCUIs
}

export interface OfflineResult {
  findings: Finding[];
  checked_pairs: number;
  no_known_issue_pairs: string[][];
  counts: Record<string, number>;
}

const SEVERITY_ORDER: Severity[] = ["contraindicated", "major", "moderate", "minor", "unknown"];
const rank = (s: Severity): number => SEVERITY_ORDER.indexOf(s);
const PROVENANCE_RANK: Record<Finding["provenance"], number> = { structured: 0, rule: 1, label_text: 2 };

type Members = Map<string, { med: OfflineMedicine; evidence: Evidence[] }>;
interface Group {
  key: string;
  label: string;
  members: Map<string, Evidence[]>;
}

export function checkOffline(meds: OfflineMedicine[], kb: Knowledge): OfflineResult {
  const rules = kb.pack.rules;
  const ruleEvidence = (id: string): Evidence => {
    const ev = rules.evidence[id];
    if (!ev) throw new Error(`no evidence for rule ${id}`);
    return ev;
  };
  const name = (rx: string): string => kb.names.get(rx) ?? rx;

  // ---------------------------------------------------------------- pairwise
  const pairs = new Map<string, Finding>(); // insertion order matters (as in Python dicts)
  const pairParts = new Map<string, [string, string, string, string]>(); // key -> (x, y, m1, m2)
  const quiet: string[][] = [];
  let checked = 0;
  for (let i = 0; i < meds.length; i++) {
    for (let j = i + 1; j < meds.length; j++) {
      const m1 = meds[i]!;
      const m2 = meds[j]!;
      let hit = false;
      for (const x of m1.ingredients) {
        for (const y of m2.ingredients) {
          if (x === y) continue; // same ingredient twice: reported as a duplicate instead
          checked += 1;
          const facts = kb.facts.get(pairKey(x, y));
          if (!facts?.length) continue;
          const [px, py] = sorted2(x, y);
          const key = JSON.stringify([px, py, m1.id, m2.id]);
          pairs.set(key, pairFinding(m1, m2, x, y, facts));
          pairParts.set(key, [px, py, m1.id, m2.id]);
          hit = true;
        }
      }
      if (!hit) quiet.push([m1.label, m2.label]);
    }
  }

  function pairFinding(m1: OfflineMedicine, m2: OfflineMedicine, x: string, y: string, facts: Fact[]): Finding {
    const a = name(x);
    const b = name(y);
    const severity = facts.map((f) => f.severity).reduce((s, t) => (rank(t) < rank(s) ? t : s));
    const sources = [...new Set(facts.map((f) => kb.datasets.get(f.dataset)?.name ?? f.dataset))]
      .sort(byCodePoint)
      .join(", ");
    const t = kb.pack.templates;
    return {
      id: `interaction:${sorted2(x, y).join("-")}:${m1.id}:${m2.id}`,
      type: "interaction",
      severity,
      medicines: [m1.id, m2.id],
      drug_labels: [m1.label, m2.label],
      ingredients: [a, b],
      ingredient_ids: [x, y],
      title: format(t.pair_title, { a: cap(a), b: cap(b) }),
      simple: t.pair_simple[severity],
      professional: format(t.pair_professional[severity], { sources }),
      consider: t.pair_consider[severity],
      evidence: facts.map((f) => evidence(f.dataset, f.ref, f.url, f.quote)),
      provenance: "structured",
      confidence: severity !== "unknown" ? "high" : "medium",
      rule_id: null,
      related: [],
      related_rules: [],
    };
  }

  function evidence(dataset: string, record: string, url: string | null, quote: string | null): Evidence {
    const meta = kb.datasets.get(dataset);
    return {
      dataset,
      dataset_name: meta ? meta.name : dataset,
      dataset_version: meta ? meta.version : null,
      record_id: record,
      url,
      quote,
    };
  }

  // ---------------------------------------------------------------- duplicates
  function duplicateIngredients(): Finding[] {
    const holders = new Map<string, OfflineMedicine[]>();
    for (const med of meds) {
      for (const rx of new Set(med.ingredients)) {
        holders.set(rx, [...(holders.get(rx) ?? []), med]);
      }
    }
    const out: Finding[] = [];
    for (const [rx, holding] of holders) {
      if (holding.length < 2) continue;
      const ingredient = name(rx);
      const labels = holding.map((m) => m.label);
      const tx = texts(rules.dup_ingredient.text, { ingredient, drugs: join(labels) });
      out.push({
        id: `duplicate_ingredient:${rx}`,
        type: "duplicate_ingredient",
        severity: rules.dup_ingredient.severity,
        medicines: holding.map((m) => m.id),
        drug_labels: labels,
        ingredients: [ingredient],
        ingredient_ids: [rx],
        ...tx,
        evidence: [ruleEvidence(rules.dup_ingredient.id)],
        provenance: "rule",
        confidence: "high",
        rule_id: rules.dup_ingredient.id,
        related: [],
        related_rules: [],
      });
    }
    return out;
  }

  function group(key: string): Group {
    const g = kb.groups.get(key);
    if (!g) throw new Error(`unknown rule group ${key}`);
    return g;
  }

  function membersOf(g: Group): Members {
    const out: Members = new Map();
    for (const med of meds) {
      for (const rx of med.ingredients) {
        const ev = g.members.get(rx);
        if (ev?.length && !out.has(rx)) out.set(rx, { med, evidence: ev });
      }
    }
    return out;
  }

  function duplicateClasses(): Finding[] {
    const out: Finding[] = [];
    for (const [key, severity] of rules.dup_class.groups) {
      const g = group(key);
      const members = membersOf(g);
      if (members.size < 2 || new Set([...members.values()].map((m) => m.med.id)).size < 2) continue;
      out.push(groupFinding("duplicate_class", rules.dup_class.id, severity, rules.dup_class.text, members, [g]));
    }
    return out;
  }

  // ---------------------------------------------------------------- cumulative
  function cumulative(): Finding[] {
    const out: Finding[] = [];
    for (const rule of rules.cumulative) {
      const groups = rule.groups.map(group);
      const members: Members = new Map();
      const covered = new Map<string, Set<string>>();
      for (const g of groups) {
        for (const [rx, { med, evidence: ev }] of membersOf(g)) {
          const entry = members.get(rx) ?? { med, evidence: [] };
          entry.evidence = [...entry.evidence, ...ev];
          members.set(rx, entry);
          covered.set(rx, new Set([...(covered.get(rx) ?? []), g.key]));
        }
      }
      if (triggers(rule, covered, members)) {
        out.push(groupFinding("cumulative", rule.id, rule.severity, rule.text, members, groups));
      }
    }
    return out;
  }

  function groupFinding(
    ftype: "duplicate_class" | "cumulative",
    ruleId: string,
    severity: Severity,
    text: RuleText,
    members: Members,
    groups: Group[],
  ): Finding {
    const rxs = [...members.keys()].sort(byCodePoint);
    const names = rxs.map(name);
    const labels = unique(rxs.map((r) => members.get(r)!.med.label));
    const tx = texts(text, {
      count: String(rxs.length),
      drugs: join(labels),
      ingredients: join(names),
      group: groups[0]!.label,
      groups: join(groups.map((g) => g.label)),
    });
    const ev = uniqueEvidence(rxs.flatMap((r) => members.get(r)!.evidence));
    const fromFlags = ev.some((e) => e.dataset === "openfda_label");
    const scope = ftype === "duplicate_class" ? groups[0]!.key : "";
    return {
      id: `${ftype}:${ruleId}:${scope}:${rxs.join("-")}`,
      type: ftype,
      severity,
      medicines: unique(rxs.map((r) => members.get(r)!.med.id)),
      drug_labels: labels,
      ingredients: names,
      ingredient_ids: rxs,
      ...tx,
      evidence: [...ev, ruleEvidence(ruleId)],
      provenance: "rule",
      confidence: fromFlags ? "medium" : "high",
      rule_id: ruleId,
      related: [],
      related_rules: [],
    };
  }

  /** A 2-drug rule finding about a pair that already has a pairwise card becomes a note on it. */
  function mergeIntoPair(finding: Finding): boolean {
    if (finding.ingredient_ids.length !== 2 || finding.medicines.length !== 2) return false;
    const [x, y] = sorted2(finding.ingredient_ids[0]!, finding.ingredient_ids[1]!);
    for (const [key, pair] of pairs) {
      const [kx, ky, k1, k2] = pairParts.get(key)!;
      if (kx === x && ky === y && sameSet([k1!, k2!], finding.medicines)) {
        const known = new Set(pair.evidence.map(evidenceKey));
        pairs.set(key, {
          ...pair,
          related: [...pair.related, `${finding.title}. ${finding.simple}`],
          related_rules: [...pair.related_rules, finding.rule_id ?? finding.type],
          evidence: [...pair.evidence, ...finding.evidence.filter((e) => !known.has(evidenceKey(e)))],
          severity: rank(finding.severity) < rank(pair.severity) ? finding.severity : pair.severity,
        });
        return true;
      }
    }
    return false;
  }

  // ---------------------------------------------------------------- run
  const extra = duplicateIngredients();
  for (const finding of [...duplicateClasses(), ...cumulative()]) {
    if (!mergeIntoPair(finding)) extra.push(finding);
  }
  const findings = [...pairs.values(), ...extra].sort(compareFindings);
  const counts: Record<string, number> = {};
  for (const f of findings) counts[f.severity] = (counts[f.severity] ?? 0) + 1;
  return { findings, checked_pairs: checked, no_known_issue_pairs: quiet, counts };
}

function triggers(
  rule: { min_drugs: number; min_groups: number; require_groups: string[][] },
  covered: Map<string, Set<string>>,
  members: Members,
): boolean {
  if (covered.size < rule.min_drugs || new Set([...members.values()].map((m) => m.med.id)).size < 2) {
    return false;
  }
  const allGroups = new Set([...covered.values()].flatMap((s) => [...s]));
  if (allGroups.size < rule.min_groups) return false;
  if (rule.require_groups.length === 0) return true;
  // Each required slot needs its own drug.
  const drugs = [...covered.keys()];
  const assign = (slot: number, used: Set<string>): boolean => {
    if (slot === rule.require_groups.length) return true;
    const wanted = rule.require_groups[slot]!;
    return drugs.some(
      (d) => !used.has(d) && wanted.some((g) => covered.get(d)!.has(g)) && assign(slot + 1, new Set([...used, d])),
    );
  };
  return assign(0, new Set());
}

// ---------------------------------------------------------------- helpers (as in engine.py)

function compareFindings(f: Finding, g: Finding): number {
  const a = [rank(f.severity), PROVENANCE_RANK[f.provenance], -f.ingredients.length];
  const b = [rank(g.severity), PROVENANCE_RANK[g.provenance], -g.ingredients.length];
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i]! - b[i]!;
  return byCodePoint(f.title, g.title);
}

/** Python's default string order (by code point), not the locale order. */
function byCodePoint(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sorted2(x: string, y: string): [string, string] {
  return x < y ? [x, y] : [y, x];
}

function format(template: string, values: Record<string, string>): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) => {
    const value = values[key];
    if (value === undefined) throw new Error(`missing value for {${key}}`);
    return value;
  });
}

function texts(t: RuleText, values: Record<string, string>): RuleText {
  return {
    title: format(t.title, values),
    simple: format(t.simple, values),
    professional: format(t.professional, values),
    consider: format(t.consider, values),
  };
}

function join(items: string[]): string {
  return items.length === 1 ? items[0]! : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]!}`;
}

function cap(text: string): string {
  return text.slice(0, 1).toUpperCase() + text.slice(1);
}

function unique<T>(items: T[]): T[] {
  return [...new Set(items)];
}

function sameSet(a: string[], b: string[]): boolean {
  const sa = new Set(a);
  const sb = new Set(b);
  return sa.size === sb.size && [...sa].every((x) => sb.has(x));
}

function evidenceKey(e: Evidence): string {
  return JSON.stringify([e.dataset, e.dataset_name, e.dataset_version, e.record_id, e.url, e.quote]);
}

function uniqueEvidence(items: Evidence[]): Evidence[] {
  const seen = new Set<string>();
  return items.filter((e) => {
    const k = evidenceKey(e);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}
