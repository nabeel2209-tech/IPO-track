// Shapes returned by the FastAPI backend (see backend/app/schemas.py).

export type Segment = "mainboard" | "sme";

export interface IpoSummary {
  isin: string;
  company: string;
  segment: Segment;
  nse_symbol: string | null;
  bse_code: string | null;
  listing_date: string;
  issue_price: number;
  lot_size: number;
  min_investment: number;
  listing_close: number | null;
  listing_return: number | null;
  latest_date: string | null;
  latest_adj_close: number | null;
  latest_return: number | null;
}

export interface IpoList {
  items: IpoSummary[];
  total: number;
}

export interface Category {
  key: string;
  label: string;
  eligibility: string;
  min_lots: number;
  max_lots: number | null;
  shares: number;
  buy_price: number;
  amount: number;
}

export interface IpoDetail {
  isin: string;
  company: string;
  segment: Segment;
  nse_symbol: string | null;
  bse_code: string | null;
  exchanges: string;
  issue_open: string | null;
  issue_close: string | null;
  listing_date: string;
  issue_price: number;
  price_band_low: number | null;
  price_band_high: number | null;
  lot_size: number;
  employee_discount: number;
  categories: Category[];
  subscription: { individual: number | null; snii: number | null; bnii: number | null; qib: number | null; total: number | null };
  first_price_date: string | null;
  latest_price_date: string | null;
  notes: string | null;
}

export interface CategoryPnl {
  key: string;
  lots: number;
  shares: number;
  invested: number;
  value: number;
  pnl: number;
  pnl_pct: number;
}

export interface DayPnl {
  requested: string;
  trade_date: string;
  close: number;
  adj_close: number;
  exchange: string;
  categories: CategoryPnl[];
}

export interface Pnl {
  isin: string;
  listing: DayPnl | null;
  latest: DayPnl | null;
  on_date: DayPnl | null;
}

export interface PricePoint {
  date: string;
  close: number;
  adj_close: number;
  exchange: string;
}

export interface PriceSeries {
  isin: string;
  issue_price: number;
  points: PricePoint[];
  corporate_actions: { ex_date: string; kind: string; share_multiplier: number; description: string | null }[];
}

export interface Meta {
  ipo_count: number;
  mainboard_count: number;
  sme_count: number;
  latest_price_date: string | null;
  last_successful_ingest: string | null;
  failed_days_last_30: number;
}

export interface AskAnswer {
  answer: string;
  tool_calls: { name: string; input: Record<string, unknown> }[];
}
