import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { DrugSearch } from "../components/DrugSearch";
import { MedicineCard } from "../components/MedicineCard";
import { PatientContextForm } from "../components/PatientContextForm";
import { useMedications } from "../lib/medications";

/** Home screen = the tool: add medicines, optional patient details, check. */
export default function CheckPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { meds, addPicked, addTyped, ready, clear } = useMedications();
  const waiting = meds.filter((m) => m.status !== "resolved").length;

  return (
    <section className="space-y-5 py-4">
      <DrugSearch onPick={addPicked} onType={addTyped} />

      <Link
        to="/scan"
        className="flex min-h-12 w-full items-center justify-center gap-2 rounded-xl border-2 border-primary px-4 font-semibold text-primary hover:bg-primary/5"
      >
        {t("check.scan")}
      </Link>

      {meds.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border-strong p-6 text-center text-muted">
          {t("check.empty")}
        </p>
      ) : (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">{t("check.listTitle", { count: meds.length })}</h2>
            <button type="button" onClick={clear} className="min-h-11 px-2 text-sm text-muted underline">
              {t("check.clear")}
            </button>
          </div>
          <ul className="space-y-3">
            {meds.map((m) => (
              <MedicineCard key={m.id} med={m} />
            ))}
          </ul>
        </div>
      )}

      <PatientContextForm />

      <div className="sticky bottom-0 -mx-4 border-t border-sand bg-cream/95 px-4 py-3 backdrop-blur">
        <button
          type="button"
          disabled={!ready}
          onClick={() => navigate("/results")}
          className="min-h-14 w-full rounded-xl bg-primary px-4 text-lg font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          {t("check.run")}
        </button>
        {meds.length > 0 && waiting > 0 && (
          <p className="mt-1 text-center text-sm text-muted" role="status">
            {t("check.waiting", { count: waiting })}
          </p>
        )}
      </div>
    </section>
  );
}
