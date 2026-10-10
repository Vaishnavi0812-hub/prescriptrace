/**
 * Printing (or "Save as PDF" in the print dialog) should show everything, including collapsed
 * sections. Open every <details> before printing and restore the user's view afterwards.
 */
export function installPrintSupport(): () => void {
  let opened: HTMLDetailsElement[] = [];
  const before = () => {
    opened = [...document.querySelectorAll<HTMLDetailsElement>("details:not([open])")];
    opened.forEach((d) => (d.open = true));
  };
  const after = () => {
    opened.forEach((d) => (d.open = false));
    opened = [];
  };
  window.addEventListener("beforeprint", before);
  window.addEventListener("afterprint", after);
  return () => {
    window.removeEventListener("beforeprint", before);
    window.removeEventListener("afterprint", after);
  };
}
