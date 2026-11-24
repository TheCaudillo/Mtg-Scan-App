"use client";

import { useEffect, useRef } from "react";
import { fileUrl } from "@/lib/api";
import { adjustedValue, fmtUsd } from "@/lib/lot";
import type { CardRecord, LotSettings } from "@/lib/types";
import { Badge, FINISH_LABEL, LANG_LABEL, StatusBadge, TreatmentBadges, cx } from "./ui";

export function CardTable({ cards, settings, selectedId, onSelect, onOpen, isWanted, pageNo }: {
  cards: CardRecord[];
  settings: LotSettings;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  isWanted: (c: CardRecord) => boolean;
  pageNo: (pageId: string) => number;
}) {
  const rowRefs = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    if (!selectedId) return;
    rowRefs.current.get(selectedId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedId]);

  if (!cards.length) return <div className="rounded-lg border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">No cards match this filter.</div>;

  return (
    <ul className="divide-y divide-zinc-800/80 overflow-hidden rounded-lg ring-1 ring-zinc-800">
      {cards.map((c) => {
        const p = c.selected;
        const sel = c.id === selectedId;
        const liquid = c.unit_price_usd !== null && c.unit_price_usd >= settings.bulk_cutoff_usd;
        const adj = adjustedValue(c, settings);
        return (
          <li
            key={c.id}
            ref={(el) => { if (el) rowRefs.current.set(c.id, el); else rowRefs.current.delete(c.id); }}
            onClick={() => { onSelect(c.id); onOpen(c.id); }}
            className={cx(
              "flex cursor-pointer items-center gap-3 px-3 py-2 transition-colors",
              sel ? "bg-amber-500/10" : "hover:bg-zinc-900",
              c.quantity === 0 && "opacity-40",
            )}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl(c.crop_url)} alt="" loading="lazy" className="h-[4.2rem] w-12 shrink-0 rounded object-cover ring-1 ring-zinc-700" />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-1.5">
                <span className="shrink-0 text-xs tabular-nums text-zinc-500">{pageNo(c.page_id)}·{c.slot}</span>
                <span className={cx("truncate font-medium", p ? "text-zinc-100" : "text-rose-300")}>{p ? p.name : c.status === "pending" ? "Scanning…" : "Unidentified"}</span>
                {c.quantity > 1 && <span className="text-xs text-zinc-400">×{c.quantity}</span>}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-400">
                {p && <span title={p.set_name ?? ""}>{p.set_code.toUpperCase()} #{p.collector_number}</span>}
                {p && (
                  <span className={cx(c.foil_detection === "uncertain" ? "text-amber-300" : c.finish !== "nonfoil" ? "text-fuchsia-300" : "")}>
                    {FINISH_LABEL[c.finish]}{c.foil_detection === "uncertain" ? "?" : ""}
                  </span>
                )}
                {p?.printed_name && p.printed_name !== p.name && <span className="truncate italic">{p.printed_name}</span>}
                {c.lang !== "en" && <Badge tone="sky">{LANG_LABEL[c.lang] ?? c.lang.toUpperCase()}</Badge>}
                {isWanted(c) && <Badge tone="emerald">★ Want</Badge>}
                {p && <TreatmentBadges treatments={p.treatments} max={2} />}
                {c.flags.includes("foil_price_inversion") && <Badge tone="rose" title="Non-foil price is higher than foil — check finish in person">usd&gt;foil</Badge>}
              </div>
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <span className={cx("tabular-nums", liquid ? "font-semibold text-emerald-300" : "text-zinc-400")}>{fmtUsd(c.unit_price_usd)}</span>
              {adj !== null && adj !== c.unit_price_usd && <span className="text-[11px] tabular-nums text-zinc-500">adj {fmtUsd(adj)}</span>}
              <StatusBadge card={c} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
