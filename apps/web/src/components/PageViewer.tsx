"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { api, fileUrl } from "@/lib/api";
import type { CardRecord, GridSpec, PageRecord, Point } from "@/lib/types";
import { Button, cx } from "./ui";

type Mode = "view" | "boxes" | "grid";
type Drag = { kind: "box"; i: number; j: number } | { kind: "grid"; j: number } | null;

const STATUS_STROKE: Record<string, string> = {
  identified: "#34d399",
  needs_review: "#fbbf24",
  unidentified: "#fb7185",
  pending: "#a1a1aa",
  error: "#fb7185",
};

function lerp(a: Point, b: Point, t: number): Point {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function gridCells(c: Point[], rows: number, cols: number): Point[][] {
  const [tl, tr, br, bl] = c;
  const at = (u: number, v: number) => lerp(lerp(tl, tr, u), lerp(bl, br, u), v);
  const out: Point[][] = [];
  for (let r = 0; r < rows; r++)
    for (let k = 0; k < cols; k++)
      out.push([at(k / cols, r / rows), at((k + 1) / cols, r / rows), at((k + 1) / cols, (r + 1) / rows), at(k / cols, (r + 1) / rows)]);
  return out;
}

const pts = (q: Point[]) => q.map((p) => `${p.x},${p.y}`).join(" ");

export function PageViewer({ page, cards, selectedId, onSelect, batchId, busy }: {
  page: PageRecord;
  cards: CardRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  batchId: string;
  busy: boolean;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [mode, setMode] = useState<Mode>("view");
  const [boxes, setBoxes] = useState<Point[][]>([]);
  const [grid, setGrid] = useState<GridSpec | null>(null);
  const [drag, setDrag] = useState<Drag>(null);
  const [err, setErr] = useState<string | null>(null);
  const detectionFailed = (page.message ?? "").includes("uniform_grid");
  const w = page.width || 1000;
  const h = page.height || 1000;
  const handleR = Math.max(w, h) * 0.014;

  const toSvg = useCallback((e: ReactPointerEvent) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const m = svg.getScreenCTM();
    if (!m) return { x: 0, y: 0 };
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return { x: Math.max(0, Math.min(w, p.x)), y: Math.max(0, Math.min(h, p.y)) };
  }, [w, h]);

  async function startBoxes() {
    setErr(null);
    try {
      const prev = await api.detect(batchId, page.id);
      setBoxes(prev.quads);
      setMode("boxes");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  function startGrid() {
    const cb = page.content_box ?? [0, 0, w, h];
    // only trust existing boxes if the detector actually found card edges
    const all = detectionFailed ? [] : cards.flatMap((c) => c.quad);
    let corners: Point[];
    if (all.length >= 8) {
      const xs = all.map((p) => p.x), ys = all.map((p) => p.y);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      corners = [{ x: x0, y: y0 }, { x: x1, y: y0 }, { x: x1, y: y1 }, { x: x0, y: y1 }];
    } else {
      const [x, y, cw, ch] = cb;
      const m = 0.05;
      corners = [
        { x: x + cw * m, y: y + ch * m }, { x: x + cw * (1 - m), y: y + ch * m },
        { x: x + cw * (1 - m), y: y + ch * (1 - m) }, { x: x + cw * m, y: y + ch * (1 - m) },
      ];
    }
    setGrid(page.manual_grid ?? { corners, rows: 3, cols: 3 });
    setMode("grid");
  }

  async function scanWith() {
    setErr(null);
    try {
      if (mode === "boxes") await api.scan(batchId, { page_ids: [page.id], rescan: true, boxes: { [page.id]: { quads: boxes } } });
      else if (mode === "grid" && grid) await api.scan(batchId, { page_ids: [page.id], rescan: true, grids: { [page.id]: grid } });
      setMode("view");
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  function onMove(e: ReactPointerEvent) {
    if (!drag) return;
    const p = toSvg(e);
    if (drag.kind === "box") setBoxes((bs) => bs.map((q, i) => (i === drag.i ? q.map((pt, j) => (j === drag.j ? p : pt)) : q)));
    else setGrid((g) => (g ? { ...g, corners: g.corners.map((pt, j) => (j === drag.j ? p : pt)) } : g));
  }

  function addBox() {
    const ref = boxes[0];
    const bw = ref ? Math.abs(ref[1].x - ref[0].x) : w / 4;
    const bh = ref ? Math.abs(ref[3].y - ref[0].y) : h / 4;
    const cx0 = w / 2 - bw / 2, cy0 = h / 2 - bh / 2;
    setBoxes((bs) => [...bs, [{ x: cx0, y: cy0 }, { x: cx0 + bw, y: cy0 }, { x: cx0 + bw, y: cy0 + bh }, { x: cx0, y: cy0 + bh }]]);
  }

  const cells = useMemo(() => (grid ? gridCells(grid.corners, grid.rows, grid.cols) : []), [grid]);
  const scanning = page.status === "detecting" || page.status === "matching";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-zinc-200">Page {page.index + 1}</span>
        <span className="truncate text-zinc-500">{page.filename}</span>
        {page.chrome_cropped && <span className="text-sky-300" title="Phone screenshot UI bars were removed">screenshot UI stripped</span>}
        {page.message && <span className="text-zinc-500">· {page.message}</span>}
        <span className="ml-auto flex gap-1">
          {mode === "view" ? (
            <>
              <Button variant="ghost" className="min-h-7 px-2 text-xs" onClick={startBoxes} disabled={busy || scanning} title="Review/adjust detected card boxes before (re)scanning">
                Adjust boxes
              </Button>
              <Button variant="ghost" className="min-h-7 px-2 text-xs" onClick={startGrid} disabled={busy || scanning} title="Place a manual grid for heavily angled photos">
                Grid overlay
              </Button>
            </>
          ) : (
            <>
              {mode === "boxes" && <Button className="min-h-7 px-2 text-xs" onClick={addBox}>+ Box</Button>}
              {mode === "grid" && grid && (
                <>
                  <select aria-label="rows" value={grid.rows} onChange={(e) => setGrid({ ...grid, rows: Number(e.target.value) })} className="rounded bg-zinc-800 px-1 text-xs">
                    {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} rows</option>)}
                  </select>
                  <select aria-label="cols" value={grid.cols} onChange={(e) => setGrid({ ...grid, cols: Number(e.target.value) })} className="rounded bg-zinc-800 px-1 text-xs">
                    {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} cols</option>)}
                  </select>
                </>
              )}
              <Button variant="primary" className="min-h-7 px-2 text-xs" onClick={scanWith}>Scan with {mode}</Button>
              <Button variant="ghost" className="min-h-7 px-2 text-xs" onClick={() => setMode("view")}>Cancel</Button>
            </>
          )}
        </span>
      </div>
      {err && <div className="text-xs text-rose-400">{err}</div>}
      {detectionFailed && mode === "view" && page.status === "done" && (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-amber-500/10 p-2 text-sm text-amber-200 ring-1 ring-amber-500/40">
          <span className="flex-1">
            Couldn&apos;t find the card edges in this photo, so these boxes are a guess and the results are unreliable.
            Use <b>Grid overlay</b>: drag the 4 yellow corners onto the outer corners of the cards, set rows × columns, then <b>Scan with grid</b>.
          </span>
          <Button variant="primary" className="min-h-8 text-xs" onClick={startGrid}>Place grid</Button>
        </div>
      )}
      {mode === "grid" && (
        <div className="rounded-md bg-zinc-900 p-2 text-xs text-zinc-300 ring-1 ring-zinc-700">
          Drag the 4 yellow corner dots to the <b>outer corners of the card area</b> (top-left card&apos;s top-left corner, etc.). Only cover full pockets on this page, not cards peeking from the next page.
        </div>
      )}
      {scanning && (
        <div className="h-1 overflow-hidden rounded bg-zinc-800">
          <div className="h-full bg-amber-400 transition-all" style={{ width: `${Math.max(5, page.progress * 100)}%` }} />
        </div>
      )}
      <div className="relative overflow-hidden rounded-lg bg-zinc-900 ring-1 ring-zinc-800">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={fileUrl(page.image_url)} alt={`Binder page ${page.index + 1}`} className="block h-auto w-full select-none" draggable={false} />
        <svg
          ref={svgRef}
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          className={cx("absolute inset-0 h-full w-full", mode !== "view" && "touch-none")}
          onPointerMove={onMove}
          onPointerUp={() => setDrag(null)}
          onPointerLeave={() => setDrag(null)}
        >
          {mode === "view" &&
            cards.map((c) => {
              const sel = c.id === selectedId;
              const stroke = STATUS_STROKE[c.user_verified ? "identified" : c.status] ?? "#a1a1aa";
              const cxp = c.quad.reduce((a, p) => a + p.x, 0) / 4;
              const cyp = c.quad.reduce((a, p) => a + p.y, 0) / 4;
              return (
                <g key={c.id} onClick={() => onSelect(c.id)} className="cursor-pointer">
                  <polygon points={pts(c.quad)} fill={sel ? "rgba(251,191,36,0.22)" : "rgba(0,0,0,0.001)"} stroke={sel ? "#fbbf24" : stroke} strokeWidth={sel ? handleR * 0.6 : handleR * 0.3} />
                  <circle cx={cxp} cy={cyp} r={handleR * 1.6} fill="rgba(9,9,11,0.8)" stroke={stroke} strokeWidth={handleR * 0.2} />
                  <text x={cxp} y={cyp} fill="#fafafa" fontSize={handleR * 1.7} textAnchor="middle" dominantBaseline="central" fontWeight={700}>
                    {c.slot}
                  </text>
                </g>
              );
            })}
          {mode === "boxes" &&
            boxes.map((q, i) => (
              <g key={i}>
                <polygon points={pts(q)} fill="rgba(56,189,248,0.12)" stroke="#38bdf8" strokeWidth={handleR * 0.3} />
                {q.map((p, j) => (
                  <circle key={j} cx={p.x} cy={p.y} r={handleR} fill="#38bdf8" stroke="#082f49" strokeWidth={handleR * 0.2}
                    className="cursor-grab"
                    onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag({ kind: "box", i, j }); }} />
                ))}
                <g className="cursor-pointer" onClick={() => setBoxes((bs) => bs.filter((_, k) => k !== i))}>
                  <circle cx={(q[0].x + q[2].x) / 2} cy={(q[0].y + q[2].y) / 2} r={handleR * 1.3} fill="#e11d48" />
                  <text x={(q[0].x + q[2].x) / 2} y={(q[0].y + q[2].y) / 2} fontSize={handleR * 1.8} fill="#fff" textAnchor="middle" dominantBaseline="central">×</text>
                </g>
              </g>
            ))}
          {mode === "grid" && grid && (
            <g>
              {cells.map((q, i) => <polygon key={i} points={pts(q)} fill="rgba(251,191,36,0.08)" stroke="#fbbf24" strokeWidth={handleR * 0.25} />)}
              {grid.corners.map((p, j) => (
                <circle key={j} cx={p.x} cy={p.y} r={handleR * 1.3} fill="#fbbf24" stroke="#451a03" strokeWidth={handleR * 0.25} className="cursor-grab"
                  onPointerDown={(e) => { (e.target as Element).setPointerCapture?.(e.pointerId); setDrag({ kind: "grid", j }); }} />
              ))}
            </g>
          )}
        </svg>
      </div>
    </div>
  );
}
