"use client";

import type { ReactNode } from "react";
import type { CardRecord } from "@/lib/types";

export function cx(...c: (string | false | null | undefined)[]): string {
  return c.filter(Boolean).join(" ");
}

export function Badge({ children, tone = "zinc", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium leading-none whitespace-nowrap", TONES[tone])}>
      {children}
    </span>
  );
}

type Tone = "zinc" | "amber" | "emerald" | "rose" | "sky" | "violet" | "fuchsia";
const TONES: Record<Tone, string> = {
  zinc: "bg-zinc-800 text-zinc-300 ring-1 ring-inset ring-zinc-700",
  amber: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30",
  emerald: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/30",
  rose: "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/30",
  sky: "bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/30",
  violet: "bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/30",
  fuchsia: "bg-fuchsia-500/15 text-fuchsia-300 ring-1 ring-inset ring-fuchsia-500/30",
};

export function Button({
  children, onClick, variant = "default", disabled, className, title, type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "ghost" | "danger" | "selected";
  disabled?: boolean;
  className?: string;
  title?: string;
  type?: "button" | "submit";
}) {
  const v = {
    default: "bg-zinc-800 hover:bg-zinc-700 text-zinc-100 ring-1 ring-inset ring-zinc-700",
    primary: "bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold",
    ghost: "hover:bg-zinc-800 text-zinc-300",
    danger: "bg-rose-600/90 hover:bg-rose-500 text-white",
    selected: "bg-amber-500/20 text-amber-200 ring-1 ring-inset ring-amber-400",
  }[variant];
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={cx("inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md px-3 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40", v, className)}
    >
      {children}
    </button>
  );
}

export const REASON_LABEL: Record<string, string> = {
  same_art_reprint: "Same-art reprint",
  collector_number_unreadable: "Collector # unreadable",
  glare_over_finish: "Finish hidden by glare",
  foil_price_inversion: "Foil price inversion",
  low_confidence: "Low confidence",
  visual_text_conflict: "Art/name conflict",
  language_uncertain: "Language uncertain",
  no_match: "No match",
  manual: "Manual",
};

export function StatusBadge({ card }: { card: CardRecord }) {
  if (card.status === "pending") return <Badge tone="zinc">scanning…</Badge>;
  if (card.status === "unidentified") return <Badge tone="rose">unidentified</Badge>;
  if (card.user_verified) return <Badge tone="emerald">✓ verified</Badge>;
  if (card.needs_review)
    return (
      <Badge tone="amber" title={card.review_reasons.map((r) => REASON_LABEL[r] ?? r).join(", ")}>
        review
      </Badge>
    );
  return <Badge tone="emerald">{Math.round(card.confidence * 100)}%</Badge>;
}

export function TreatmentBadges({ treatments, max = 3 }: { treatments: string[]; max?: number }) {
  const shown = treatments.filter((t) => t !== "Mythic").slice(0, max);
  return (
    <>
      {shown.map((t) => (
        <Badge key={t} tone={t.includes("Foil") ? "fuchsia" : "violet"}>
          {t}
        </Badge>
      ))}
    </>
  );
}

export const FINISH_LABEL: Record<string, string> = { nonfoil: "Non-foil", foil: "Foil", etched: "Etched", uncertain: "Finish?" };

export const LANG_LABEL: Record<string, string> = {
  en: "EN", es: "ES", fr: "FR", de: "DE", it: "IT", pt: "PT", ja: "JA", ko: "KO", ru: "RU", zhs: "ZH", zht: "ZH",
};
