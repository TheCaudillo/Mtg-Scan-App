// Mirrors services/scanner/scanner/models.py (Pydantic v2)

export type Finish = "nonfoil" | "foil" | "etched";
export type FoilDetection = Finish | "uncertain";
export type CardStatus = "pending" | "identified" | "needs_review" | "unidentified" | "error";
export type Currency = "USD" | "MXN";
export type ConditionLabel = "NM" | "LP" | "MP" | "HP";
export type Verdict = "good" | "borderline" | "pass" | "n/a";

export interface Point {
  x: number;
  y: number;
}

export interface Printing {
  scryfall_id: string;
  oracle_id: string | null;
  illustration_id: string | null;
  name: string;
  printed_name: string | null;
  lang: string;
  set_code: string;
  set_name: string | null;
  collector_number: string;
  rarity: string | null;
  released_at: string | null;
  border_color: string | null;
  frame: string | null;
  frame_effects: string[];
  promo_types: string[];
  finishes: string[];
  treatments: string[];
  type_line: string | null;
  oracle_text: string | null;
  flavor_text: string | null;
  artist: string | null;
  usd: number | null;
  usd_foil: number | null;
  usd_etched: number | null;
  price_inversion: boolean;
  scryfall_uri: string | null;
  image_normal: string | null;
  image_small: string | null;
  image_art_crop: string | null;
  score: number;
}

export interface VisionRead {
  name: string | null;
  printed_name: string | null;
  language: string | null;
  set_code: string | null;
  collector_number: string | null;
  rarity_letter: string | null;
  foil_symbol: "dot" | "star" | "none" | "unclear" | null;
  foil_sheen: "clear" | "none" | "unclear" | null;
  border: string | null;
  frame_cues: string[];
  text_snippet: string | null;
  is_card: boolean;
  confidence: number | null;
  source: string;
}

export interface CardRecord {
  id: string;
  batch_id: string;
  page_id: string;
  slot: number;
  row: number;
  col: number;
  quad: Point[];
  crop_url: string | null;
  art_url: string | null;
  strip_url: string | null;
  status: CardStatus;
  needs_review: boolean;
  review_reasons: string[];
  confidence: number;
  match_method: string | null;
  observed: VisionRead | null;
  selected: Printing | null;
  candidates: Printing[];
  lang: string;
  foil_detection: FoilDetection;
  finish: Finish;
  quantity: number;
  unit_price_usd: number | null;
  price_source: "scryfall" | "english_equivalent" | null;
  flags: string[];
  user_verified: boolean;
  error: string | null;
  updated_at: string;
}

export interface GridSpec {
  corners: Point[];
  rows: number;
  cols: number;
}

export interface PageRecord {
  id: string;
  batch_id: string;
  index: number;
  filename: string;
  image_url: string;
  width: number;
  height: number;
  status: "uploaded" | "detecting" | "matching" | "done" | "error";
  progress: number;
  message: string | null;
  chrome_cropped: boolean;
  content_box: number[] | null;
  card_count: number;
  manual_grid: GridSpec | null;
}

export interface BatchRecord {
  id: string;
  name: string;
  created_at: string;
  status: "new" | "scanning" | "done" | "error";
  pages: PageRecord[];
  cards: CardRecord[];
}

export interface BatchListItem {
  id: string;
  name: string;
  created_at: string;
  status: string;
  pages: number;
  cards: number;
}

export interface DetectPreview {
  method: string;
  chrome_cropped: boolean;
  content_box: number[];
  quads: Point[][];
}

export interface WantItem {
  name: string;
  set_code: string | null;
  quantity: number;
}

export interface Health {
  ok: boolean;
  printings: number;
  sync: Record<string, string>;
  matcher: { mode: string; visual_index: string | null; ocr: string | null; vision: string | null };
}

export interface LotSettings {
  asking_price: number | null;
  currency: Currency;
  fx_rate_mxn_per_usd: number;
  bulk_cutoff_usd: number;
  condition_label: ConditionLabel;
  condition_pct: number;
  non_english_discount_pct: number;
  target_buy_rate_pct: number;
}

export interface LotSummary {
  total_cards: number;
  priced_cards: number;
  unpriced_cards: number;
  liquid_cards: number;
  bulk_cards: number;
  retail_total_usd: number;
  liquid_total_usd: number;
  bulk_total_usd: number;
  adjusted_liquid_usd: number;
  adjusted_bulk_usd: number;
  adjusted_lot_value_usd: number;
  suggested_max_offer_usd: number;
  asking_price_usd: number | null;
  estimated_margin_usd: number | null;
  estimated_margin_pct: number | null;
  verdict: Verdict;
}
