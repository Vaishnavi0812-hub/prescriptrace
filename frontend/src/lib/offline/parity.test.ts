import { describe, expect, it } from "vitest";

import { checkOffline, type OfflineMedicine, type OfflineResult } from "./engine";
import { decodePack, type OfflinePack } from "./pack";

/**
 * Optional real-data parity check. Generate the file first with
 * `docker compose run --rm backend python scripts/offline_parity.py` (it needs the loaded
 * database, so this is skipped in CI).
 */
interface ParityData {
  pack: OfflinePack;
  cases: { medicines: OfflineMedicine[]; expected: OfflineResult }[];
}
const files = import.meta.glob<ParityData>("../../../../data/cache/offline_parity.json", {
  eager: true,
  import: "default",
});
const data = Object.values(files)[0];

describe.skipIf(!data)("offline engine on real data", () => {
  it("matches the Python engine on every generated case", () => {
    const kb = decodePack(data!.pack);
    const mismatched = data!.cases.filter(
      (c) => JSON.stringify(checkOffline(c.medicines, kb)) !== JSON.stringify(c.expected),
    );
    if (mismatched[0]) expect(checkOffline(mismatched[0].medicines, kb)).toEqual(mismatched[0].expected);
    expect(mismatched.length).toBe(0);
  });
});
