"use client";

import { useCallback, useMemo, useState } from "react";
import { api, prepareUpload } from "@/lib/api";
import { DEFAULT_SETTINGS, cardLines, summarize } from "@/lib/lot";
import type { CardRecord, LotSettings, WantItem } from "@/lib/types";
import { useBatch } from "@/lib/useBatch";
import { useLocalState } from "@/lib/useLocalState";
import { wantMatcher } from "@/lib/wantlist";
import { CalculatorBar } from "./CalculatorBar";
import { CardTable } from "./CardTable";
import { ExportMenu } from "./ExportMenu";
import { PageViewer } from "./PageViewer";
import { ReviewDrawer } from "./ReviewDrawer";
import { UploadZone } from "./UploadZone";
import { Button, cx } from "./ui";

type Filter = "all" | "review" | "liquid" | "bulk" | "wanted" | "unidentified";
type Sort = "slot" | "price";

export function LotView({ batchId, onBack, wantItems, onOpenWantlist }: {
  batchId: string;
  onBack: () => void;
  wantItems: WantItem[];
  onOpenWantlist: () => void;
}) {
  const { batch, error, live, replaceCard, addPages } = useBatch(batchId);
  const [settings, setSettings] = useLocalState<LotSettings>("binderscan.settings.v1", DEFAULT_SETTINGS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("slot");
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [activePage, setActivePage] = useState<string | null>(null);

  const isWanted = useMemo(() => wantMatcher(wantItems), [wantItems]);
  const cards = useMemo(() => batch?.cards ?? [], [batch?.cards]);
  const pages = useMemo(() => batch?.pages ?? [], [batch?.pages]);
  const summary = useMemo(() => summarize(cardLines(cards), settings), [cards, settings]);
  const pageNo = useCallback((pid: string) => (pages.find((p) => p.id === pid)?.index ?? 0) + 1, [pages]);

  const needsReview = (c: CardRecord) => (c.needs_review || c.status === "unidentified") && !c.user_verified && c.status !== "pending";
  const reviewCount = cards.filter(needsReview).length;

  const counts: Record<Filter, number> = {
    all: cards.length,
    review: reviewCount,
    liquid: cards.filter((c) => c.unit_price_usd !== null && c.unit_price_usd >= settings.bulk_cutoff_usd).length,
    bulk: cards.filter((c) => c.selected && (c.unit_price_usd === null || c.unit_price_usd < settings.bulk_cutoff_usd)).length,
    wanted: cards.filter(isWanted).length,
    unidentified: cards.filter((c) => c.status === "unidentified").length,
  };

  const visible = useMemo(() => {
    const f = cards.filter((c) => {
      switch (filter) {
        case "review": return needsReview(c);
        case "liquid": return c.unit_price_usd !== null && c.unit_price_usd >= settings.bulk_cutoff_usd;
        case "bulk": return !!c.selected && (c.unit_price_usd === null || c.unit_price_usd < settings.bulk_cutoff_usd);
        case "wanted": return isWanted(c);
        case "unidentified": return c.status === "unidentified";
        default: return true;
      }
    });
    return sort === "price" ? [...f].sort((a, b) => (b.unit_price_usd ?? -1) - (a.unit_price_usd ?? -1)) : f;
  }, [cards, filter, sort, settings.bulk_cutoff_usd, isWanted]);

  const shownPage = pages.find((p) => p.id === activePage) ?? pages.find((p) => p.id === cards.find((c) => c.id === selectedId)?.page_id) ?? pages[0];
  const scanning = batch?.status === "scanning" || pages.some((p) => p.status === "detecting" || p.status === "matching");
  const unscanned = pages.filter((p) => p.status === "uploaded" || p.status === "error").length;

  async function upload(files: File[]) {
    setUploading(true);
    setMsg(null);
    try {
      const blobs = await Promise.all(files.map((f) => prepareUpload(f)));
      const names = files.map((f) => (f.name.replace(/\.(heic|heif)$/i, ".jpg") || "photo.jpg"));
      const newPages = await api.uploadPages(batchId, blobs, names);
      addPages(newPages);
      setActivePage(newPages[0]?.id ?? null);
      await api.scan(batchId);  // scan right away; boxes can be adjusted and re-scanned per page
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  const select = (id: string) => {
    setSelectedId(id);
    const c = cards.find((x) => x.id === id);
    if (c) setActivePage(c.page_id);
  };

  const drawerCard = cards.find((c) => c.id === drawerId) ?? null;
  const navList = visible.length ? visible : cards;
  const nav = useCallback((dir: -1 | 1) => {
    if (!drawerId) return;
    const i = navList.findIndex((c) => c.id === drawerId);
    const next = navList[(i + dir + navList.length) % navList.length];
    if (next) { setDrawerId(next.id); select(next.id); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawerId, navList]);

  if (error && !batch) return <div className="p-6 text-rose-300">Could not load lot: {error}. Is the scanner API running?</div>;
  if (!batch) return <div className="p-6 text-zinc-500">Loading lot…</div>;

  return (
    <div className="min-h-screen">
      <CalculatorBar settings={settings} setSettings={setSettings} summary={summary} reviewCount={reviewCount} />

      <div className="mx-auto max-w-7xl space-y-4 px-3 py-4 sm:px-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="ghost" onClick={onBack} className="px-2">← Lots</Button>
          <h1 className="mr-auto truncate text-lg font-semibold">{batch.name}</h1>
          <span className={cx("h-2 w-2 rounded-full", live ? "bg-emerald-400" : "bg-zinc-600")} title={live ? "Live updates connected" : "Live updates offline (polling)"} />
          {unscanned > 0 && !scanning && <Button variant="primary" onClick={() => void api.scan(batchId)}>Scan {unscanned} page(s)</Button>}
          {scanning && <span className="animate-pulse text-sm text-amber-300">Scanning…</span>}
          <Button onClick={onOpenWantlist}>★ Want list{wantItems.length ? ` (${wantItems.length})` : ""}</Button>
          <ExportMenu batchId={batchId} settings={settings} unverified={reviewCount} />
        </div>
        {msg && <div className="rounded bg-rose-500/10 p-2 text-sm text-rose-300">{msg}</div>}

        {pages.length === 0 ? (
          <UploadZone onFiles={(f) => void upload(f)} busy={uploading} />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
            <div className="space-y-3 lg:sticky lg:top-24 lg:self-start">
              {pages.length > 1 && (
                <div className="flex gap-1 overflow-x-auto pb-1">
                  {pages.map((p) => (
                    <button key={p.id} onClick={() => setActivePage(p.id)}
                      className={cx("shrink-0 rounded-md px-3 py-1 text-xs ring-1", p.id === shownPage?.id ? "bg-amber-500/20 text-amber-200 ring-amber-400" : "text-zinc-400 ring-zinc-700 hover:bg-zinc-800")}>
                      Pg {p.index + 1}
                      {p.status === "error" ? " ⚠" : p.status === "done" ? ` · ${p.card_count}` : p.status === "uploaded" ? "" : " …"}
                    </button>
                  ))}
                </div>
              )}
              {shownPage && (
                <PageViewer
                  key={shownPage.id}
                  page={shownPage}
                  cards={cards.filter((c) => c.page_id === shownPage.id)}
                  selectedId={selectedId}
                  onSelect={(id) => { select(id); setDrawerId(id); }}
                  batchId={batchId}
                  busy={uploading}
                />
              )}
              <UploadZone onFiles={(f) => void upload(f)} busy={uploading} compact />
            </div>

            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {([
                  ["all", "All"], ["review", "Needs review"], ["liquid", "Liquid"], ["bulk", "Bulk"], ["wanted", "★ Wanted"], ["unidentified", "Unidentified"],
                ] as [Filter, string][]).map(([k, label]) => (
                  <button key={k} onClick={() => setFilter(k)}
                    className={cx("rounded-full px-3 py-1 text-xs ring-1 transition-colors",
                      filter === k ? "bg-amber-500 font-semibold text-zinc-950 ring-amber-500" : "text-zinc-300 ring-zinc-700 hover:bg-zinc-800",
                      k === "review" && counts.review > 0 && filter !== k && "text-amber-300 ring-amber-500/50")}>
                    {label} <span className="tabular-nums opacity-70">{counts[k]}</span>
                  </button>
                ))}
                <select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="ml-auto rounded-md bg-zinc-900 px-2 py-1 text-xs ring-1 ring-zinc-700">
                  <option value="slot">Sort: page/slot</option>
                  <option value="price">Sort: price ↓</option>
                </select>
              </div>
              <CardTable cards={visible} settings={settings} selectedId={selectedId} onSelect={select} onOpen={setDrawerId} isWanted={isWanted} pageNo={pageNo} />
            </div>
          </div>
        )}
      </div>

      {drawerCard && (
        <ReviewDrawer
          key={drawerCard.id}
          card={drawerCard}
          settings={settings}
          onClose={() => setDrawerId(null)}
          onUpdated={replaceCard}
          onNav={nav}
          navLabel={`${navList.findIndex((c) => c.id === drawerCard.id) + 1}/${navList.length}`}
        />
      )}
    </div>
  );
}
