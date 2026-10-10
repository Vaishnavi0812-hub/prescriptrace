import { afterEach, expect, it } from "vitest";

import { installPrintSupport } from "./print";

afterEach(() => {
  document.body.innerHTML = "";
});

it("expands every collapsed section for printing and restores the view afterwards", () => {
  document.body.innerHTML = `
    <details id="a"><summary>A</summary>text</details>
    <details id="b" open><summary>B</summary>text</details>`;
  const uninstall = installPrintSupport();
  const a = document.getElementById("a") as HTMLDetailsElement;
  const b = document.getElementById("b") as HTMLDetailsElement;

  window.dispatchEvent(new Event("beforeprint"));
  expect([a.open, b.open]).toEqual([true, true]);
  window.dispatchEvent(new Event("afterprint"));
  expect([a.open, b.open]).toEqual([false, true]); // the one the user had open stays open

  uninstall();
});
