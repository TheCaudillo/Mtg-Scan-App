"use client";

import { useState } from "react";
import { CONDITION_PRESETS, fmtMxn, fmtUsd } from "@/lib/lot";
import type { ConditionLabel, LotSettings, LotSummary } from "@/lib/types";
import { cx } from "./ui";

const VERDICT = {
  good: { label: "Good Deal", cls: "bg-emerald-500 text-emerald-950" },
  borderline: { label: "Borderline", cls: "bg-amber-400 text-amber-950" },
  pass: { label: "Pass", cls: "bg-rose-500 text-rose-950" },
  "n/a": { label: "Enter asking price", cls: "bg-zinc-800 text-zinc-400" },
} as const;

function Num({ label, value, onChange, step = 1, suffix, min = 0, className }: {
  label: string; value: number | null; onChange: (v: number | null) => void; step?: number; suffix?: string; min?: number; className?: string;
}) {
  return (
    <label className={cx("flex flex-col gap-1 text-[11px] uppercase tracking-wide text-zinc-400", className)}>
      {label}
      <span className="flex items-center rounded-md bg-zinc-900 ring-1 ring-zinc-700 focus-within:ring-amber-400">
        <input
          type="number"
          inputMode="decimal"
          step={step}
          min={min}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          className="w-full min-w-0 bg-transparent px-2 py-1.5 text-base text-zinc-100 outline-none sm:text-sm"
        />
        {suffix && <span className="pr-2 text-zinc-500 normal-case">{suffix}</span>}
      </span>
    </label>
  );
}

function Stat({ label, value, sub, strong }: { label: string; value: string; sub?: string; strong?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cx("truncate tabular-nums", strong ? "text-lg font-semibold text-zinc-50" : "text-sm text-zinc-200")}>{value}</div>
      {sub && <div className="truncate text-[11px] tabular-nums text-zinc-500">{sub}</div>}
    </div>
  );
}

export function CalculatorBar({ settings, setSettings, summary, reviewCount }: {
  settings: LotSettings;
  setSettings: (fn: (s: LotSettings) => LotSettings) => void;
  summary: LotSummary;
  reviewCount: number;
}) {
  const [open, setOpen] = useState(false);
  const set = <K extends keyof LotSettings>(k: K, v: LotSettings[K]) => setSettings((s) => ({ ...s, [k]: v }));
  const mxn = (usd: number | null) => (usd === null ? "" : fmtMxn(usd * settings.fx_rate_mxn_per_usd));
  const v = VERDICT[summary.verdict];

  return (
    <div className="sticky top-0 z-30 border-b border-zinc-800 bg-zinc-950/95 backdrop-blur supports-[backdrop-filter]:bg-zinc-950/80">
      <div className="mx-auto max-w-7xl px-3 py-2 sm:px-4">
        <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
          <div className="grid w-full grid-cols-3 gap-x-4 gap-y-1 sm:w-auto sm:flex-1 sm:grid-cols-6">
            <Stat label="Cards" value={String(summary.total_cards)} sub={summary.unpriced_cards ? `${summary.unpriced_cards} unpriced` : `${summary.liquid_cards} liquid · ${summary.bulk_cards} bulk`} />
            <Stat label="Retail" value={fmtUsd(summary.retail_total_usd)} sub={mxn(summary.retail_total_usd)} />
            <Stat label={`Liquid ≥${fmtUsd(settings.bulk_cutoff_usd, 0)}`} value={fmtUsd(summary.liquid_total_usd)} sub={`bulk ${fmtUsd(summary.bulk_total_usd)}`} />
            <Stat label="Adjusted lot" value={fmtUsd(summary.adjusted_lot_value_usd)} sub={mxn(summary.adjusted_lot_value_usd)} />
            <Stat strong label="Max offer" value={fmtUsd(summary.suggested_max_offer_usd)} sub={mxn(summary.suggested_max_offer_usd)} />
            <Stat
              label="Est. margin"
              value={summary.estimated_margin_usd === null ? "—" : fmtUsd(summary.estimated_margin_usd)}
              sub={summary.estimated_margin_pct === null ? undefined : `${summary.estimated_margin_pct > 0 ? "+" : ""}${summary.estimated_margin_pct}%`}
            />
          </div>
          <div className="flex w-full items-center justify-end gap-2 sm:w-auto">
            {reviewCount > 0 && (
              <span className="rounded-full bg-amber-500/15 px-2 py-1 text-xs text-amber-300 ring-1 ring-amber-500/30">{reviewCount} to review</span>
            )}
            <span className={cx("rounded-md px-3 py-1.5 text-sm font-bold", v.cls)}>{v.label}</span>
            <button
              onClick={() => setOpen((o) => !o)}
              className="rounded-md px-2 py-1.5 text-sm text-zinc-300 ring-1 ring-zinc-700 hover:bg-zinc-800"
              aria-expanded={open}
            >
              {open ? "Hide" : "Deal"} ⚙
            </button>
          </div>
        </div>

        <div className={cx("grid-cols-2 gap-3 pt-3 sm:grid-cols-4 lg:grid-cols-7", open ? "grid" : "hidden")}>
          <div className="col-span-2 flex items-end gap-2 sm:col-span-1">
            <Num label="Asking price" value={settings.asking_price} onChange={(x) => set("asking_price", x)} step={10} className="flex-1" />
            <div className="flex overflow-hidden rounded-md ring-1 ring-zinc-700">
              {(["USD", "MXN"] as const).map((c) => (
                <button key={c} onClick={() => set("currency", c)} className={cx("px-2 py-1.5 text-xs", settings.currency === c ? "bg-amber-500 text-zinc-950 font-semibold" : "text-zinc-400 hover:bg-zinc-800")}>
                  {c}
                </button>
              ))}
            </div>
          </div>
          <Num label="MXN per USD" value={settings.fx_rate_mxn_per_usd} onChange={(x) => set("fx_rate_mxn_per_usd", x && x > 0 ? x : 1)} step={0.1} />
          <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-zinc-400">
            Bulk cutoff {fmtUsd(settings.bulk_cutoff_usd)}
            <input type="range" min={0.25} max={10} step={0.25} value={settings.bulk_cutoff_usd} onChange={(e) => set("bulk_cutoff_usd", Number(e.target.value))} className="h-9 accent-amber-400" />
          </label>
          <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-zinc-400">
            Condition
            <div className="flex overflow-hidden rounded-md ring-1 ring-zinc-700">
              {(Object.keys(CONDITION_PRESETS) as ConditionLabel[]).map((k) => (
                <button
                  key={k}
                  onClick={() => setSettings((s) => ({ ...s, condition_label: k, condition_pct: CONDITION_PRESETS[k] }))}
                  className={cx("flex-1 px-1 py-1.5 text-xs", settings.condition_label === k ? "bg-amber-500 font-semibold text-zinc-950" : "text-zinc-300 hover:bg-zinc-800")}
                  title={`${CONDITION_PRESETS[k]}%`}
                >
                  {k}
                </button>
              ))}
            </div>
          </label>
          <Num label="Non-English disc." value={settings.non_english_discount_pct} onChange={(x) => set("non_english_discount_pct", x ?? 0)} suffix="%" />
          <Num label="Target buy rate" value={settings.target_buy_rate_pct} onChange={(x) => set("target_buy_rate_pct", x ?? 0)} suffix="%" />
          <div className="col-span-2 self-end text-[11px] leading-snug text-zinc-500 sm:col-span-1">
            Max offer = {settings.target_buy_rate_pct}% × liquid value after condition ({settings.condition_pct}%) and non-EN discount. Bulk is a bonus.
          </div>
        </div>
      </div>
    </div>
  );
}
