"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BatchListItem, Health, WantItem } from "@/lib/types";
import { loadLocalWantlist, saveLocalWantlist } from "@/lib/wantlist";
import { LotView } from "./LotView";
import { WantListPanel } from "./WantListPanel";
import { Button } from "./ui";

function readHash(): string | null {
  const m = /lot=([\w-]+)/.exec(window.location.hash);
  return m ? m[1] : null;
}

export function App() {
  const [lotId, setLotId] = useState<string | null>(readHash);
  const [lots, setLots] = useState<BatchListItem[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [want, setWant] = useState<{ text: string; items: WantItem[] }>(loadLocalWantlist);
  const [wantOpen, setWantOpen] = useState(false);
  const [name, setName] = useState("");

  const loadLots = useCallback(() => {
    Promise.all([api.health(), api.listBatches()])
      .then(([h, l]) => {
        setHealth(h);
        setLots(l);
        setErr(null);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    const onHash = () => setLotId(readHash());
    window.addEventListener("hashchange", onHash);
    const local = loadLocalWantlist();
    void api.getWantlist().then((wl) => {
      if (wl.items.length) setWant((w) => ({ text: w.text || wl.items.map((i) => `${i.quantity > 1 ? `${i.quantity} ` : ""}${i.name}${i.set_code ? ` (${i.set_code.toUpperCase()})` : ""}`).join("\n"), items: wl.items }));
      else if (local.items.length) void api.putWantlist(local.text);
    }).catch(() => undefined);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!lotId) loadLots();
  }, [lotId, loadLots]);

  const open = (id: string | null) => {
    window.location.hash = id ? `lot=${id}` : "";
    setLotId(id);
  };

  async function create() {
    try {
      const b = await api.createBatch(name.trim() || undefined);
      setName("");
      open(b.id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const wantPanel = wantOpen && (
    <WantListPanel text={want.text} items={want.items} onClose={() => setWantOpen(false)}
      onSaved={(text, items) => { setWant({ text, items }); saveLocalWantlist(text, items); }} />
  );

  if (lotId) {
    return (
      <>
        <LotView batchId={lotId} onBack={() => open(null)} wantItems={want.items} onOpenWantlist={() => setWantOpen(true)} />
        {wantPanel}
      </>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">
          BinderScan <span className="text-amber-400">MTG</span>
        </h1>
        <p className="text-sm text-zinc-400">Scan binder pages, identify exact printings against a local Scryfall mirror, and price the lot.</p>
      </header>

      {err && (
        <div className="rounded-lg bg-rose-500/10 p-3 text-sm text-rose-300 ring-1 ring-rose-500/30">
          Scanner API unreachable ({err}). Start it with <code className="text-rose-200">make api</code>.
        </div>
      )}
      {health && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
          <span>{health.printings.toLocaleString()} printings{health.sync.synced_at ? ` · synced ${health.sync.synced_at.slice(0, 10)}` : ""}</span>
          <span>art index: {health.matcher.visual_index ?? "not built"}</span>
          <span>OCR: {health.matcher.ocr ?? "off"}</span>
          <span>vision LLM: {health.matcher.vision ?? "off"}</span>
          {health.printings === 0 && <span className="text-amber-300">Run <code>make sync</code> first!</span>}
        </div>
      )}

      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void create(); }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New lot name (optional)"
          className="min-w-0 flex-1 rounded-md bg-zinc-900 px-3 py-2 text-base ring-1 ring-zinc-700 outline-none focus:ring-amber-400 sm:text-sm" />
        <Button type="submit" variant="primary">+ New lot</Button>
      </form>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-500">Recent lots</h2>
          <Button variant="ghost" onClick={() => setWantOpen(true)}>★ Want list ({want.items.length})</Button>
        </div>
        {lots.length === 0 && <div className="rounded-lg border border-dashed border-zinc-800 p-6 text-center text-sm text-zinc-500">No lots yet — create one and drop in your binder photos.</div>}
        <ul className="divide-y divide-zinc-800 overflow-hidden rounded-lg ring-1 ring-zinc-800">
          {lots.map((l) => (
            <li key={l.id} className="flex items-center gap-3 px-3 py-3 hover:bg-zinc-900">
              <button className="min-w-0 flex-1 text-left" onClick={() => open(l.id)}>
                <div className="truncate font-medium">{l.name}</div>
                <div className="text-xs text-zinc-500">{l.pages} page(s) · {l.cards} cards · {l.status} · {l.created_at.slice(0, 16).replace("T", " ")}</div>
              </button>
              <Button variant="ghost" title="Delete lot" onClick={async () => {
                if (!confirm(`Delete “${l.name}”?`)) return;
                await api.deleteBatch(l.id);
                loadLots();
              }}>🗑</Button>
            </li>
          ))}
        </ul>
      </section>
      {wantPanel}
    </main>
  );
}
