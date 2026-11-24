# BinderScan MTG

Scan multi-card Magic: The Gathering binder photos (angled phone shots, WhatsApp sale screenshots),
identify each card's **exact printing** against a local Scryfall mirror, evaluate whether the lot is worth
buying, and export clean CSVs.

```
apps/web            Next.js 16 (App Router, TS strict, Tailwind 4) — mobile-first, PWA-installable
services/scanner    FastAPI + OpenCV + SQLite + OpenCLIP/FAISS + Tesseract + pluggable vision LLM
scripts/            sync_scryfall.py · build_art_index.py · test_scan.py · make_synthetic_binder.py
data/               scryfall.db, app.db, art_index/, uploads/  (gitignored)
```

## Quick start

Prerequisites: Python 3.11+, Node 20+, and optionally `tesseract` (`brew install tesseract` /
`sudo apt install tesseract-ocr`) for free local collector-number reading.

```bash
make setup          # pip deps + npm install, creates .env
make sync           # Scryfall default_cards → data/scryfall.db (~110k printings, ~20 s)
make setup-ml       # OpenCLIP + FAISS (CPU is fine)
make index-quick    # art index for printings since 2023 (~10 min) — or `make index` for all (~30-60 min)
make dev            # API on :8000, web on :3000 → open http://localhost:3000
```

Try it on one photo from the terminal first:

```bash
make scan IMG=~/Downloads/binder_page.jpg      # prints every slot + writes binder_page.jpg_annotated.jpg
```

**From your phone:** `make dev-lan`, then open `http://<your-computer-LAN-IP>:3000` on the phone
(same Wi-Fi). The "📷 Camera" button opens the rear camera; it can be added to the home screen as an app.

### Recognition modes (`MATCHER_MODE` in `.env`)

| Mode | What runs | Needs |
|---|---|---|
| `auto` (default) | local art index + strip OCR; vision LLM only for cards that remain ambiguous | index built; LLM key optional |
| `clip` | art index + OCR only, fully offline | index built |
| `vision` | vision LLM on every card ("Day-1" mode, no index needed) + OCR | `VISION_PROVIDER` + key |

Vision LLM: set `VISION_PROVIDER=anthropic|openai|gemini` and the matching `*_API_KEY`. `VISION_MODEL`
overrides the default fast model per provider. Requests run with `VISION_CONCURRENCY` (default 6).

**Nothing the models say is trusted.** Every read (set code, collector number, name) is validated
against `scryfall.db`; only printings that exist there are ever returned, and prices come only from
Scryfall (`N/A` when Scryfall has none).

## How it works

1. **Scryfall mirror** (`scanner/scryfall_sync.py`) — streams the official bulk file (current gzipped
   JSONL API, legacy JSON also supported) into SQLite/WAL with indexes on name, (set, collector #),
   illustration_id and oracle_id. Lookups take < 2 ms.
   - `make prices` refreshes only price columns (daily).
   - `make sync-es` ingests Spanish printings from `all_cards` so Spanish printed names match directly.
     Without it, Spanish cards are still matched by artwork/set/number and priced from the English
     printing with the same set + collector number (`price_source = english_equivalent`).
2. **Detection** (`scanner/detect/`, `CardDetector` interface) — `OpenCVBinderDetector`: strips phone
   screenshot chrome, finds card quads from several edge/threshold maps, keeps the dominant size and
   orientation cluster, drops nested boxes and partial cards cut by the left/right edge (adjacent page),
   fills holes in the rows×cols lattice, falls back to a uniform 3×3. Each card is deskewed and cut into
   art box, glare-normalised zoomed collector strip, set symbol and name bar.
   `YOLO11CardDetector` is stubbed: set `DETECTOR=yolo11` + `YOLO_WEIGHTS` when you have a model.
   In the UI, **Adjust boxes** (drag corners, delete/add) or **Grid overlay** (4 corners + rows/cols)
   re-scan a heavily angled page.
3. **Matching** (`scanner/match/`) — `ClipFaissIndex` (OpenCLIP ViT-B-32 on Scryfall art crops, one
   vector per artwork, language-agnostic), `TesseractStripReader` (reads `010/277 C · MID • EN`),
   `VisionLLMReader` (strict JSON read + targeted "which of these printings" disambiguation).
4. **Resolver** (`scanner/match/resolver.py`) — merges evidence, expands every same-art reprint from
   SQLite, ranks, and either resolves or returns 2–4 candidates with `needs_review` and reasons:
   `same_art_reprint`, `collector_number_unreadable`, `glare_over_finish`, `foil_price_inversion`,
   `visual_text_conflict`, `low_confidence`. Visual confidence uses the top-1 vs top-2 margin, not just
   raw similarity (wrong CLIP matches cluster tightly).
5. **Radar** (`scanner/radar.py`) — treatments (Extended Art, Borderless, Showcase, Retro Frame, White
   Border, Full Art, Surge Foil, Secret Lair, Promo, Mythic…), foil detection (`foil` only when ★, clear
   sheen or foil-only printing; `nonfoil` only with a clear • or non-foil-only printing; else
   `uncertain` and priced at the lower finish), and `usd > usd_foil` inversion flags.

### Lot calculator

Retail = Σ unit price × qty. Cards ≥ bulk cutoff are **liquid**. Adjusted value applies the condition
preset (NM 100 / LP 85 / MP 70 / HP 50 %) and the non-English discount (non-EN cards only).
**Max offer = target buy rate × adjusted liquid value** (bulk is treated as a free bonus).
Verdict: asking ≤ max offer → *Good Deal*; ≤ 115 % of it → *Borderline*; else *Pass*. MXN asking prices
convert with the editable rate. Same math in `scanner/lot.py` and `apps/web/src/lib/lot.ts`.

### Exports

Detailed CSV (Page, Slot, English/Printed name, Language, Set, Collector #, Rarity, Finish, Treatment,
prices, Adjusted Value, Confidence, Scryfall URL), ManaBox CSV, Moxfield CSV, and a copyable Markdown table.

## API

`GET /api/health` · `POST/GET /api/batches` · `GET/DELETE /api/batches/{id}` ·
`POST /api/batches/{id}/pages` (multipart `files`) · `POST /api/batches/{id}/pages/{page}/detect` ·
`POST /api/batches/{id}/scan` (`grids` / `boxes` overrides) · `GET /api/batches/{id}/events` (SSE) ·
`PATCH /api/cards/{id}` (`scryfall_id`, `finish`, `lang`, `quantity`, `user_verified`) ·
`GET /api/search?q=` · `GET /api/printings/{id}/alternatives` · `POST /api/batches/{id}/summary` ·
`GET /api/batches/{id}/export?format=csv|manabox|moxfield|markdown` · `GET/PUT /api/wantlist`.
Interactive docs at http://localhost:8000/docs.

## Tests

```bash
make test     # pytest: Scryfall ingest/validation, Spanish pricing, foil inversion, lot math,
              # detector on synthetic binder photos, OCR parsing, exports, full API flow
make build    # eslint + next build (TypeScript strict)
make fixtures # regenerate synthetic binder test photos from real Scryfall images
```

## Measured on the synthetic fixtures (full 50k-artwork index, CPU only, no LLM key)

| Photo | Right card | Exact printing | Exact printing among candidates | Time |
|---|---|---|---|---|
| Straight-on page | 9/9 | 8/9 | 9/9 | ~1.2 s |
| Angled + glare | 9/9 | 8/9 | 9/9 | ~1.3 s |
| WhatsApp screenshot | 9/9 | 6/9 | 8/9 | ~1.0 s |

Every wrong printing was flagged for review. These are synthetic composites of real Scryfall images
(`make fixtures`); real phone photos of sleeved cards will be harder. Please report misses.

## Known limitations

- Strip OCR needs resolution: at WhatsApp-screenshot resolution collector numbers are often unreadable,
  so same-art reprints come back as review candidates. A vision LLM key or a closer photo resolves them.
- Collector-strip OCR targets the modern (2015+) frame. Older frames put the number elsewhere, so
  those cards fall back to artwork + review candidates (e.g. M11 Lightning Bolt vs its reprints).
- The art index stores one standard-frame representative per artwork; borderless / extended-art
  versions are recognised by artwork and then disambiguated among printings.
- Detection is heuristic. Very glare-heavy pages or non-grid layouts may need the Grid overlay.
