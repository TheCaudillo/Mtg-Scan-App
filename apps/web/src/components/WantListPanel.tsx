"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { WantItem } from "@/lib/types";
import { saveLocalWantlist } from "@/lib/wantlist";
import { Button } from "./ui";

export function WantListPanel({ text, items, onSaved, onClose }: {
  text: string;
  items: WantItem[];
  onSaved: (text: string, items: WantItem[]) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(text);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function save(t: string) {
    setBusy(true);
    setMsg(null);
    try {
      const wl = await api.putWantlist(t);
      saveLocalWantlist(t, wl.items);
      onSaved(t, wl.items);
      setMsg(`Saved ${wl.items.length} cards`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label="Want list">
      <button aria-label="Close" className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg space-y-3 rounded-t-2xl bg-zinc-950 p-4 ring-1 ring-zinc-800 sm:rounded-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Want / buy list</h2>
          <Button variant="ghost" onClick={onClose}>✕</Button>
        </div>
        <p className="text-sm text-zinc-400">
          One card per line (<code className="text-zinc-300">4 Lightning Bolt</code>, <code className="text-zinc-300">Sol Ring (CMR)</code>) or paste/upload a CSV with a <code className="text-zinc-300">Name</code> column. Matches get a ★ Want badge.
        </p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={10}
          placeholder={"Sword of Once and Future\n2 Cathar Commando\nReclaim (ORI)"}
          className="w-full rounded-md bg-zinc-900 p-3 font-mono text-sm ring-1 ring-zinc-700 outline-none focus:ring-amber-400"
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="cursor-pointer rounded-md bg-zinc-800 px-3 py-2 text-sm ring-1 ring-zinc-700 hover:bg-zinc-700">
            Upload CSV/TXT
            <input type="file" accept=".csv,.txt,text/plain,text/csv" hidden onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setDraft(await f.text());
              e.target.value = "";
            }} />
          </label>
          <span className="text-xs text-zinc-500">{items.length} saved</span>
          <span className="ml-auto text-xs text-zinc-400">{msg}</span>
          <Button variant="primary" disabled={busy} onClick={() => void save(draft)}>Save</Button>
        </div>
      </div>
    </div>
  );
}
