import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import rawVectors from "../../backend/tests/vectors/offline_engine.json";
import App from "./App";
import { removePack } from "./lib/offline/store";

// The pack from the shared engine vectors: warfarin, ibuprofen ("Brufen"), etc.
const PACK = {
  ...(rawVectors as unknown as { pack: { version: string; generated_at: string } }).pack,
  disclaimer: "Decision support only.",
  absence_note: "Not proof of safety.",
  checklist: [{ id: "qr_code", check: "Scan the QR code", why: "Top 300 brands carry one.",
                source: "CDSCO", source_url: null }],
};

/** Minimal Cache Storage (jsdom has none). */
function fakeCaches() {
  const stores = new Map<string, Map<string, Response>>();
  const open = async (name: string) => {
    const store = stores.get(name) ?? new Map<string, Response>();
    stores.set(name, store);
    return { put: async (url: string, r: Response) => void store.set(url, r) };
  };
  return {
    open,
    match: async (url: string) => {
      for (const store of stores.values()) {
        const hit = store.get(url);
        if (hit) return hit.clone();
      }
      return undefined;
    },
    delete: async (name: string) => stores.delete(name),
  };
}

let online = true;
const json = (body: unknown) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

beforeEach(() => {
  online = true;
  sessionStorage.clear();
  vi.stubGlobal("caches", fakeCaches());
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (!online) throw new TypeError("Failed to fetch");
      if (url.includes("/offline-pack/meta")) {
        return json({ version: PACK.version, generated_at: PACK.generated_at, download_bytes: 1_400_000, raw_bytes: 8_000_000 });
      }
      if (url.includes("/offline-pack")) return json(PACK);
      if (url.includes("/health")) return json({ status: "ok", database: true, datasets_loaded: 9 });
      if (url.includes("/datasets")) return json({ datasets: [], non_commercial_notice: "Non-commercial." });
      return json({ hits: [], results: [] });
    }),
  );
});

afterEach(async () => {
  await removePack();
  vi.unstubAllGlobals();
  onlineManager.setOnline(true);
});

/** Like a phone losing signal: requests fail AND the browser reports itself offline (which
 * pauses React Query's default "online" network mode). */
function goOffline() {
  online = false;
  vi.stubGlobal("navigator", { ...navigator, onLine: false });
  onlineManager.setOnline(false);
}

function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function saveOfflineData(user: ReturnType<typeof userEvent.setup>) {
  const view = renderApp("/about");
  expect(screen.getByText("Not set up on this device.")).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "Save for offline use (1.4 MB)" }));
  expect(await screen.findByText(/Saved on this device/)).toBeInTheDocument();
  view.unmount();
}

describe("offline use", () => {
  it("downloads only when asked and can be removed", async () => {
    const user = userEvent.setup();
    renderApp("/about");
    await screen.findByRole("button", { name: /Save for offline use/ });
    expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).endsWith("/offline-pack"))).toBe(false);
    await user.click(screen.getByRole("button", { name: /Save for offline use/ }));
    await user.click(await screen.findByRole("button", { name: "Remove offline data" }));
    expect(await screen.findByText("Not set up on this device.")).toBeInTheDocument();
  });

  it("checks typed and picked medicines on the phone, and says what was not checked", async () => {
    const user = userEvent.setup();
    await saveOfflineData(user);
    goOffline();
    renderApp("/");
    const box = screen.getByRole("combobox", { name: "Add medicine" });
    await user.type(box, "warf");
    await user.click(await screen.findByRole("option", { name: /Warfarin/ }));
    await user.type(box, "Brufen 400 tab{Enter}"); // exact name match offline
    await waitFor(() => expect(screen.getByRole("button", { name: "Check safety" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Check safety" }));

    expect(await screen.findByRole("heading", { name: "Offline check: partial" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("1 thing needs attention");
    expect(screen.getByText("Warfarin + Ibuprofen")).toBeInTheDocument();
    expect(screen.getByText("Recall and quality alerts")).toBeInTheDocument();
    expect(screen.getByText(/Not checked: alert lists need the internet/)).toBeInTheDocument();
    expect(screen.queryByText("No recall or quality alert for these products in our data.")).toBeNull();
  });

  it("never guesses an unclear typed name offline", async () => {
    const user = userEvent.setup();
    await saveOfflineData(user);
    goOffline();
    renderApp("/");
    await user.type(screen.getByRole("combobox", { name: "Add medicine" }), "warf{Enter}");
    expect(await screen.findByText("Please confirm which medicine this is")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check safety" })).toBeDisabled();
  });
});
