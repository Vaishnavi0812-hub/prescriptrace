import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Med } from "../lib/medications";
import { useMedications } from "../lib/medications";
import { Icon } from "./Severity";

/** One medicine in the list: what it contains, strength, optional batch, or "please confirm". */
export function MedicineCard({ med }: { med: Med }) {
  const { t } = useTranslation();
  const { remove, choose, retry, setBatch } = useMedications();
  const [showBatch, setShowBatch] = useState(Boolean(med.batch));
  const batchId = useId();

  return (
    <li className="rounded-xl border border-sand bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-lg font-semibold break-words">{med.text}</p>
          {med.status === "resolved" && med.picked && (
            <p className="text-sm text-muted">
              {med.picked.label !== med.text && <>{med.picked.label} · </>}
              {t("check.contains", { names: med.picked.ingredientNames.join(", ") })}
              {med.strength && <> · {med.strength}</>}
            </p>
          )}
          {med.status === "pending" && (
            <p className="text-sm text-muted" role="status">
              {t("check.recognising")}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => remove(med.id)}
          aria-label={t("check.remove", { name: med.text })}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-cream hover:text-espresso"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {(med.status === "confirm" || med.status === "unknown") && (
        <div className="mt-3 rounded-lg bg-sev-moderate/15 p-3">
          <p className="flex items-center gap-2 font-semibold text-sev-moderate-ink">
            <Icon name="question" />
            {med.status === "confirm" ? t("check.pleaseConfirm") : t("check.notRecognised")}
          </p>
          {med.candidates.length > 0 ? (
            <ul className="mt-2 space-y-2" aria-label={t("check.choices")}>
              {med.candidates.slice(0, 4).map((c) => (
                <li key={c.ref}>
                  <button
                    type="button"
                    onClick={() => choose(med.id, c)}
                    className="flex min-h-11 w-full flex-col items-start rounded-lg border border-border-strong bg-surface px-3 py-2 text-left hover:bg-cream"
                  >
                    <span className="font-medium">{c.label}</span>
                    <span className="text-sm text-muted">
                      {t("check.contains", { names: c.ingredient_names.join(", ") })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm">{t("check.tryGeneric")}</p>
          )}
          <p className="mt-2 text-sm text-muted">{t("check.noneOfThese")}</p>
        </div>
      )}

      {med.status === "error" && (
        <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-sand/40 p-3">
          <p className="text-sm">{t("check.recogniseFailed")}</p>
          <button
            type="button"
            onClick={() => retry(med.id)}
            className="min-h-11 rounded-lg border border-border-strong px-3 font-medium"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {med.status === "resolved" &&
        (showBatch ? (
          <div className="mt-3">
            <label htmlFor={batchId} className="block text-sm font-medium">
              {t("check.batch")}
            </label>
            <input
              id={batchId}
              value={med.batch}
              maxLength={40}
              inputMode="text"
              autoCapitalize="characters"
              onChange={(e) => setBatch(med.id, e.target.value.replace(/[^A-Za-z0-9 ./_-]/g, ""))}
              placeholder={t("check.batchPlaceholder")}
              className="mt-1 min-h-11 w-full rounded-lg border border-border-strong px-3"
            />
            <p className="mt-1 text-xs text-muted">{t("check.batchHelp")}</p>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowBatch(true)}
            className="mt-2 min-h-11 text-sm font-medium text-primary underline"
          >
            {t("check.addBatch")}
          </button>
        ))}
    </li>
  );
}
