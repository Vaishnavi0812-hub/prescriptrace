import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { CheckResponse } from "./lib/api";

// ---------------------------------------------------------------- fake API

const DOLO = {
  label: "Dolo 650", kind: "india_brand", ingredients: ["161"],
  ingredient_names: ["acetaminophen"], ref: "india_brand:3", source: "india_brands",
};
const WARFARIN = {
  label: "warfarin", kind: "ingredient", ingredients: ["11289"],
  ingredient_names: ["warfarin"], ref: "ingredient:11289", source: "rxnorm_prescribe",
};

function finding(over: Partial<CheckResponse["findings"][number]>): CheckResponse["findings"][number] {
  return {
    id: "f1", type: "interaction", severity: "major", medicines: ["a", "b"],
    drug_labels: ["Warfarin", "Dolo 650"], ingredients: ["warfarin", "acetaminophen"],
    ingredient_ids: ["11289", "161"], title: "Warfarin + Acetaminophen",
    simple: "Taking these two together can cause serious harm.",
    professional: "Major interaction (DDInter 2.0).",
    consider: "Consider confirming with the prescriber before these are dispensed together.",
    evidence: [{ dataset: "ddinter", dataset_name: "DDInter 2.0", dataset_version: "2.0",
                 record_id: "DDInter1|DDInter2", url: "https://ddinter2.scbdd.com/x", quote: null }],
    provenance: "structured", confidence: "high", rule_id: null, related: [], related_rules: [],
    ...over,
  };
}

function checkResponse(over: Partial<CheckResponse> = {}): CheckResponse {
  return {
    summary: { headline: "1 thing needs attention", needs_attention: 1, worth_checking: 1,
               other: 0, checked_medicines: 2, unresolved: 0 },
    medicines: [],
    unresolved: [],
    findings: [
      finding({ id: "mod", severity: "moderate", title: "Moderate pair" }),
      finding({ id: "dup", type: "duplicate_ingredient", title: "The same medicine appears more than once" }),
      finding({ id: "maj" }),
    ],
    notes: [],
    recalls: { flags: [], ingredient_summaries: [], checklist: [
      { id: "qr_code", check: "Scan the QR code", why: "Top 300 brands carry one.",
        source: "CDSCO", source_url: "https://cdsco.gov.in/x" }], coverage_notes: [] },
    no_known_issue_pairs: [],
    disclaimer: "Decision support only.",
    absence_note: "\"No known issues\" means nothing was found in our data. It is not proof.",
    data_versions: [{ code: "ddinter", name: "DDInter 2.0", version: "2.0", licence: "CC BY-NC-SA 4.0" }],
    ...over,
  };
}

type Handler = (url: string, init?: RequestInit) => unknown;

let checkHandler: Handler = () => checkResponse();
let normaliseHandler: Handler = () => ({ results: [] });

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  checkHandler = () => checkResponse();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/health")) return json({ status: "ok", database: true, datasets_loaded: 9 });
      if (url.includes("/drugs/search")) {
        const q = new URL(url).searchParams.get("q") ?? "";
        return json({ query: q, hits: [DOLO, WARFARIN].filter((h) => h.label.toLowerCase().startsWith(q.toLowerCase())) });
      }
      if (url.includes("/normalise")) return json(normaliseHandler(url, init));
      if (url.includes("/check")) {
        const out = checkHandler(url, init);
        return out instanceof Response ? out : json(out);
      }
      return json({}, 404);
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function renderApp(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function addByPicking(user: ReturnType<typeof userEvent.setup>, typed: string, option: RegExp) {
  await user.type(screen.getByRole("combobox", { name: "Add medicine" }), typed);
  await user.click(await screen.findByRole("option", { name: option }));
}

// ---------------------------------------------------------------- tests

describe("adding medicines", () => {
  it("picks from autocomplete with the keyboard and shows what it contains", async () => {
    const user = userEvent.setup();
    renderApp();
    const box = screen.getByRole("combobox", { name: "Add medicine" });
    await user.type(box, "dol");
    await screen.findByRole("option", { name: /Dolo 650/ });
    await user.keyboard("{ArrowDown}{Enter}");
    const card = await screen.findByText("Dolo 650", { selector: "p" });
    expect(within(card.closest("li")!).getByText(/Contains: acetaminophen/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check safety" })).toBeEnabled();
  });

  it("asks to confirm an unclear typed name and blocks the check until confirmed", async () => {
    normaliseHandler = () => ({
      results: [{ raw: "amlodipin", query: "amlodipin", status: "confirm", confidence: 0.85,
        best: null, strengths: [], dose_form: null,
        candidates: [{ label: "amlodipine", kind: "ingredient", ingredients: ["17767"],
          ingredient_names: ["amlodipine"], confidence: 0.85, method: "prefix",
          ref: "ingredient:17767", source: "rxnorm" }] }],
    });
    const user = userEvent.setup();
    renderApp();
    await user.type(screen.getByRole("combobox", { name: "Add medicine" }), "amlodipin{Enter}");
    expect(await screen.findByText("Please confirm which medicine this is")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check safety" })).toBeDisabled();
    expect(screen.getByText("1 medicine still needs confirming")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /amlodipine/ }));
    expect(screen.getByRole("button", { name: "Check safety" })).toBeEnabled();
  });

  it("removes a medicine", async () => {
    const user = userEvent.setup();
    renderApp();
    await addByPicking(user, "dol", /Dolo 650/);
    await user.click(screen.getByRole("button", { name: "Remove Dolo 650" }));
    expect(screen.getByText(/No medicines yet/)).toBeInTheDocument();
  });

  it("keeps the list only in session storage", async () => {
    const user = userEvent.setup();
    renderApp();
    await addByPicking(user, "dol", /Dolo 650/);
    expect(sessionStorage.getItem("prescriptrace.session.v1")).toContain("Dolo 650");
    expect(JSON.stringify(localStorage)).not.toContain("Dolo 650");
  });
});

describe("results", () => {
  async function goToResults(user: ReturnType<typeof userEvent.setup>) {
    renderApp();
    await addByPicking(user, "war", /warfarin/);
    await addByPicking(user, "dol", /Dolo 650/);
    await user.type(screen.getByRole("combobox", { name: "Add medicine" }), "{Escape}");
    await user.click(screen.getByRole("button", { name: "Check safety" }));
  }

  it("shows the headline, then sections in the agreed order, severity as text", async () => {
    const user = userEvent.setup();
    await goToResults(user);
    expect(await screen.findByRole("heading", { level: 1, name: /1 thing needs attention/ })).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Needs attention", "Recalls and quality alerts", "Duplicate medicines", "Worth checking"]);
    expect(screen.getAllByText("Major").length).toBeGreaterThan(0); // label, not only colour
    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });

  it("sends the picked ingredients and batch, never asking the server to guess", async () => {
    const user = userEvent.setup();
    let sent: { items: { selection?: { ingredients: string[] } }[] } | null = null;
    checkHandler = (_url, init) => {
      sent = JSON.parse(String(init?.body));
      return checkResponse();
    };
    await goToResults(user);
    await screen.findByRole("heading", { level: 1 });
    expect(sent!.items.map((i) => i.selection?.ingredients)).toEqual([["11289"], ["161"]]);
  });

  it("switches between simple and professional explanations and shows sources", async () => {
    const user = userEvent.setup();
    await goToResults(user);
    const card = (await screen.findByText("Warfarin + Acetaminophen")).closest("li")!;
    expect(within(card).getByText(/can cause serious harm/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Professional" }));
    expect(within(card).getByText(/Major interaction \(DDInter 2.0\)/)).toBeInTheDocument();
    await user.click(within(card).getByText(/Show source/));
    expect(within(card).getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href", "https://ddinter2.scbdd.com/x");
  });

  it("words 'no known issues' carefully", async () => {
    checkHandler = () => checkResponse({
      summary: { headline: "No known issues found in our data", needs_attention: 0, worth_checking: 0,
                 other: 0, checked_medicines: 2, unresolved: 0 },
      findings: [], no_known_issue_pairs: [["Warfarin", "Dolo 650"]],
    });
    const user = userEvent.setup();
    await goToResults(user);
    expect(await screen.findAllByText("No known issues found in our data")).not.toHaveLength(0);
    expect(screen.getByText(/It is not proof/)).toBeInTheDocument();
  });

  it("shows an offline message with retry when the server cannot be reached", async () => {
    checkHandler = () => {
      throw new TypeError("Failed to fetch");
    };
    const user = userEvent.setup();
    await goToResults(user);
    // The page retries once (~1 s) before declaring the connection lost.
    expect(
      await screen.findByRole("heading", { name: "No connection" }, { timeout: 4000 }),
    ).toBeInTheDocument();
    checkHandler = () => checkResponse();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("1 thing needs attention"));
  });
});

describe("glossary", () => {
  it("explains jargon on tap", async () => {
    checkHandler = () => checkResponse({
      findings: [finding({ simple: "Together they can cause serotonin syndrome." })],
    });
    const user = userEvent.setup();
    renderApp();
    await addByPicking(user, "dol", /Dolo 650/);
    await user.click(screen.getByRole("button", { name: "Check safety" }));
    await user.click(await screen.findByRole("button", { name: "serotonin syndrome" }));
    expect(screen.getByRole("note")).toHaveTextContent(/too much serotonin/);
  });
});
