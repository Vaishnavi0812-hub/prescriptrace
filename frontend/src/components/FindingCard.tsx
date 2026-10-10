import { useTranslation } from "react-i18next";

import type { Evidence, Finding } from "../lib/api";
import { SeverityBadge, severityStripe } from "./Severity";
import { WithTerms } from "./Term";

export type Detail = "simple" | "professional";

export function FindingCard({ finding, detail }: { finding: Finding; detail: Detail }) {
  const { t } = useTranslation();
  const text = detail === "simple" ? finding.simple : finding.professional;
  return (
    <li
      className={`rounded-xl border border-sand border-l-8 bg-surface p-4 ${severityStripe(finding.severity)}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge level={finding.severity} />
        {finding.provenance === "label_text" && (
          <span className="text-xs text-muted">{t("results.fromLabel")}</span>
        )}
      </div>
      <h3 className="mt-2 text-lg font-semibold">{finding.title}</h3>
      <p className="mt-1 text-sm text-muted">{finding.drug_labels.join(" · ")}</p>

      <div className="mt-3 space-y-2">
        <p>
          <span className="font-semibold">{t("results.whatItMeans")} </span>
          <WithTerms text={text} />
        </p>
        <p>
          <span className="font-semibold">{t("results.whatToConsider")} </span>
          {finding.consider}
        </p>
        {finding.related.map((note) => (
          <p key={note} className="rounded-lg bg-cream p-2 text-sm">
            <span className="font-semibold">{t("results.alsoApplies")} </span>
            <WithTerms text={note} />
          </p>
        ))}
      </div>
      <EvidenceDetails evidence={finding.evidence} confidence={finding.confidence} />
    </li>
  );
}

export function EvidenceDetails({
  evidence,
  confidence,
}: {
  evidence: Evidence[];
  confidence?: string;
}) {
  const { t } = useTranslation();
  return (
    <details className="mt-3">
      <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-primary underline">
        {t("results.evidence", { count: evidence.length })}
      </summary>
      {confidence && (
        <p className="text-sm text-muted">{t(`results.confidence.${confidence}`)}</p>
      )}
      <ul className="mt-2 space-y-2 text-sm">
        {evidence.map((e, i) => (
          <li key={`${e.dataset}-${e.record_id}-${i}`} className="rounded-lg border border-sand p-2">
            <p className="font-medium">
              {e.dataset_name}
              {e.dataset_version && <span className="font-normal text-muted"> · {e.dataset_version}</span>}
            </p>
            <p className="break-words text-muted">
              {t("results.record")}: {e.record_id}
            </p>
            {e.quote && <blockquote className="mt-1 border-l-2 border-sand pl-2 italic">{e.quote}</blockquote>}
            {e.url && (
              <a
                href={e.url}
                target="_blank"
                rel="noreferrer noopener"
                className="mt-1 inline-flex min-h-11 items-center text-primary underline"
              >
                {t("results.openSource")}
              </a>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}
