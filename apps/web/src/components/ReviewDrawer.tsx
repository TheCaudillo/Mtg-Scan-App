"use client";

import { useEffect, useMemo, useState } from "react";
import { api, fileUrl } from "@/lib/api";
import { adjustedValue, fmtUsd } from "@/lib/lot";
import type { CardRecord, Finish, LotSettings, Printing } from "@/lib/types";
import { Badge, Button, FINISH_LABEL, REASON_LABEL, StatusBadge, TreatmentBadges, cx } from "./ui";

const LANG_CHOICES = [
  { code: "en", label: "EN" },
  { code: "es", label: "ES" },
];
const OTHER_LANGS = ["fr", "de", "it", "pt", "ja", "ko", "ru", "zhs", "zht"];

type DiffKey = "set" | "border" | "frame" | "effects" | "finishes" | "rules" | "promo" | "year";

function diffKeys(cands: Printing[]): Set<DiffKey> {
  const out = new Set<DiffKey>();
  if (cands.length < 2) return out;
  const uniq = (f: (p: Printing) => string) => new Set(cands.map(f)).size > 1;
  if (uniq((p) => p.set_code)) out.add("set");
  if (uniq((p) => p.border_color ?? "")) out.add("border");
  if (uniq((p) => p.frame ?? "")) out.add("frame");
  if (uniq((p) => [...p.frame_effects, ...p.promo_types].sort().join(","))) out.add("effects");
  if (uniq((p) => [...p.finishes].sort().join(","))) out.add("finishes");
  if (uniq((p) => (p.oracle_text ?? "").replace(/\s+/g, " ").trim())) out.add("rules");
  if (uniq((p) => (p.released_at ?? "").slice(0, 4))) out.add("year");
  if (uniq((p) => p.treatments.join(","))) out.add("promo");
  return out;
}

function Hl({ on, children }: { on: boolean; children: React.ReactNode }) {
  return <span className={cx(on && "rounded bg-amber-400/20 px-1 text-amber-200")}>{children}</span>;
}

function CandidateCard({ p, selected, diffs, onPick, busy }: { p: Printing; selected: boolean; diffs: Set<DiffKey>; onPick: () => void; busy: boolean }) {
  return (
    <div className={cx("flex flex-col gap-2 rounded-lg p-2 ring-1", selected ? "bg-amber-500/10 ring-amber-400" : "bg-zinc-900 ring-zinc-800")}>
      <a href={p.scryfall_uri ?? "#"} target="_blank" rel="noreferrer" className="block">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={p.image_normal ?? p.image_small ?? ""} alt={p.name} loading="lazy" className="aspect-[488/680] w-full rounded-md bg-zinc-800 object-cover" />
      </a>
      <div className="space-y-1 text-xs">
        <div className="font-medium text-zinc-100">
          <Hl on={diffs.has("set")}>{p.set_code.toUpperCase()} #{p.collector_number}</Hl>
        </div>
        <div className="truncate text-zinc-400" title={p.set_name ?? ""}>{p.set_name}</div>
        <div className="flex flex-wrap gap-x-2 text-zinc-400">
          <Hl on={diffs.has("year")}>{p.released_at?.slice(0, 4)}</Hl>
          <Hl on={diffs.has("border")}>{p.border_color} border</Hl>
          <Hl on={diffs.has("frame")}>{p.frame} frame</Hl>
          {p.rarity && <span className="capitalize">{p.rarity}</span>}
        </div>
        {(p.frame_effects.length > 0 || p.treatments.length > 0) && (
          <div className={cx("flex flex-wrap gap-1", diffs.has("effects") || diffs.has("promo") ? "rounded bg-amber-400/10 p-0.5" : "")}>
            <TreatmentBadges treatments={p.treatments} max={4} />
            {p.frame_effects.filter((f) => !["extendedart", "showcase"].includes(f)).map((f) => <Badge key={f}>{f}</Badge>)}
          </div>
        )}
        <div className="grid grid-cols-3 gap-1 tabular-nums">
          <span className={cx(!p.finishes.includes("nonfoil") && "line-through opacity-40")} title="Non-foil">● {fmtUsd(p.usd)}</span>
          <span className={cx(!p.finishes.includes("foil") && "line-through opacity-40", "text-fuchsia-300")} title="Foil">★ {fmtUsd(p.usd_foil)}</span>
          <span className={cx(!p.finishes.includes("etched") && "opacity-30")} title="Etched">E {fmtUsd(p.usd_etched)}</span>
        </div>
        {p.price_inversion && <Badge tone="rose">non-foil &gt; foil</Badge>}
        {diffs.has("rules") && p.oracle_text && <p className="line-clamp-3 rounded bg-amber-400/10 p-1 text-[11px] text-amber-100">{p.oracle_text}</p>}
      </div>
      <Button variant={selected ? "selected" : "primary"} onClick={onPick} disabled={busy} className="mt-auto">
        {selected ? "✓ Selected" : "This one"}
      </Button>
    </div>
  );
}

export function ReviewDrawer({ card, settings, onClose, onUpdated, onNav, navLabel }: {
  card: CardRecord;
  settings: LotSettings;
  onClose: () => void;
  onUpdated: (c: CardRecord) => void;
  onNav: (dir: -1 | 1) => void;
  navLabel: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // parent renders this with key={card.id}, so state resets when navigating between cards
  const [query, setQuery] = useState(card.observed?.name ?? card.observed?.printed_name ?? "");
  const [extra, setExtra] = useState<Printing[] | null>(null);
  const [extraLabel, setExtraLabel] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === "j") onNav(1);
      if (e.key === "ArrowLeft" || e.key === "k") onNav(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onNav]);

  async function patch(p: Parameters<typeof api.patchCard>[1]) {
    setBusy(true);
    setErr(null);
    try {
      onUpdated(await api.patchCard(card.id, p));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runSearch() {
    if (query.trim().length < 2) return;
    setBusy(true);
    try {
      setExtra(await api.search(query.trim()));
      setExtraLabel(`Search: “${query.trim()}”`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function allPrintings() {
    if (!card.selected) return;
    setBusy(true);
    try {
      setExtra(await api.alternatives(card.selected.scryfall_id));
      setExtraLabel(`All printings of ${card.selected.name}`);
    } finally {
      setBusy(false);
    }
  }

  const shown = extra ?? card.candidates;
  const diffs = useMemo(() => diffKeys(shown), [shown]);
  const sel = card.selected;
  const finishes = (sel?.finishes ?? []) as Finish[];
  const obs = card.observed;

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Review card">
      <button aria-label="Close" className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-5xl flex-col overflow-hidden bg-zinc-950 shadow-2xl ring-1 ring-zinc-800">
        <header className="flex items-center gap-2 border-b border-zinc-800 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-sm text-zinc-500">Slot {card.slot}</span>
              <StatusBadge card={card} />
              {card.match_method && <span className="hidden text-[11px] text-zinc-600 sm:inline">via {card.match_method}</span>}
            </div>
            <div className="truncate text-lg font-semibold">{sel ? sel.name : "Unidentified card"}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {card.review_reasons.map((r) => <Badge key={r} tone="amber">{REASON_LABEL[r] ?? r}</Badge>)}
              {card.error && <Badge tone="rose" title={card.error}>error</Badge>}
            </div>
          </div>
          <Button variant="ghost" onClick={() => onNav(-1)} title="Previous (←)">‹</Button>
          <span className="text-xs tabular-nums text-zinc-500">{navLabel}</span>
          <Button variant="ghost" onClick={() => onNav(1)} title="Next (→)">›</Button>
          <Button variant="ghost" onClick={onClose} title="Close (Esc)">✕</Button>
        </header>

        <div className="grid flex-1 gap-4 overflow-y-auto p-4 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
          {/* left: the user's photo */}
          <section className="space-y-3">
            <div className="text-[11px] uppercase tracking-wide text-zinc-500">Your photo</div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl(card.crop_url)} alt="Your card crop" className="mx-auto w-full max-w-[15rem] rounded-lg ring-1 ring-zinc-700" />
            <div className="text-[11px] uppercase tracking-wide text-zinc-500">Collector strip (zoomed)</div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl(card.strip_url)} alt="Collector strip" className="w-full rounded ring-1 ring-zinc-700" />
            {obs && (
              <div className="rounded-md bg-zinc-900 p-2 text-xs text-zinc-400 ring-1 ring-zinc-800">
                <div className="mb-1 text-[10px] uppercase tracking-wide text-zinc-500">Read from photo ({obs.source})</div>
                {[
                  ["Name", obs.printed_name ?? obs.name],
                  ["Set / #", [obs.set_code?.toUpperCase(), obs.collector_number].filter(Boolean).join(" #")],
                  ["Language", obs.language?.toUpperCase()],
                  ["Foil marker", obs.foil_symbol === "star" ? "★ star" : obs.foil_symbol === "dot" ? "• dot" : obs.foil_symbol],
                  ["Sheen", obs.foil_sheen],
                ].filter(([, v]) => v).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2"><span>{k}</span><span className="text-zinc-200">{v}</span></div>
                ))}
              </div>
            )}

            {/* one-tap controls */}
            {sel && (
              <div className="space-y-3 rounded-lg bg-zinc-900 p-3 ring-1 ring-zinc-800">
                <div>
                  <div className="mb-1 flex items-center justify-between text-[11px] uppercase tracking-wide text-zinc-500">
                    <span>Finish</span>
                    {card.foil_detection === "uncertain" && <span className="normal-case text-amber-300">not confirmed</span>}
                  </div>
                  <div className="grid grid-cols-3 gap-1">
                    {(["nonfoil", "foil", "etched"] as Finish[]).map((f) => (
                      <Button key={f} disabled={busy || !finishes.includes(f)} variant={card.finish === f && card.foil_detection !== "uncertain" ? "selected" : card.finish === f ? "default" : "ghost"} onClick={() => void patch({ finish: f })} className="px-1 text-xs">
                        {FINISH_LABEL[f]}
                      </Button>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">Language</div>
                  <div className="flex gap-1">
                    {LANG_CHOICES.map((l) => (
                      <Button key={l.code} disabled={busy} variant={card.lang === l.code ? "selected" : "ghost"} onClick={() => void patch({ lang: l.code })} className="flex-1 text-xs">{l.label}</Button>
                    ))}
                    <select
                      aria-label="Other language"
                      value={OTHER_LANGS.includes(card.lang) ? card.lang : ""}
                      onChange={(e) => e.target.value && void patch({ lang: e.target.value })}
                      className={cx("flex-1 rounded-md bg-zinc-800 px-1 text-xs", OTHER_LANGS.includes(card.lang) && "ring-1 ring-amber-400")}
                    >
                      <option value="">Other…</option>
                      {OTHER_LANGS.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
                    </select>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] uppercase tracking-wide text-zinc-500">Quantity</span>
                  <div className="flex items-center gap-1">
                    <Button disabled={busy || card.quantity <= 0} onClick={() => void patch({ quantity: card.quantity - 1 })} className="w-9 px-0">−</Button>
                    <span className="w-8 text-center tabular-nums">{card.quantity}</span>
                    <Button disabled={busy} onClick={() => void patch({ quantity: card.quantity + 1 })} className="w-9 px-0">+</Button>
                  </div>
                </div>
                <div className="flex items-baseline justify-between border-t border-zinc-800 pt-2 text-sm">
                  <span className="text-zinc-400">Unit {fmtUsd(card.unit_price_usd)}{card.price_source === "english_equivalent" && <span className="ml-1 text-[10px] text-sky-300">(EN price)</span>}</span>
                  <span className="font-semibold tabular-nums">Adj. {fmtUsd(adjustedValue(card, settings))}</span>
                </div>
                {!card.user_verified && (
                  <Button variant="primary" disabled={busy} className="w-full" onClick={() => void patch({ user_verified: true })}>✓ Looks right</Button>
                )}
              </div>
            )}
          </section>

          {/* right: candidate printings */}
          <section className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="mr-auto text-[11px] uppercase tracking-wide text-zinc-500">
                {extra ? extraLabel : `Candidate printings (${card.candidates.length})`}
                {diffs.size > 0 && <span className="ml-2 normal-case text-amber-300/80">highlighted = differs</span>}
              </div>
              {extra && <Button variant="ghost" className="min-h-7 text-xs" onClick={() => setExtra(null)}>← candidates</Button>}
              {sel && !extra && <Button variant="ghost" className="min-h-7 text-xs" onClick={() => void allPrintings()}>All printings</Button>}
            </div>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void runSearch(); }}>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search Scryfall DB by name…"
                className="min-w-0 flex-1 rounded-md bg-zinc-900 px-3 py-2 text-base ring-1 ring-zinc-700 outline-none focus:ring-amber-400 sm:text-sm"
              />
              <Button type="submit" disabled={busy}>Search</Button>
            </form>
            {err && <div className="rounded bg-rose-500/10 p-2 text-sm text-rose-300">{err}</div>}
            {shown.length === 0 ? (
              <div className="rounded-lg border border-dashed border-zinc-800 p-6 text-center text-sm text-zinc-500">
                No candidates — search by name above to pick the exact printing.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-4">
                {shown.map((p) => (
                  <CandidateCard key={p.scryfall_id} p={p} diffs={diffs} busy={busy} selected={sel?.scryfall_id === p.scryfall_id || (!!sel && sel.lang !== "en" && sel.set_code === p.set_code && sel.collector_number === p.collector_number)} onPick={() => void patch({ scryfall_id: p.scryfall_id })} />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
