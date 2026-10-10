import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function mockFetch(response: Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(() => response));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App shell", () => {
  it("lands on the check tool, not a marketing page", () => {
    mockFetch(new Promise(() => {}));
    renderAt("/");
    expect(screen.getByRole("combobox", { name: "Add medicine" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Scan prescription/ })).toBeInTheDocument();
  });

  it("always shows the decision-support disclaimer", () => {
    mockFetch(new Promise(() => {}));
    renderAt("/");
    expect(screen.getByText(/Decision support only/)).toBeInTheDocument();
  });

  it("shows connected status with dataset count when the API is healthy", async () => {
    mockFetch(
      Promise.resolve(
        new Response(JSON.stringify({ status: "ok", database: true, datasets_loaded: 3 })),
      ),
    );
    renderAt("/");
    expect(await screen.findByText("Connected · 3 datasets loaded")).toBeInTheDocument();
  });

  it("shows an offline status when the API is unreachable", async () => {
    mockFetch(Promise.reject(new TypeError("Failed to fetch")));
    renderAt("/");
    // The health query retries once (~1 s backoff) before reporting offline.
    expect(
      await screen.findByText("Offline or server unreachable", {}, { timeout: 4000 }),
    ).toBeInTheDocument();
  });

  it("explains that it does not detect fake medicines", () => {
    mockFetch(new Promise(() => {}));
    renderAt("/about");
    expect(screen.getByText(/does not detect fake medicines/)).toBeInTheDocument();
  });
});
