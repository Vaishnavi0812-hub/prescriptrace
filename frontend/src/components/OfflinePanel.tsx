import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  downloadPack,
  fetchPackMeta,
  offlineSupported,
  removePack,
  useOfflineInfo,
} from "../lib/offline/store";

const formatDate = (iso: string): string => new Date(iso).toLocaleDateString();
const megabytes = (bytes: number): string => (bytes / 1_000_000).toFixed(1);

/** Set up, update or remove the offline data on this device. Nothing downloads until asked. */
export function OfflinePanel() {
  const { t } = useTranslation();
  const info = useOfflineInfo();
  const meta = useQuery({
    queryKey: ["offline-pack-meta"],
    queryFn: ({ signal }) => fetchPackMeta(signal),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const download = useMutation({ mutationFn: downloadPack });
  const remove = useMutation({ mutationFn: removePack });
  const updateAvailable = Boolean(info && meta.data && meta.data.version !== info.version);

  if (!offlineSupported()) {
    return (
      <section aria-labelledby="offline-h" className="space-y-2">
        <h2 id="offline-h" className="text-xl font-bold">{t("offline.title")}</h2>
        <p>{t("offline.unsupported")}</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="offline-h" className="space-y-3 rounded-xl border border-sand bg-surface p-4">
      <h2 id="offline-h" className="text-xl font-bold">{t("offline.title")}</h2>
      <p className="text-sm">{t("offline.what")}</p>
      <p className="text-sm text-muted">{t("offline.limits")}</p>

      <p className="font-medium" role="status" aria-live="polite">
        {info
          ? t("offline.ready", { date: formatDate(info.generated_at) })
          : t("offline.notSetUp")}
        {updateAvailable && <> · {t("offline.updateAvailable")}</>}
      </p>

      <div className="flex flex-wrap gap-3">
        {(!info || updateAvailable) && (
          <button
            type="button"
            onClick={() => download.mutate()}
            disabled={download.isPending || meta.isError}
            className="min-h-12 rounded-xl bg-primary px-5 font-semibold text-white hover:bg-primary-hover disabled:opacity-60"
          >
            {download.isPending
              ? t("offline.downloading")
              : t(info ? "offline.update" : "offline.download", {
                  size: meta.data ? megabytes(meta.data.download_bytes) : "1.5",
                })}
          </button>
        )}
        {info && (
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="min-h-12 rounded-xl border border-border-strong px-5 font-medium"
          >
            {t("offline.remove")}
          </button>
        )}
      </div>
      {download.isError && (
        <p role="alert" className="text-sm text-sev-major-ink">
          {t("offline.failed")}
        </p>
      )}
      {!info && meta.isError && <p className="text-sm text-muted">{t("offline.needsConnection")}</p>}
    </section>
  );
}

/** Short status for the footer. */
export function OfflineStatus() {
  const { t } = useTranslation();
  const info = useOfflineInfo();
  if (!info) return null;
  return <p className="text-sm text-muted">{t("offline.footer", { date: formatDate(info.generated_at) })}</p>;
}
