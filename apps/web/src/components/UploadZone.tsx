"use client";

import { useRef, useState } from "react";
import { cx } from "./ui";

export function UploadZone({ onFiles, busy, compact }: { onFiles: (files: File[]) => void; busy: boolean; compact?: boolean }) {
  const [over, setOver] = useState(false);
  const pick = useRef<HTMLInputElement>(null);
  const cam = useRef<HTMLInputElement>(null);
  const take = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => f.type.startsWith("image/") || /\.(heic|heif)$/i.test(f.name));
    if (files.length) onFiles(files);
  };
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files); }}
      className={cx(
        "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed text-center transition-colors",
        compact ? "p-3 sm:flex-row" : "p-8",
        over ? "border-amber-400 bg-amber-400/5" : "border-zinc-700 bg-zinc-900/40",
      )}
    >
      {!compact && (
        <div>
          <div className="text-base font-medium text-zinc-100">Drop binder pages, photos or WhatsApp screenshots</div>
          <div className="mt-1 text-sm text-zinc-500">Multiple pages per lot · JPG / PNG / WebP / HEIC</div>
        </div>
      )}
      <div className="flex flex-wrap justify-center gap-2">
        <button disabled={busy} onClick={() => pick.current?.click()} className="rounded-md bg-amber-500 px-4 py-2 text-sm font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-50">
          {busy ? "Uploading…" : compact ? "+ Add pages" : "Choose photos"}
        </button>
        <button disabled={busy} onClick={() => cam.current?.click()} className="rounded-md bg-zinc-800 px-4 py-2 text-sm text-zinc-100 ring-1 ring-zinc-700 hover:bg-zinc-700 disabled:opacity-50 sm:hidden">
          📷 Camera
        </button>
      </div>
      <input ref={pick} type="file" accept="image/*,.heic,.heif" multiple hidden onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
      <input ref={cam} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { take(e.target.files); e.target.value = ""; }} />
    </div>
  );
}
