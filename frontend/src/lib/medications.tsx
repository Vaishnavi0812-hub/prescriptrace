import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { normaliseLines, type Candidate, type PatientContext, type SearchHit } from "./api";

/**
 * The medicine list and patient context. Privacy by default: kept only in this browser tab's
 * sessionStorage (cleared when the tab closes). No names or IDs are ever collected.
 */

export type MedStatus = "pending" | "resolved" | "confirm" | "unknown" | "error";

export interface Picked {
  ref: string | null;
  label: string;
  ingredients: string[];
  ingredientNames: string[];
}

export interface Med {
  id: string;
  text: string;
  status: MedStatus;
  picked: Picked | null;
  candidates: Candidate[];
  strength: string;
  batch: string;
}

interface Store {
  meds: Med[];
  context: PatientContext;
}

const KEY = "prescriptrace.session.v1";
const EMPTY: Store = {
  meds: [],
  context: { age_group: null, pregnant: false, renal: false, hepatic: false },
};

function load(): Store {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Store;
    // A lookup that was in flight when the page closed is retried.
    return {
      ...parsed,
      meds: parsed.meds.map((m) => (m.status === "pending" ? { ...m, status: "error" } : m)),
    };
  } catch {
    return EMPTY;
  }
}

function save(store: Store): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    // storage blocked (private mode): the list still works for this page view
  }
}

let counter = 0;
const newId = (): string => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

export const fromCandidate = (c: Candidate | SearchHit): Picked => ({
  ref: c.ref,
  label: c.label,
  ingredients: c.ingredients,
  ingredientNames: c.ingredient_names,
});

interface MedicationsApi extends Store {
  addPicked: (hit: SearchHit) => void;
  addTyped: (text: string) => void;
  addCandidate: (text: string, candidate: Candidate) => void;
  choose: (id: string, candidate: Candidate) => void;
  retry: (id: string) => void;
  remove: (id: string) => void;
  setBatch: (id: string, batch: string) => void;
  setContext: (context: PatientContext) => void;
  clear: () => void;
  ready: boolean; // every medicine is confirmed and there is at least one
}

const Ctx = createContext<MedicationsApi | null>(null);

export function MedicationsProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<Store>(load);
  useEffect(() => save(store), [store]);

  const update = useCallback((id: string, patch: Partial<Med>) => {
    setStore((s) => ({ ...s, meds: s.meds.map((m) => (m.id === id ? { ...m, ...patch } : m)) }));
  }, []);

  const recognise = useCallback(
    (id: string, text: string) => {
      update(id, { status: "pending" });
      normaliseLines([text])
        .then(({ results }) => {
          const r = results[0];
          if (!r) return update(id, { status: "error" });
          const strength = r.strengths.map((s) => s.value + (s.unit ? ` ${s.unit}` : "")).join(", ");
          update(id, {
            status: r.status,
            picked: r.status === "resolved" && r.best ? fromCandidate(r.best) : null,
            candidates: r.candidates,
            strength,
          });
        })
        .catch(() => update(id, { status: "error" }));
    },
    [update],
  );

  const api = useMemo<MedicationsApi>(
    () => ({
      ...store,
      addPicked: (hit) =>
        setStore((s) => ({
          ...s,
          meds: [
            ...s.meds,
            {
              id: newId(),
              text: hit.label,
              status: "resolved",
              picked: fromCandidate(hit),
              candidates: [],
              strength: "",
              batch: "",
            },
          ],
        })),
      addTyped: (text) => {
        const id = newId();
        setStore((s) => ({
          ...s,
          meds: [
            ...s.meds,
            { id, text, status: "pending", picked: null, candidates: [], strength: "", batch: "" },
          ],
        }));
        recognise(id, text);
      },
      addCandidate: (text, candidate) =>
        setStore((s) => ({
          ...s,
          meds: [
            ...s.meds,
            {
              id: newId(),
              text,
              status: "resolved",
              picked: fromCandidate(candidate),
              candidates: [],
              strength: "",
              batch: "",
            },
          ],
        })),
      choose: (id, candidate) =>
        update(id, { status: "resolved", picked: fromCandidate(candidate) }),
      retry: (id) => {
        const med = store.meds.find((m) => m.id === id);
        if (med) recognise(id, med.text);
      },
      remove: (id) => setStore((s) => ({ ...s, meds: s.meds.filter((m) => m.id !== id) })),
      setBatch: (id, batch) => update(id, { batch }),
      setContext: (context) => setStore((s) => ({ ...s, context })),
      clear: () => setStore(EMPTY),
      ready: store.meds.length > 0 && store.meds.every((m) => m.status === "resolved" && m.picked),
    }),
    [store, recognise, update],
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useMedications(): MedicationsApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMedications must be used inside MedicationsProvider");
  return ctx;
}
