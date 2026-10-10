import { useTranslation } from "react-i18next";

import type { PatientContext } from "../lib/api";
import { useMedications } from "../lib/medications";

/** Optional patient details. Never names or IDs. */
export function PatientContextForm() {
  const { t } = useTranslation();
  const { context, setContext } = useMedications();
  const set = (patch: Partial<PatientContext>) => setContext({ ...context, ...patch });
  const active = [context.age_group, context.pregnant, context.renal, context.hepatic].filter(Boolean)
    .length;

  return (
    <details className="rounded-xl border border-sand bg-surface" open={active > 0}>
      <summary className="flex min-h-12 cursor-pointer items-center px-4 font-semibold">
        {t("context.title")}
        {active > 0 && (
          <span className="ml-2 rounded-full bg-primary/10 px-2 text-sm text-primary">
            {t("context.selected", { count: active })}
          </span>
        )}
      </summary>
      <div className="space-y-4 border-t border-sand px-4 py-4">
        <p className="text-sm text-muted">{t("context.privacy")}</p>
        <fieldset>
          <legend className="mb-2 font-medium">{t("context.age")}</legend>
          <div className="flex flex-wrap gap-2">
            {([null, "child", "adult", "older"] as const).map((age) => (
              <label
                key={age ?? "any"}
                className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 ${
                  context.age_group === age ? "border-primary bg-primary/10" : "border-border-strong"
                }`}
              >
                <input
                  type="radio"
                  name="age_group"
                  checked={context.age_group === age}
                  onChange={() => set({ age_group: age })}
                  className="h-4 w-4 accent-primary"
                />
                {t(`context.ages.${age ?? "unknown"}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 font-medium">{t("context.conditions")}</legend>
          <div className="space-y-2">
            {(["pregnant", "renal", "hepatic"] as const).map((key) => (
              <label key={key} className="flex min-h-11 cursor-pointer items-center gap-3">
                <input
                  type="checkbox"
                  checked={context[key]}
                  onChange={(e) => set({ [key]: e.target.checked })}
                  className="h-5 w-5 accent-primary"
                />
                {t(`context.${key}`)}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </details>
  );
}
