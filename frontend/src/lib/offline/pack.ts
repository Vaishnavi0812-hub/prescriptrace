import type { ChecklistItem, Evidence, Severity } from "../api";

/** The offline pack as served by GET /api/v1/offline-pack (see backend app/core/offline_pack.py). */

export interface RuleText {
  title: string;
  simple: string;
  professional: string;
  consider: string;
}

/** [dataset index, severity index, record id, URL after the dataset's prefix, quote?] */
export type PackFact = [number, number, string, string | null, string?];

export interface OfflinePack {
  format: number;
  version: string;
  generated_at: string;
  // Fixed wording (added by the API; absent from the test vectors).
  licence_notice?: string;
  disclaimer?: string;
  absence_note?: string;
  checklist?: ChecklistItem[];
  datasets: { code: string; name: string; version: string | null; licence: string }[];
  severities: Severity[];
  pair_datasets: string[];
  url_prefixes: string[];
  ingredients: [string, string][];
  /** [display text, kind, ingredient indexes, ref] */
  names: [string, string, number[], string][];
  pairs: [number, number, PackFact[]][];
  groups: Record<string, { label: string; members: [number, Evidence[]][] }>;
  rules: {
    version: number;
    evidence: Record<string, Evidence>;
    dup_ingredient: { id: string; severity: Severity; text: RuleText };
    dup_class: { id: string; text: RuleText; groups: [string, Severity][] };
    cumulative: {
      id: string;
      groups: string[];
      min_drugs: number;
      min_groups: number;
      require_groups: string[][];
      severity: Severity;
      text: RuleText;
    }[];
  };
  templates: {
    pair_title: string;
    pair_simple: Record<Severity, string>;
    pair_professional: Record<Severity, string>;
    pair_consider: Record<Severity, string>;
  };
}

export const SUPPORTED_FORMAT = 1;

export interface Fact {
  dataset: string;
  severity: Severity;
  ref: string;
  url: string | null;
  quote: string | null;
}

/** The pack decoded into lookup tables (built once after loading). */
export interface Knowledge {
  pack: OfflinePack;
  names: Map<string, string>; // rxcui -> ingredient name
  facts: Map<string, Fact[]>; // "a|b" (a < b) -> source records
  groups: Map<string, { key: string; label: string; members: Map<string, Evidence[]> }>;
  datasets: Map<string, { name: string; version: string | null }>;
}

export const pairKey = (x: string, y: string): string => (x < y ? `${x}|${y}` : `${y}|${x}`);

export function decodePack(pack: OfflinePack): Knowledge {
  if (pack.format !== SUPPORTED_FORMAT) throw new Error(`unsupported offline pack format ${pack.format}`);
  const rx = pack.ingredients.map(([id]) => id);
  const names = new Map(pack.ingredients);
  const facts = new Map<string, Fact[]>();
  for (const [a, b, list] of pack.pairs) {
    facts.set(
      pairKey(rx[a]!, rx[b]!),
      list.map(([ds, sev, ref, url, quote]) => ({
        dataset: pack.pair_datasets[ds]!,
        severity: pack.severities[sev]!,
        ref,
        url: url === null ? null : pack.url_prefixes[ds]! + url,
        quote: quote ?? null,
      })),
    );
  }
  const groups = new Map(
    Object.entries(pack.groups).map(([key, g]) => [
      key,
      { key, label: g.label, members: new Map(g.members.map(([i, ev]) => [rx[i]!, ev])) },
    ]),
  );
  const datasets = new Map(pack.datasets.map((d) => [d.code, { name: d.name, version: d.version }]));
  return { pack, names, facts, groups, datasets };
}
