import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, Outlet } from "react-router-dom";

import { fetchHealth } from "../lib/api";

function DataStatus() {
  const { t } = useTranslation();
  const { data, isPending, isError } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => fetchHealth(signal),
    retry: 1,
    refetchInterval: 60_000,
  });

  let label = t("footer.apiChecking");
  let dot = "bg-sand";
  if (isError || data?.database === false) {
    label = t("footer.apiDown");
    dot = "bg-sev-major";
  } else if (!isPending) {
    label = t("footer.apiOk", { count: data.datasets_loaded });
    dot = "bg-primary";
  }

  return (
    <p className="flex items-center gap-2 text-sm text-muted" role="status" aria-live="polite">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dot}`} aria-hidden="true" />
      <span>
        <span className="sr-only">{t("footer.dataStatus")}: </span>
        {label}
      </span>
    </p>
  );
}

export default function Layout() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col px-4">
      <header className="flex items-center justify-between py-4">
        <Link to="/" className="flex min-h-11 items-center text-xl font-bold text-primary">
          {t("app.name")}
        </Link>
        <span className="text-sm text-muted">{t("app.tagline")}</span>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
      <footer className="space-y-2 border-t border-sand py-4">
        <DataStatus />
        <p className="text-sm text-muted">{t("footer.disclaimer")}</p>
        <Link
          to="/about"
          className="inline-flex min-h-11 items-center text-sm font-medium text-primary underline"
        >
          {t("footer.about")}
        </Link>
      </footer>
    </div>
  );
}
