import type {
  BatchListItem,
  BatchRecord,
  CardRecord,
  DetectPreview,
  Finish,
  GridSpec,
  Health,
  PageRecord,
  Point,
  Printing,
  WantItem,
} from "./types";

/** Scanner API base. Defaults to the same host on :8000 so a phone on your LAN just works. */
export function apiBase(): string {
  const env = process.env.NEXT_PUBLIC_API_BASE;
  if (env) return env.replace(/\/$/, "");
  if (typeof window === "undefined") return "http://localhost:8000";
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

export function fileUrl(path: string | null | undefined): string {
  if (!path) return "";
  return path.startsWith("http") ? path : `${apiBase()}${path}`;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) detail = String((body as { detail: unknown }).detail);
    } catch {
      /* not json */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => req<Health>("/api/health"),
  listBatches: () => req<BatchListItem[]>("/api/batches"),
  createBatch: (name?: string) => req<BatchRecord>("/api/batches", { method: "POST", body: JSON.stringify({ name }) }),
  getBatch: (id: string) => req<BatchRecord>(`/api/batches/${id}`),
  deleteBatch: (id: string) => req<{ deleted: string }>(`/api/batches/${id}`, { method: "DELETE" }),
  uploadPages: (id: string, files: Blob[], names: string[]) => {
    const fd = new FormData();
    files.forEach((f, i) => fd.append("files", f, names[i]));
    return req<PageRecord[]>(`/api/batches/${id}/pages`, { method: "POST", body: fd });
  },
  deletePage: (id: string, pageId: string) =>
    req<{ deleted: string }>(`/api/batches/${id}/pages/${pageId}`, { method: "DELETE" }),
  detect: (id: string, pageId: string, grid?: GridSpec) =>
    req<DetectPreview>(`/api/batches/${id}/pages/${pageId}/detect`, {
      method: "POST",
      body: JSON.stringify(grid ? { grid } : {}),
    }),
  scan: (
    id: string,
    opts: { page_ids?: string[]; rescan?: boolean; grids?: Record<string, GridSpec>; boxes?: Record<string, { quads: Point[][] }> } = {},
  ) => req<{ queued: number }>(`/api/batches/${id}/scan`, { method: "POST", body: JSON.stringify(opts) }),
  patchCard: (
    cardId: string,
    patch: Partial<{ scryfall_id: string; finish: Finish; lang: string; quantity: number; user_verified: boolean }>,
  ) => req<CardRecord>(`/api/cards/${cardId}`, { method: "PATCH", body: JSON.stringify(patch) }),
  search: (q: string) => req<Printing[]>(`/api/search?q=${encodeURIComponent(q)}`),
  alternatives: (scryfallId: string) => req<Printing[]>(`/api/printings/${scryfallId}/alternatives`),
  getWantlist: () => req<{ items: WantItem[] }>("/api/wantlist"),
  putWantlist: (text: string) =>
    req<{ items: WantItem[] }>("/api/wantlist", { method: "PUT", body: JSON.stringify({ text }) }),
  exportUrl: (id: string, format: "csv" | "manabox" | "moxfield" | "markdown", params: Record<string, string>) =>
    `${apiBase()}/api/batches/${id}/export?${new URLSearchParams({ format, ...params }).toString()}`,
};

/** Downscale big phone photos in the browser before upload (EXIF orientation applied). */
export async function prepareUpload(file: File, maxSide = 3200): Promise<Blob> {
  if (!file.type.startsWith("image/") || file.size < 2_500_000 || typeof createImageBitmap === "undefined") return file;
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 6_000_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d")?.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.92));
    return blob ?? file;
  } catch {
    return file;
  }
}
