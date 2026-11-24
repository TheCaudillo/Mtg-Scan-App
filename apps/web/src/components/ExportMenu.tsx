"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { LotSettings } from "@/lib/types";
import { Button } from "./ui";

export function ExportMenu({ batchId, settings, unverified }: { batchId: string; settings: LotSettings; unverified: number }) {
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const params = {
    condition: settings.condition_label,
    non_english_discount_pct: String(settings.non_english_discount_pct),
    bulk_cutoff_usd: String(settings.bulk_cutoff_usd),
  };

  async function copyMarkdown() {
    try {
      const res = await fetch(api.exportUrl(batchId, "markdown", params));
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      setMsg("Markdown copied");
    } catch {
      setMsg("Copy failed — opening instead");
      window.open(api.exportUrl(batchId, "markdown", params), "_blank");
    }
    setTimeout(() => setMsg(null), 2500);
  }

  return (
    <div className="relative">
      <Button onClick={() => setOpen((o) => !o)} aria-expanded={open}>⇩ Export</Button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-64 space-y-1 rounded-lg bg-zinc-900 p-2 shadow-xl ring-1 ring-zinc-700">
          {unverified > 0 && <div className="px-2 pb-1 text-xs text-amber-300">{unverified} card(s) still need review — exported as currently selected.</div>}
          {([
            ["csv", "Detailed CSV"],
            ["manabox", "ManaBox CSV"],
            ["moxfield", "Moxfield CSV"],
          ] as const).map(([fmt, label]) => (
            <a key={fmt} href={api.exportUrl(batchId, fmt, params)} className="block rounded px-2 py-2 text-sm hover:bg-zinc-800" onClick={() => setOpen(false)}>
              {label}
            </a>
          ))}
          <button onClick={() => void copyMarkdown()} className="block w-full rounded px-2 py-2 text-left text-sm hover:bg-zinc-800">
            Copy Markdown summary
          </button>
          {msg && <div className="px-2 text-xs text-emerald-300">{msg}</div>}
        </div>
      )}
    </div>
  );
}
