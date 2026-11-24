import type { CardRecord, WantItem } from "./types";

const KEY = "binderscan.wantlist.v1";

export function normalizeName(s: string | null | undefined): string {
  if (!s) return "";
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function loadLocalWantlist(): { text: string; items: WantItem[] } {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw) as { text: string; items: WantItem[] };
  } catch {
    /* storage unavailable */
  }
  return { text: "", items: [] };
}

export function saveLocalWantlist(text: string, items: WantItem[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ text, items }));
  } catch {
    /* ignore */
  }
}

export function wantMatcher(items: WantItem[]): (c: CardRecord) => boolean {
  const byName = new Map<string, WantItem[]>();
  for (const it of items) {
    const k = normalizeName(it.name);
    byName.set(k, [...(byName.get(k) ?? []), it]);
  }
  return (c: CardRecord) => {
    if (!c.selected) return false;
    const names = [c.selected.name, ...c.selected.name.split(" // "), c.selected.printed_name].map(normalizeName);
    for (const n of names) {
      const hits = byName.get(n);
      if (hits?.some((h) => !h.set_code || h.set_code === c.selected?.set_code)) return true;
    }
    return false;
  };
}
