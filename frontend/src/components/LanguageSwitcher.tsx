import { useId } from "react";
import { useTranslation } from "react-i18next";

import { LANGUAGES, setLanguage, type LanguageCode } from "../i18n";

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  const id = useId();
  return (
    <div className="flex items-center gap-2 print:hidden">
      <label htmlFor={id} className="sr-only">
        {t("language.label")}
      </label>
      <select
        id={id}
        value={i18n.language}
        onChange={(e) => setLanguage(e.target.value as LanguageCode)}
        className="min-h-11 rounded-lg border border-border-strong bg-surface px-2 text-sm"
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code} lang={l.code}>
            {l.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Shown while an unreviewed machine translation is in use. */
export function TranslationNotice() {
  const { t, i18n } = useTranslation();
  const lang = LANGUAGES.find((l) => l.code === i18n.language);
  if (!lang || lang.reviewed) return null;
  return <p className="rounded-lg bg-sev-moderate/15 p-2 text-sm print:hidden">{t("language.machineTranslated")}</p>;
}
