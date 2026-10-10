import type { CheckRequestItem, CheckResponse, Finding, PatientContext } from "../api";
import { checkOffline } from "./engine";
import type { Knowledge } from "./pack";

/**
 * A check computed on this device from the offline pack, in the same shape as the API's answer.
 * Partial by design: no recall/alert lists, no label notes, no patient-context checks. The
 * `offline` field makes the results page say so.
 */
export function runOfflineCheck(
  items: CheckRequestItem[],
  context: PatientContext,
  kb: Knowledge,
): CheckResponse {
  const known = items.filter((it) => it.selection?.ingredients.every((rx) => kb.names.has(rx)));
  const unknown = items.filter((it) => !known.includes(it));
  const result = checkOffline(
    known.map((it) => ({ id: it.id, label: it.text, ingredients: [...new Set(it.selection!.ingredients)].sort() })),
    kb,
  );
  const pack = kb.pack;
  return {
    summary: summarise(result.findings, known.length, unknown.length),
    medicines: known.map((it) => ({
      id: it.id,
      text: it.text,
      label: it.selection!.label,
      ingredients: [...new Set(it.selection!.ingredients)].sort().map((rx) => ({ rxcui: rx, name: kb.names.get(rx)! })),
      how: "selected",
      confidence: null,
      batch: it.batch ?? null,
    })),
    unresolved: unknown.map((it) => ({ id: it.id, text: it.text, status: "unknown", candidates: [] })),
    findings: result.findings,
    notes: [],
    recalls: { flags: [], ingredient_summaries: [], checklist: pack.checklist ?? [], coverage_notes: [] },
    no_known_issue_pairs: result.no_known_issue_pairs,
    disclaimer: pack.disclaimer ?? "",
    absence_note: pack.absence_note ?? "",
    data_versions: pack.datasets,
    offline: {
      generated_at: pack.generated_at,
      context_ignored: Boolean(context.age_group || context.pregnant || context.renal || context.hepatic),
    },
  };
}

// Port of backend app/core/summary.py (without recalls, which are not checked offline).
const ATTENTION = new Set(["contraindicated", "major"]);
const WORTH = new Set(["moderate"]);

export function summarise(findings: Finding[], checked: number, unresolved: number): CheckResponse["summary"] {
  const attention = findings.filter((f) => ATTENTION.has(f.severity)).length;
  const worth = findings.filter((f) => WORTH.has(f.severity)).length;
  return {
    headline: headline(attention, worth, checked, unresolved),
    needs_attention: attention,
    worth_checking: worth,
    other: findings.length - attention - worth,
    checked_medicines: checked,
    unresolved,
  };
}

function headline(attention: number, worth: number, checked: number, unresolved: number): string {
  if (checked === 0) return unresolved ? "Please confirm the medicines first" : "Add medicines to check";
  if (attention) return `${attention} ${attention === 1 ? "thing needs" : "things need"} attention`;
  if (worth) return `${worth} ${worth === 1 ? "thing is" : "things are"} worth checking`;
  return "No known issues found in our data";
}
