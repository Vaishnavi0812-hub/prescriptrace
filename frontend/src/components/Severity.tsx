import { useTranslation } from "react-i18next";

import type { Severity } from "../lib/api";

/** Severity is always icon + text label + colour, never colour alone. */
export type Level = Severity | "serious" | "warning" | "info" | "none";

const STYLE: Record<Level, { ink: string; tint: string; stripe: string; icon: IconName }> = {
  contraindicated: {
    ink: "text-sev-contraindicated",
    tint: "bg-sev-contraindicated/10",
    stripe: "border-l-sev-contraindicated",
    icon: "stop",
  },
  serious: {
    ink: "text-sev-contraindicated",
    tint: "bg-sev-contraindicated/10",
    stripe: "border-l-sev-contraindicated",
    icon: "stop",
  },
  major: {
    ink: "text-sev-major-ink",
    tint: "bg-sev-major/10",
    stripe: "border-l-sev-major",
    icon: "warning",
  },
  warning: {
    ink: "text-sev-major-ink",
    tint: "bg-sev-major/10",
    stripe: "border-l-sev-major",
    icon: "warning",
  },
  moderate: {
    ink: "text-sev-moderate-ink",
    tint: "bg-sev-moderate/15",
    stripe: "border-l-sev-moderate",
    icon: "alert",
  },
  minor: {
    ink: "text-sev-minor-ink",
    tint: "bg-sev-minor/10",
    stripe: "border-l-sev-minor",
    icon: "info",
  },
  info: { ink: "text-muted", tint: "bg-sand/40", stripe: "border-l-sand", icon: "info" },
  unknown: { ink: "text-muted", tint: "bg-sand/40", stripe: "border-l-sand", icon: "question" },
  none: { ink: "text-primary", tint: "bg-primary/10", stripe: "border-l-primary", icon: "check" },
};

export const severityStripe = (level: Level): string => STYLE[level].stripe;

export function SeverityBadge({ level }: { level: Level }) {
  const { t } = useTranslation();
  const style = STYLE[level];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold ${style.tint} ${style.ink}`}
    >
      <Icon name={style.icon} />
      {t(`severity.${level}`)}
    </span>
  );
}

type IconName = "stop" | "warning" | "alert" | "info" | "question" | "check";

export function Icon({ name, className = "h-4 w-4" }: { name: IconName; className?: string }) {
  const paths: Record<IconName, string> = {
    stop: "M7.86 2h8.28L22 7.86v8.28L16.14 22H7.86L2 16.14V7.86L7.86 2zM12 7v6m0 3.5v.5",
    warning: "M12 3l10 18H2L12 3zm0 7v5m0 3v.5",
    alert: "M12 2a10 10 0 100 20 10 10 0 000-20zm0 5v6m0 3.5v.5",
    info: "M12 2a10 10 0 100 20 10 10 0 000-20zm0 9v6m0-10v.5",
    question:
      "M12 2a10 10 0 100 20 10 10 0 000-20zm-2.5 7.5a2.5 2.5 0 115 0c0 1.5-2.5 2-2.5 3.5m0 3v.5",
    check: "M12 2a10 10 0 100 20 10 10 0 000-20zm-4.5 10l3 3 6-6",
  };
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
