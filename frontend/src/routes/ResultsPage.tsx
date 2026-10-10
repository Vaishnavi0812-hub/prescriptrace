import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { FindingCard, type Detail } from "../components/FindingCard";
import { RecallSection } from "../components/RecallSection";
import { Icon } from "../components/Severity";
import { Skeleton } from "../components/Skeleton";
import { ApiError, runCheck, type CheckRequestItem, type CheckResponse, type Finding } from "../lib/api";
import { useMedications } from "../lib/medications";
import { runOfflineCheck } from "../lib/offline/check";
import { isNetworkError, loadKnowledge, useOfflineInfo } from "../lib/offline/store";

const DETAIL_KEY = "prescriptrace.detail"; // a per-device display preference, not patient data

function useDetail(): [Detail, (d: Detail) => void] {
  const [detail, setDetail] = useState<Detail>(() => {
    try {
      return localStorage.getItem(DETAIL_KEY) === "professional" ? "professional" : "simple";
    } catch {
      return "simple";
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(DETAIL_KEY, detail);
    } catch {
      // ignore: preference simply isn't remembered
    }
  }, [detail]);
  return [detail, setDetail];
}

/** A result computed on this phone: say plainly what was not checked. */
function OfflineBanner({ offline }: { offline: NonNullable<CheckResponse["offline"]> }) {
  const { t } = useTranslation();
  return (
    <section className="space-y-2 rounded-xl border-2 border-sev-moderate bg-sev-moderate/15 p-4" aria-labelledby="offline-result-h">
      <h2 id="offline-result-h" className="flex items-center gap-2 text-lg font-bold">
        <Icon name="alert" className="h-5 w-5 text-sev-moderate-ink" />
        {t("offline.resultTitle")}
      </h2>
      <p>{t("offline.resultBody", { date: new Date(offline.generated_at).toLocaleDateString() })}</p>
      {offline.context_ignored && <p className="font-semibold">{t("offline.contextIgnored")}</p>}
      <p className="text-sm font-medium">{t("offline.notChecked")}</p>
      <ul className="list-disc pl-5 text-sm">
        {(["recalls", "notes", "context", "minor"] as const).map((k) => (
          <li key={k}>{t(`offline.notCheckedItems.${k}`)}</li>
        ))}
      </ul>
      <p className="text-sm">{t("offline.recheck")}</p>
    </section>
  );
}

const isDuplicate = (f: Finding) => f.type === "duplicate_ingredient" || f.type === "duplicate_class";

export default function ResultsPage() {
  const { t } = useTranslation();
  const { meds, context, ready } = useMedications();
  const [detail, setDetail] = useDetail();
  const offlineInfo = useOfflineInfo();

  const items: CheckRequestItem[] = meds
    .filter((m) => m.picked)
    .map((m) => ({
      id: m.id,
      text: m.text,
      selection: { ref: m.picked!.ref, label: m.picked!.label, ingredients: m.picked!.ingredients },
      ...(m.batch.trim() ? { batch: m.batch.trim() } : {}),
    }));

  const { data, error, isPending, refetch, isFetching } = useQuery({
    queryKey: ["check", items, context],
    queryFn: async ({ signal }) => {
      try {
        return await runCheck(items, context, signal);
      } catch (e) {
        // No connection: fall back to the offline pack, if one is saved (a partial check).
        const kb = isNetworkError(e) ? await loadKnowledge() : null;
        if (kb) return runOfflineCheck(items, context, kb);
        throw e;
      }
    },
    enabled: ready,
    retry: 1,
    // Run even when the browser reports no network: the offline pack can answer.
    networkMode: "always",
  });

  if (!ready) {
    return (
      <section className="space-y-4 py-6 text-center">
        <p>{t("results.notReady")}</p>
        <Link to="/" className="inline-flex min-h-11 items-center font-semibold text-primary underline">
          {t("results.back")}
        </Link>
      </section>
    );
  }

  if (isPending) {
    return (
      <section className="space-y-4 py-4" aria-busy="true" aria-live="polite">
        <p className="sr-only">{t("results.loading")}</p>
        <div className="h-10 w-2/3 animate-pulse rounded bg-sand" />
        <Skeleton lines={4} />
        <Skeleton lines={3} />
        <Skeleton lines={2} />
      </section>
    );
  }

  if (error || !data) {
    const offline = !(error instanceof ApiError);
    return (
      <section className="space-y-4 py-6" role="alert">
        <h1 className="text-xl font-bold">{offline ? t("results.offlineTitle") : t("results.errorTitle")}</h1>
        <p>{offline ? t("results.offlineBody") : (error as ApiError).message}</p>
        {offline && !offlineInfo && (
          <p className="text-sm">
            {t("offline.setUpHint")}{" "}
            <Link to="/about" className="inline-flex min-h-11 items-center font-medium text-primary underline">
              {t("offline.setUpLink")}
            </Link>
          </p>
        )}
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="min-h-12 rounded-xl bg-primary px-5 font-semibold text-white disabled:opacity-60"
          >
            {t("common.retry")}
          </button>
          <Link to="/" className="inline-flex min-h-12 items-center px-2 font-semibold text-primary underline">
            {t("results.back")}
          </Link>
        </div>
      </section>
    );
  }

  const nonDup = data.findings.filter((f) => !isDuplicate(f));
  const attention = nonDup.filter((f) => f.severity === "contraindicated" || f.severity === "major");
  const worth = nonDup.filter((f) => f.severity === "moderate");
  const other = nonDup.filter((f) => f.severity === "minor" || f.severity === "unknown");
  const duplicates = data.findings.filter(isDuplicate);
  const s = data.summary;
  const nothingFound = data.findings.length === 0 && data.recalls.flags.length === 0;

  return (
    <article className="space-y-6 py-4" aria-live="polite">
      {/* (1) one plain-language headline */}
      <header className="space-y-2">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          {s.needs_attention > 0 ? (
            <Icon name="warning" className="h-7 w-7 text-sev-major-ink" />
          ) : (
            <Icon name="check" className="h-7 w-7 text-primary" />
          )}
          {s.headline}
        </h1>
        <p className="text-sm text-muted">
          {t("results.checked", { count: s.checked_medicines })}
          {s.worth_checking > 0 && <> · {t("results.worthCount", { count: s.worth_checking })}</>}
        </p>
        {/* On paper: when, and which medicines (names only; nothing about the patient). */}
        <div className="hidden text-sm print:block">
          <p>{t("print.printed", { date: new Date().toLocaleString() })}</p>
          <p className="font-semibold">{t("print.medicines")}</p>
          <ul className="list-disc pl-5">
            {data.medicines.map((m) => (
              <li key={m.id}>
                {m.text} ({m.ingredients.map((i) => i.name).join(", ")})
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden" role="group" aria-label={t("results.detailLabel")}>
          {(["simple", "professional"] as const).map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={detail === d}
              onClick={() => setDetail(d)}
              className={`min-h-11 rounded-lg border px-3 text-sm font-medium ${
                detail === d ? "border-primary bg-primary text-white" : "border-border-strong bg-surface"
              }`}
            >
              {t(`results.detail.${d}`)}
            </button>
          ))}
          <button
            type="button"
            onClick={() => window.print()}
            className="ml-auto min-h-11 rounded-lg border border-border-strong bg-surface px-3 text-sm font-medium"
          >
            {t("print.button")}
          </button>
        </div>
      </header>

      {data.offline && <OfflineBanner offline={data.offline} />}

      {/* (2) highest-severity items first */}
      {attention.length > 0 && (
        <section aria-labelledby="attention-h" className="space-y-3">
          <h2 id="attention-h" className="text-xl font-bold">{t("results.attention")}</h2>
          <ul className="space-y-3">
            {attention.map((f) => <FindingCard key={f.id} finding={f} detail={detail} />)}
          </ul>
        </section>
      )}

      {/* (3) recall and alert flags + checklist */}
      <RecallSection recalls={data.recalls} notChecked={Boolean(data.offline)} />

      {/* (4) duplicate therapy */}
      {duplicates.length > 0 && (
        <section aria-labelledby="dup-h" className="space-y-3">
          <h2 id="dup-h" className="text-xl font-bold">{t("results.duplicates")}</h2>
          <ul className="space-y-3">
            {duplicates.map((f) => <FindingCard key={f.id} finding={f} detail={detail} />)}
          </ul>
        </section>
      )}

      {worth.length > 0 && (
        <section aria-labelledby="worth-h" className="space-y-3">
          <h2 id="worth-h" className="text-xl font-bold">{t("results.worth")}</h2>
          <ul className="space-y-3">
            {worth.map((f) => <FindingCard key={f.id} finding={f} detail={detail} />)}
          </ul>
        </section>
      )}

      {data.notes.length > 0 && (
        <section aria-labelledby="notes-h" className="space-y-3">
          <h2 id="notes-h" className="text-xl font-bold">{t("results.notes")}</h2>
          <p className="text-sm text-muted">{t("results.notesHelp")}</p>
          <ul className="space-y-3">
            {data.notes.map((n, i) => (
              <li key={`${n.medicine}-${n.context}-${i}`}>
                {/* Collapsed: label quotes are long; one line each until tapped. */}
                <details className="rounded-xl border border-sand bg-surface">
                  <summary className="flex min-h-12 cursor-pointer items-center px-4 font-semibold">
                    {n.medicine} · {t(`contextName.${n.context}`)}
                  </summary>
                  <div className="border-t border-sand px-4 py-3">
                    <blockquote className="border-l-2 border-sand pl-2 text-sm">{n.text}</blockquote>
                    {n.evidence.url && (
                      <a href={n.evidence.url} target="_blank" rel="noreferrer noopener"
                         className="inline-flex min-h-11 items-center text-sm text-primary underline">
                        {t("results.readLabel")}
                      </a>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </section>
      )}

      {other.length > 0 && (
        <details className="rounded-xl border border-sand bg-surface">
          <summary className="flex min-h-12 cursor-pointer items-center px-4 font-medium">
            {t("results.other", { count: other.length })}
          </summary>
          <ul className="space-y-3 border-t border-sand p-3">
            {other.map((f) => <FindingCard key={f.id} finding={f} detail={detail} />)}
          </ul>
        </details>
      )}

      {/* (5) "no known issues" — carefully worded */}
      {(nothingFound || data.no_known_issue_pairs.length > 0) && (
        <section className="rounded-xl border border-sand bg-surface p-4">
          {nothingFound && (
            <p className="flex items-center gap-2 font-semibold text-primary">
              <Icon name="check" className="h-5 w-5" />
              {t("results.noKnown")}
            </p>
          )}
          {data.no_known_issue_pairs.length > 0 && (
            <details>
              <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium">
                {t("results.quietPairs", { count: data.no_known_issue_pairs.length })}
              </summary>
              <ul className="list-disc pl-5 text-sm">
                {data.no_known_issue_pairs.map(([a, b]) => <li key={`${a}|${b}`}>{a} + {b}</li>)}
              </ul>
            </details>
          )}
          <p className="mt-2 text-sm text-muted">{data.absence_note}</p>
        </section>
      )}

      {/* (6) sources */}
      <details className="rounded-xl border border-sand bg-surface">
        <summary className="flex min-h-12 cursor-pointer items-center px-4 font-medium">
          {t("results.sources")}
        </summary>
        <ul className="space-y-1 border-t border-sand p-4 text-sm">
          {data.data_versions.map((d) => (
            <li key={d.code}>
              <span className="font-medium">{d.name}</span>
              {d.version && <span className="text-muted"> · {d.version}</span>}
              <span className="text-muted"> · {d.licence}</span>
            </li>
          ))}
        </ul>
      </details>

      <p className="text-sm text-muted">{data.disclaimer}</p>
      <Link to="/" className="inline-flex min-h-12 items-center font-semibold text-primary underline print:hidden">
        {t("results.edit")}
      </Link>
    </article>
  );
}
