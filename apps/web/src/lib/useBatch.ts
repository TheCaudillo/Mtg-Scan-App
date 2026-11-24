"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiBase } from "./api";
import type { BatchRecord, CardRecord, PageRecord } from "./types";

function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  const i = list.findIndex((x) => x.id === item.id);
  if (i === -1) return [...list, item];
  const next = list.slice();
  next[i] = item;
  return next;
}

function sortCards(cards: CardRecord[], pages: PageRecord[]): CardRecord[] {
  const order = new Map(pages.map((p) => [p.id, p.index]));
  return [...cards].sort((a, b) => (order.get(a.page_id) ?? 0) - (order.get(b.page_id) ?? 0) || a.slot - b.slot);
}

/** Loads a batch and keeps it live via Server-Sent Events (falls back to polling). */
export function useBatch(id: string | null) {
  const [batch, setBatch] = useState<BatchRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      setBatch(await api.getBatch(id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    void api
      .getBatch(id)
      .then((b) => {
        if (!cancelled) setBatch(b);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });

    const es = new EventSource(`${apiBase()}/api/batches/${id}/events`);
    es.addEventListener("hello", () => setLive(true));
    es.addEventListener("card", (ev) => {
      const card = JSON.parse((ev as MessageEvent<string>).data) as CardRecord;
      setBatch((b) => {
        if (!b) return b;
        // a re-scan replaces a page's cards: drop stale cards of that page with other ids at same slot
        const cards = b.cards.filter((c) => !(c.page_id === card.page_id && c.slot === card.slot && c.id !== card.id));
        return { ...b, cards: sortCards(upsert(cards, card), b.pages) };
      });
    });
    es.addEventListener("page", (ev) => {
      const page = JSON.parse((ev as MessageEvent<string>).data) as PageRecord;
      setBatch((b) => (b ? { ...b, pages: upsert(b.pages, page).sort((x, y) => x.index - y.index) } : b));
    });
    es.addEventListener("batch", (ev) => {
      const d = JSON.parse((ev as MessageEvent<string>).data) as { status: BatchRecord["status"] };
      setBatch((b) => (b ? { ...b, status: d.status } : b));
    });
    es.addEventListener("done", () => {
      void api.getBatch(id).then((b) => !cancelled && setBatch(b));
    });
    es.onerror = () => setLive(false);
    return () => {
      cancelled = true;
      es.close();
    };
  }, [id]);

  // polling fallback while scanning and SSE isn't connected
  useEffect(() => {
    const scanning = batch?.status === "scanning" || batch?.pages.some((p) => p.status === "detecting" || p.status === "matching");
    if (scanning && !live) {
      pollRef.current = setInterval(() => void refresh(), 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [batch?.status, batch?.pages, live, refresh]);

  const replaceCard = useCallback((card: CardRecord) => {
    setBatch((b) => (b ? { ...b, cards: sortCards(upsert(b.cards, card), b.pages) } : b));
  }, []);

  const addPages = useCallback((pages: PageRecord[]) => {
    setBatch((b) => (b ? { ...b, pages: [...b.pages, ...pages].sort((x, y) => x.index - y.index) } : b));
  }, []);

  return { batch, error, live, refresh, replaceCard, addPages, setBatch };
}
