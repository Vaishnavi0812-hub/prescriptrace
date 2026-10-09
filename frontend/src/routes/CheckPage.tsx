import { useId } from "react";
import { useTranslation } from "react-i18next";

/** Stage 1 shell of the home screen. Search and scan are wired up in Stages 7 and 8. */
export default function CheckPage() {
  const { t } = useTranslation();
  const inputId = useId();
  const hintId = useId();

  return (
    <section className="space-y-4 py-4">
      <label htmlFor={inputId} className="block text-lg font-semibold">
        {t("check.addMedicine")}
      </label>
      <input
        id={inputId}
        type="search"
        aria-describedby={hintId}
        placeholder={t("check.addMedicine")}
        disabled
        className="min-h-14 w-full rounded-xl border-2 border-sand bg-surface px-4 text-lg placeholder:text-muted"
      />
      <p id={hintId} className="text-sm text-muted">
        {t("check.addMedicineHint")} · {t("check.comingSoon")}
      </p>
      <button
        type="button"
        disabled
        className="min-h-12 w-full rounded-xl border-2 border-primary px-4 font-semibold text-primary disabled:opacity-60"
      >
        {t("check.scan")}
      </button>
    </section>
  );
}
