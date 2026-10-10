import { useTranslation } from "react-i18next";

import type { CheckResponse, RecallFlag } from "../lib/api";
import { EvidenceDetails } from "./FindingCard";
import { SeverityBadge, severityStripe } from "./Severity";

function FlagCard({ flag }: { flag: RecallFlag }) {
  const { t } = useTranslation();
  return (
    <li className={`rounded-xl border border-sand border-l-8 bg-surface p-4 ${severityStripe(flag.level)}`}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge level={flag.level} />
        <span className="text-sm text-muted">{t(`recalls.match.${flag.match}`)}</span>
      </div>
      <h3 className="mt-2 text-lg font-semibold">{flag.title}</h3>
      <p className="mt-2">{flag.simple}</p>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">{t("recalls.product")}</dt>
        <dd className="break-words">{flag.product_description}</dd>
        {flag.lot_info && (
          <>
            <dt className="text-muted">{t("recalls.batch")}</dt>
            <dd className="break-words">{flag.lot_info}</dd>
          </>
        )}
        {flag.reason && (
          <>
            <dt className="text-muted">{t("recalls.reason")}</dt>
            <dd className="break-words">{flag.reason}</dd>
          </>
        )}
        {flag.firm && (
          <>
            <dt className="text-muted">{t("recalls.firm")}</dt>
            <dd className="break-words">{flag.firm}</dd>
          </>
        )}
        {flag.report_date && (
          <>
            <dt className="text-muted">{t("recalls.date")}</dt>
            <dd>{flag.report_date}</dd>
          </>
        )}
      </dl>
      <p className="mt-2">
        <span className="font-semibold">{t("results.whatToConsider")} </span>
        {flag.consider}
      </p>
      <EvidenceDetails evidence={[flag.evidence]} />
    </li>
  );
}

/** One card per medicine (its most serious alert; flags arrive sorted), the rest collapsed. */
function groupByMedicine(flags: RecallFlag[]): [RecallFlag, ...RecallFlag[]][] {
  const groups = new Map<string, [RecallFlag, ...RecallFlag[]]>();
  for (const flag of flags) {
    const group = groups.get(flag.medicine_id);
    if (group) group.push(flag);
    else groups.set(flag.medicine_id, [flag]);
  }
  return [...groups.values()];
}

export function RecallSection({
  recalls,
  notChecked = false,
}: {
  recalls: CheckResponse["recalls"];
  notChecked?: boolean; // offline: alert lists were not consulted, so never say "none found"
}) {
  const { t } = useTranslation();
  const { flags, ingredient_summaries: summaries, checklist, coverage_notes: coverage } = recalls;
  return (
    <section aria-labelledby="recalls-h" className="space-y-3">
      <h2 id="recalls-h" className="text-xl font-bold">
        {t("recalls.title")}
      </h2>
      <p className="text-sm text-muted">{t("recalls.notDetection")}</p>
      {flags.length > 0 ? (
        <ul className="space-y-3">
          {groupByMedicine(flags).map(([first, ...more]) => (
            <li key={first.medicine_id} className="space-y-2">
              <ul>
                <FlagCard flag={first} />
              </ul>
              {more.length > 0 && (
                <details className="rounded-xl border border-sand bg-surface">
                  <summary className="flex min-h-12 cursor-pointer items-center px-4 text-sm font-medium">
                    {t("recalls.more", { count: more.length, medicine: first.medicine_label })}
                  </summary>
                  <ul className="space-y-3 border-t border-sand p-3">
                    {more.map((f) => (
                      <FlagCard key={`${f.evidence.record_id}-${f.match}`} flag={f} />
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-sand bg-surface p-4">
          {notChecked ? t("offline.recallsNotChecked") : t("recalls.none")}
        </p>
      )}

      {summaries.length > 0 && (
        <details className="rounded-xl border border-sand bg-surface">
          <summary className="flex min-h-12 cursor-pointer items-center px-4 font-medium">
            {t("recalls.sameIngredient", { count: summaries.reduce<number>((n, s) => n + s.total, 0) })}
          </summary>
          <div className="space-y-3 border-t border-sand p-4 text-sm">
            <p className="text-muted">{t("recalls.sameIngredientHelp")}</p>
            {summaries.map((s) => (
              <div key={`${s.medicine_id}-${s.region}`}>
                <p className="font-semibold">
                  {t("recalls.summaryLine", { medicine: s.medicine_label, count: s.total,
                                              region: t(`region.${s.region}`, s.region) })}
                </p>
                <ul className="mt-1 list-disc pl-5">
                  {s.recent.map((f) => (
                    <li key={f.evidence.record_id}>
                      {f.product_description}
                      {f.report_date && <span className="text-muted"> · {f.report_date}</span>}
                      {f.evidence.url && (
                        <>
                          {" "}
                          <a href={f.evidence.url} target="_blank" rel="noreferrer noopener"
                             className="inline-flex min-h-11 items-center text-primary underline">
                            {t("results.openSource")}
                          </a>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </details>
      )}

      <details className="rounded-xl border border-sand bg-surface" open={flags.some((f) => f.level !== "info")}>
        <summary className="flex min-h-12 cursor-pointer items-center px-4 font-semibold">
          {t("checklist.title")}
        </summary>
        <ol className="list-decimal space-y-3 border-t border-sand py-4 pr-4 pl-9">
          {checklist.map((item) => (
            <li key={item.id}>
              <p className="font-medium">{item.check}</p>
              <p className="text-sm text-muted">{item.why}</p>
              <p className="text-xs text-muted">
                {t("checklist.source")}:{" "}
                {item.source_url ? (
                  <a href={item.source_url} target="_blank" rel="noreferrer noopener" className="inline-flex min-h-11 items-center underline">
                    {item.source}
                  </a>
                ) : (
                  item.source
                )}
              </p>
            </li>
          ))}
        </ol>
      </details>
      {coverage.length > 0 && (
        <p className="text-xs text-muted">
          {t("recalls.coverage")}: {coverage.join(" · ")}
        </p>
      )}
    </section>
  );
}
