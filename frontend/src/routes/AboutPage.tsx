import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Skeleton } from "../components/Skeleton";
import { fetchDatasets } from "../lib/api";

/** What the app does and does not do, and every dataset with version, date, licence, limits. */
export default function AboutPage() {
  const { t } = useTranslation();
  const { data, isPending, isError } = useQuery({
    queryKey: ["datasets"],
    queryFn: ({ signal }) => fetchDatasets(signal),
    staleTime: 10 * 60_000,
  });

  return (
    <section className="space-y-5 py-4">
      <h1 className="text-2xl font-bold">{t("about.title")}</h1>
      <p>{t("about.what")}</p>
      <p>{t("about.notWhat")}</p>
      <p>{t("about.privacy")}</p>
      <p className="rounded-xl bg-sev-moderate/15 p-3 text-sm">{t("about.disclaimer")}</p>

      <h2 className="text-xl font-bold">{t("about.dataTitle")}</h2>
      {isPending && <Skeleton lines={5} />}
      {isError && <p role="alert">{t("about.dataError")}</p>}
      {data && (
        <>
          <p className="rounded-xl border border-sand bg-surface p-3 text-sm">{data.non_commercial_notice}</p>
          <ul className="space-y-3">
            {data.datasets.map((d) => (
              <li key={d.code} className="rounded-xl border border-sand bg-surface p-4 text-sm">
                <p className="text-base font-semibold">
                  <a href={d.source_url} target="_blank" rel="noreferrer noopener" className="underline">
                    {d.name}
                  </a>
                </p>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <dt className="text-muted">{t("about.version")}</dt>
                  <dd>{d.version ?? "—"}</dd>
                  <dt className="text-muted">{t("about.updated")}</dt>
                  <dd>{d.downloaded_at ? new Date(d.downloaded_at).toLocaleDateString() : "—"}</dd>
                  <dt className="text-muted">{t("about.records")}</dt>
                  <dd>{d.record_count?.toLocaleString() ?? "—"}</dd>
                  <dt className="text-muted">{t("about.licence")}</dt>
                  <dd className="break-words">
                    {d.licence_url ? (
                      <a href={d.licence_url} target="_blank" rel="noreferrer noopener" className="underline">
                        {d.licence}
                      </a>
                    ) : (
                      d.licence
                    )}
                  </dd>
                  {d.region && (
                    <>
                      <dt className="text-muted">{t("about.region")}</dt>
                      <dd>{t(`region.${d.region}`, d.region)}</dd>
                    </>
                  )}
                </dl>
                {d.limitations && <p className="mt-2 text-muted">{d.limitations}</p>}
              </li>
            ))}
          </ul>
        </>
      )}
      <Link to="/" className="inline-flex min-h-11 items-center font-medium text-primary underline">
        {t("about.back")}
      </Link>
    </section>
  );
}
