import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { Icon } from "../components/Severity";
import { Skeleton } from "../components/Skeleton";
import { ApiError, scanPrescription, type Candidate, type ScannedLine } from "../lib/api";
import { shrinkForUpload } from "../lib/image";
import { useMedications } from "../lib/medications";

/**
 * Photograph a prescription. Every recognised line is shown next to the part of the photo it
 * came from; nothing is added to the list until the user taps Add (handwriting is often misread).
 */
export default function ScanPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const inputId = useId();
  const [preview, setPreview] = useState<string | null>(null);
  const scan = useMutation({
    mutationFn: async (file: File) => scanPrescription(await shrinkForUpload(file)),
  });

  const onFile = (file: File | undefined) => {
    if (!file) return;
    // The preview is a nicety; browsers without object URLs still scan.
    if (typeof URL.createObjectURL === "function") {
      if (preview) URL.revokeObjectURL(preview);
      setPreview(URL.createObjectURL(file));
    }
    scan.mutate(file);
  };

  const meds = scan.data?.lines.filter((l) => l.likely_medicine) ?? [];
  const others = scan.data?.lines.filter((l) => !l.likely_medicine) ?? [];

  return (
    <section className="space-y-5 py-4">
      <h1 className="text-2xl font-bold">{t("scan.title")}</h1>

      {!scan.isPending && (
        <div className="space-y-3">
          <label
            htmlFor={inputId}
            className="flex min-h-14 w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-primary px-4 text-lg font-semibold text-white hover:bg-primary-hover"
          >
            {scan.data ? t("scan.again") : t("scan.take")}
          </label>
          <input
            id={inputId}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            className="sr-only"
            onChange={(e) => onFile(e.target.files?.[0])}
          />
          {!scan.data && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              <li>{t("scan.tips.flat")}</li>
              <li>{t("scan.tips.light")}</li>
              <li>{t("scan.tips.frame")}</li>
            </ul>
          )}
          <p className="text-sm text-muted">{t("scan.privacy")}</p>
        </div>
      )}

      {scan.isPending && (
        <div className="space-y-3" aria-busy="true" aria-live="polite">
          <p className="font-medium">{t("scan.reading")}</p>
          {preview && <img src={preview} alt="" className="max-h-48 rounded-lg border border-sand object-contain" />}
          <Skeleton lines={2} />
          <Skeleton lines={2} />
        </div>
      )}

      {scan.isError && (
        <div role="alert" className="rounded-xl border border-sand bg-surface p-4">
          <p className="font-semibold">
            {scan.error instanceof ApiError ? t("scan.failed") : t("scan.offline")}
          </p>
          {scan.error instanceof ApiError && <p className="text-sm">{scan.error.message}</p>}
        </div>
      )}

      {scan.data && (
        <div className="space-y-4" aria-live="polite">
          {scan.data.sends_image_off_device && (
            <p className="rounded-lg bg-sev-moderate/15 p-3 text-sm">{t("scan.offDevice")}</p>
          )}
          {scan.data.warnings.map((w) => (
            <p key={w} className="flex gap-2 rounded-lg bg-sev-moderate/15 p-3 text-sm">
              <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-sev-moderate-ink" />
              {t(`scan.warnings.${w}`)}
            </p>
          ))}
          <p className="text-sm text-muted">{t("scan.checkEach")}</p>

          {meds.length > 0 && (
            <ul className="space-y-3" aria-label={t("scan.found")}>
              {meds.map((line, i) => (
                <ScannedLineCard key={`${i}-${line.text}`} line={line} />
              ))}
            </ul>
          )}

          {others.length > 0 && (
            <details className="rounded-xl border border-sand bg-surface">
              <summary className="flex min-h-12 cursor-pointer items-center px-4 font-medium">
                {t("scan.otherText", { count: others.length })}
              </summary>
              <ul className="space-y-2 border-t border-sand p-3">
                {others.map((line, i) => (
                  <OtherLine key={`${i}-${line.text}`} text={line.text} />
                ))}
              </ul>
            </details>
          )}

          <button
            type="button"
            onClick={() => navigate("/")}
            className="min-h-14 w-full rounded-xl bg-primary px-4 text-lg font-semibold text-white hover:bg-primary-hover"
          >
            {t("scan.done")}
          </button>
        </div>
      )}

      <Link to="/" className="inline-flex min-h-11 items-center font-medium text-primary underline">
        {t("results.back")}
      </Link>
    </section>
  );
}

function ScannedLineCard({ line }: { line: ScannedLine }) {
  const { t } = useTranslation();
  const { addCandidate, addTyped } = useMedications();
  const [text, setText] = useState(line.text);
  const [added, setAdded] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const editId = useId();
  const best = line.normalised?.best ?? null;
  const edited = text.trim() !== line.text;
  const choices = (line.normalised?.candidates ?? []).slice(0, 3);

  if (dismissed) return null;
  const add = (label: string, candidate?: Candidate) => {
    if (candidate) addCandidate(text.trim(), candidate);
    else addTyped(text.trim());
    setAdded(label);
  };

  return (
    <li className="rounded-xl border border-sand bg-surface p-3">
      {line.crop_png_b64 && (
        <img
          src={`data:image/png;base64,${line.crop_png_b64}`}
          alt={t("scan.cropAlt", { text: line.text })}
          className="mb-2 max-h-16 w-full rounded border border-sand bg-white object-contain object-left"
        />
      )}
      <label htmlFor={editId} className="text-xs text-muted">
        {t("scan.readAs")}
      </label>
      <input
        id={editId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={Boolean(added)}
        className="mt-1 min-h-11 w-full rounded-lg border border-border-strong px-3"
      />

      {added ? (
        <p className="mt-2 flex items-center gap-2 font-medium text-primary" role="status">
          <Icon name="check" /> {t("scan.added", { name: added })}
        </p>
      ) : (
        <div className="mt-2 space-y-2">
          {!edited && line.status === "resolved" && best && (
            <button
              type="button"
              onClick={() => add(best.label, best)}
              className="flex min-h-11 w-full flex-col items-start rounded-lg bg-primary px-3 py-2 text-left text-white hover:bg-primary-hover"
            >
              <span className="font-semibold">{t("scan.addMatch", { name: best.label })}</span>
              <span className="text-sm opacity-90">
                {t("check.contains", { names: best.ingredient_names.join(", ") })}
              </span>
            </button>
          )}
          {!edited && line.status !== "resolved" && choices.length > 0 && (
            <>
              <p className="text-sm font-medium text-sev-moderate-ink">
                {line.status === "confirm" ? t("check.pleaseConfirm") : t("scan.possibleMatches")}
              </p>
              {choices.map((c) => (
                <button
                  key={c.ref}
                  type="button"
                  onClick={() => add(c.label, c)}
                  className="flex min-h-11 w-full flex-col items-start rounded-lg border border-border-strong px-3 py-2 text-left hover:bg-cream"
                >
                  <span className="font-medium">{c.label}</span>
                  <span className="text-sm text-muted">
                    {t("check.contains", { names: c.ingredient_names.join(", ") })}
                  </span>
                </button>
              ))}
            </>
          )}
          {(edited || line.status === "unknown" || (line.status !== "resolved" && choices.length === 0)) && (
            <button
              type="button"
              onClick={() => add(text.trim())}
              disabled={text.trim().length < 2}
              className="min-h-11 w-full rounded-lg border border-primary px-3 font-medium text-primary disabled:opacity-50"
            >
              {t("scan.addTyped")}
            </button>
          )}
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="min-h-11 px-1 text-sm text-muted underline"
          >
            {t("scan.notAMedicine")}
          </button>
        </div>
      )}
    </li>
  );
}

function OtherLine({ text }: { text: string }) {
  const { t } = useTranslation();
  const { addTyped } = useMedications();
  const [added, setAdded] = useState(false);
  return (
    <li className="flex items-center justify-between gap-2 text-sm">
      <span className="break-words text-muted">{text}</span>
      {added ? (
        <span className="shrink-0 text-primary">{t("scan.addedShort")}</span>
      ) : (
        <button
          type="button"
          onClick={() => {
            addTyped(text);
            setAdded(true);
          }}
          className="min-h-11 shrink-0 rounded-lg border border-border-strong px-3"
        >
          {t("scan.addAnyway")}
        </button>
      )}
    </li>
  );
}
