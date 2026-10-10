import type { Candidate, NormalisedLine, SearchHit } from "../api";
import type { Knowledge } from "./pack";

/**
 * Offline name lookup. Deliberately simpler than the server: names are matched exactly or by
 * prefix, never by typo-tolerant guessing. Typed text resolves only on an exact name match;
 * anything else is offered as choices for the user to confirm (honesty rule 8).
 */

const KIND_RANK: Record<string, number> = { india_brand: 0, ingredient: 1, synonym: 2, brand: 3 };
const SOURCE = "offline pack";
// Strength, unit and dose-form words that may follow a name ("Dolo 650 tab").
const NOISE = /^(\d+([.,]\d+)?(mg|mcg|g|ml|iu|%)?|mg|mcg|g|ml|iu|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|syp|syrup|inj|injection|susp|drops|od|bd|tds|ip|bp|usp)$/;

interface Row {
  norm: string;
  hit: SearchHit;
}

const index = new WeakMap<Knowledge, Row[]>();

export const normaliseText = (text: string): string =>
  text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

function rows(kb: Knowledge): Row[] {
  let out = index.get(kb);
  if (!out) {
    const rx = kb.pack.ingredients.map(([id]) => id);
    out = kb.pack.names.map(([text, kind, idx, ref]) => {
      const ingredients = idx.map((i) => rx[i]!);
      return {
        norm: normaliseText(text),
        hit: {
          label: text,
          kind,
          ingredients,
          ingredient_names: ingredients.map((r) => kb.names.get(r) ?? r),
          ref,
          source: SOURCE,
        },
      };
    });
    out.sort((a, b) => (KIND_RANK[a.hit.kind] ?? 9) - (KIND_RANK[b.hit.kind] ?? 9) || a.norm.length - b.norm.length);
    index.set(kb, out);
  }
  return out;
}

export function offlineSearch(query: string, kb: Knowledge, limit = 8): SearchHit[] {
  const q = normaliseText(query);
  if (q.length < 2) return [];
  const all = rows(kb);
  const starts = all.filter((r) => r.norm.startsWith(q));
  const inside = all.filter((r) => !r.norm.startsWith(q) && r.norm.includes(` ${q}`));
  const seen = new Set<string>();
  const out: SearchHit[] = [];
  for (const { hit } of [...starts, ...inside]) {
    const key = `${hit.label.toLowerCase()}|${hit.ingredients.join(",")}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(hit);
    if (out.length >= limit) break;
  }
  return out;
}

const asCandidate = (hit: SearchHit, confidence: number, method: string): Candidate => ({
  ...hit,
  confidence,
  method,
});

export function offlineNormalise(text: string, kb: Knowledge): NormalisedLine {
  // Try the whole text first ("Dolo 650" is a brand name), then without trailing strength or
  // dose-form words ("Warfarin 5 mg tab" → "warfarin").
  const tokens = normaliseText(text).split(" ").filter(Boolean);
  let query = tokens.join(" ");
  let exact = rows(kb).filter((r) => r.norm === query);
  while (exact.length === 0 && tokens.length > 1 && NOISE.test(tokens[tokens.length - 1]!)) {
    tokens.pop();
    query = tokens.join(" ");
    exact = rows(kb).filter((r) => r.norm === query);
  }
  const distinct = new Map(exact.map((r) => [r.hit.ingredients.join(","), r.hit]));
  const base = { raw: text, query, strengths: [], dose_form: null };

  if (distinct.size === 1) {
    const best = asCandidate([...distinct.values()][0]!, 1, "offline_exact");
    return { ...base, status: "resolved", confidence: 1, best, candidates: [best] };
  }
  const options = distinct.size > 1 ? [...distinct.values()] : offlineSearch(query, kb, 5);
  const candidates = options.map((h) => asCandidate(h, 0, "offline_prefix"));
  return {
    ...base,
    status: candidates.length > 0 ? "confirm" : "unknown",
    confidence: 0,
    best: null,
    candidates,
  };
}
