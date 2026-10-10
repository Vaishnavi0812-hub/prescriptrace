import { describe, expect, it } from "vitest";

import en from "./en.json";
import hi from "./hi.json";
import kn from "./kn.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  return Object.entries(tree).reduce<Record<string, string>>((out, [k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return typeof v === "string" ? { ...out, [key]: v } : { ...out, ...flatten(v, key) };
  }, {});
}

const placeholders = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();
const EN = flatten(en);

describe.each([
  ["hi", flatten(hi)],
  ["kn", flatten(kn)],
])("%s translation", (_, other) => {
  it("has exactly the English keys", () => {
    expect(Object.keys(other).sort()).toEqual(Object.keys(EN).sort());
  });

  it("keeps every {{placeholder}}", () => {
    for (const [key, text] of Object.entries(EN)) {
      expect([key, placeholders(other[key] ?? "")]).toEqual([key, placeholders(text)]);
    }
  });

  it("leaves no English sentence untranslated", () => {
    // Wording rules (no instruction to stop or change a medicine) are for native reviewers to
    // confirm; here we only make sure nothing was skipped.
    const untranslated = Object.entries(other).filter(
      ([key, text]) => text === EN[key] && /[a-z]{4,}\s[a-z]{4,}/i.test(text) && !key.startsWith("glossary"),
    );
    expect(untranslated).toEqual([]);
  });
});
