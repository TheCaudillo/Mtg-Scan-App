// Lot buyer calculator — mirrors services/scanner/scanner/lot.py (keep in sync; both are tested).
import type { CardRecord, ConditionLabel, LotSettings, LotSummary } from "./types";

export const CONDITION_PRESETS: Record<ConditionLabel, number> = { NM: 100, LP: 85, MP: 70, HP: 50 };
export const BORDERLINE_TOLERANCE = 1.15;

export const DEFAULT_SETTINGS: LotSettings = {
  asking_price: null,
  currency: "USD",
  fx_rate_mxn_per_usd: 18.0,
  bulk_cutoff_usd: 2.0,
  condition_label: "NM",
  condition_pct: 100,
  non_english_discount_pct: 20,
  target_buy_rate_pct: 65,
};

export interface LotLine {
  unit_price_usd: number | null;
  quantity: number;
  lang: string;
}

const r2 = (v: number) => Math.round(v * 100) / 100;

export function summarize(lines: LotLine[], s: LotSettings): LotSummary {
  let total = 0, priced = 0, unpriced = 0, liquidN = 0, bulkN = 0;
  let retail = 0, liquid = 0, bulk = 0, adjLiquid = 0, adjBulk = 0;
  const cond = s.condition_pct / 100;
  const ne = 1 - s.non_english_discount_pct / 100;
  for (const ln of lines) {
    const q = Math.max(0, ln.quantity);
    if (q === 0) continue;
    total += q;
    if (ln.unit_price_usd === null) {
      unpriced += q;
      continue;
    }
    priced += q;
    const value = ln.unit_price_usd * q;
    const adj = value * cond * (ln.lang !== "en" ? ne : 1);
    retail += value;
    if (ln.unit_price_usd >= s.bulk_cutoff_usd) {
      liquidN += q;
      liquid += value;
      adjLiquid += adj;
    } else {
      bulkN += q;
      bulk += value;
      adjBulk += adj;
    }
  }
  const maxOffer = (adjLiquid * s.target_buy_rate_pct) / 100;
  const askingUsd =
    s.asking_price !== null && s.asking_price > 0
      ? s.currency === "MXN"
        ? s.asking_price / s.fx_rate_mxn_per_usd
        : s.asking_price
      : null;
  const adjustedLot = adjLiquid + adjBulk;
  let margin: number | null = null;
  let marginPct: number | null = null;
  let verdict: LotSummary["verdict"] = "n/a";
  if (askingUsd !== null) {
    margin = adjustedLot - askingUsd;
    marginPct = (margin / askingUsd) * 100;
    verdict = askingUsd <= maxOffer ? "good" : askingUsd <= maxOffer * BORDERLINE_TOLERANCE ? "borderline" : "pass";
  }
  return {
    total_cards: total,
    priced_cards: priced,
    unpriced_cards: unpriced,
    liquid_cards: liquidN,
    bulk_cards: bulkN,
    retail_total_usd: r2(retail),
    liquid_total_usd: r2(liquid),
    bulk_total_usd: r2(bulk),
    adjusted_liquid_usd: r2(adjLiquid),
    adjusted_bulk_usd: r2(adjBulk),
    adjusted_lot_value_usd: r2(adjustedLot),
    suggested_max_offer_usd: r2(maxOffer),
    asking_price_usd: askingUsd === null ? null : r2(askingUsd),
    estimated_margin_usd: margin === null ? null : r2(margin),
    estimated_margin_pct: marginPct === null ? null : Math.round(marginPct * 10) / 10,
    verdict,
  };
}

export function cardLines(cards: CardRecord[]): LotLine[] {
  return cards
    .filter((c) => c.selected)
    .map((c) => ({ unit_price_usd: c.unit_price_usd, quantity: c.quantity, lang: c.lang }));
}

export function adjustedValue(c: CardRecord, s: LotSettings): number | null {
  if (c.unit_price_usd === null) return null;
  let v = (c.unit_price_usd * c.quantity * s.condition_pct) / 100;
  if (c.lang !== "en") v *= 1 - s.non_english_discount_pct / 100;
  return r2(v);
}

export function fmtUsd(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "N/A";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtMxn(v: number | null | undefined): string {
  if (v === null || v === undefined) return "N/A";
  return `MX$${Math.round(v).toLocaleString("en-US")}`;
}
