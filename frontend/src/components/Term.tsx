import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * A word with a plain-language explanation ("no jargon without a tooltip"). A button, not a hover
 * tooltip, so it works with touch and screen readers.
 */
export function Term({ term, children }: { term: string; children: React.ReactNode }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="cursor-help underline decoration-dotted underline-offset-4"
      >
        {children}
      </button>
      {open && (
        <span
          id={id}
          role="note"
          className="mt-1 block rounded-lg border border-sand bg-surface p-2 text-sm text-espresso shadow-sm"
        >
          {t(`glossary.${term}`)}
        </span>
      )}
    </span>
  );
}

/** Wrap known jargon inside a sentence with Term buttons. */
export function WithTerms({ text }: { text: string }) {
  const { t } = useTranslation();
  const glossary = t("glossary", { returnObjects: true }) as Record<string, string>;
  const words = Object.keys(glossary);
  if (!words.length) return <>{text}</>;
  const pattern = new RegExp(`\\b(${words.map(escapeRegExp).join("|")})\\b`, "i");
  const parts: React.ReactNode[] = [];
  let rest = text;
  let key = 0;
  // Explain each term once per sentence: the first occurrence becomes a button.
  const seen = new Set<string>();
  for (let match = pattern.exec(rest); match; match = pattern.exec(rest)) {
    const word = match[0];
    const term = words.find((w) => w.toLowerCase() === word.toLowerCase()) ?? word;
    parts.push(rest.slice(0, match.index));
    parts.push(
      seen.has(term) ? (
        word
      ) : (
        <Term key={key++} term={term}>
          {word}
        </Term>
      ),
    );
    seen.add(term);
    rest = rest.slice(match.index + word.length);
  }
  parts.push(rest);
  return <>{parts}</>;
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
