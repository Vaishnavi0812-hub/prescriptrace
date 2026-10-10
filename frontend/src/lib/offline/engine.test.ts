import { describe, expect, it } from "vitest";

import rawVectors from "../../../../backend/tests/vectors/offline_engine.json";
import { checkOffline, type OfflineMedicine, type OfflineResult } from "./engine";
import { decodePack, type OfflinePack } from "./pack";

/**
 * Shared vectors written by the Python engine (backend/tests/unit/test_offline_pack.py). The
 * TypeScript engine must give exactly the same result on the same pack, so offline checks never
 * drift from online ones.
 */
const vectors = rawVectors as unknown as {
  pack: OfflinePack;
  cases: { name: string; medicines: OfflineMedicine[]; expected: OfflineResult }[];
};
const kb = decodePack(vectors.pack);

describe("offline engine matches the Python engine", () => {
  it("has cases covering every finding type", () => {
    const types = new Set(vectors.cases.flatMap((c) => c.expected.findings.map((f) => f.type)));
    expect([...types].sort()).toEqual(["cumulative", "duplicate_class", "duplicate_ingredient", "interaction"]);
    expect(vectors.cases.some((c) => c.expected.findings.some((f) => f.related.length > 0))).toBe(true);
  });

  it.each(vectors.cases.map((c) => [c.name, c] as const))("%s", (_, c) => {
    expect(checkOffline(c.medicines, kb)).toEqual(c.expected);
  });
});

describe("offline engine safety", () => {
  it("never reports an unsourced finding", () => {
    for (const c of vectors.cases) {
      for (const f of checkOffline(c.medicines, kb).findings) {
        expect(f.evidence.length).toBeGreaterThan(0);
        for (const e of f.evidence) expect(e.record_id).toBeTruthy();
      }
    }
  });

  it("rejects a pack in an unknown format", () => {
    expect(() => decodePack({ ...vectors.pack, format: 99 })).toThrow(/format/);
  });
});
