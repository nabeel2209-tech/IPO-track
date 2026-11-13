"""Response shapes for the API (what the front end receives)."""

from datetime import date

from pydantic import BaseModel


class IpoSummary(BaseModel):
    isin: str
    company: str
    segment: str
    nse_symbol: str | None
    bse_code: str | None
    listing_date: date
    issue_price: float
    lot_size: int
    min_investment: float  # cost of the smallest individual/retail application
    listing_close: float | None
    listing_return: float | None
    latest_date: date | None
    latest_adj_close: float | None
    latest_return: float | None


class IpoList(BaseModel):
    items: list[IpoSummary]
    total: int


class CategoryOut(BaseModel):
    key: str
    label: str
    eligibility: str
    min_lots: int
    max_lots: int | None
    shares: int
    buy_price: float
    amount: float


class Subscription(BaseModel):
    individual: float | None
    snii: float | None
    bnii: float | None
    qib: float | None
    total: float | None


class IpoDetail(BaseModel):
    isin: str
    company: str
    segment: str
    nse_symbol: str | None
    bse_code: str | None
    exchanges: str
    issue_open: date | None
    issue_close: date | None
    listing_date: date
    issue_price: float
    price_band_low: float | None
    price_band_high: float | None
    lot_size: int
    employee_discount: float
    categories: list[CategoryOut]
    subscription: Subscription
    first_price_date: date | None
    latest_price_date: date | None
    notes: str | None


class CategoryPnlOut(BaseModel):
    key: str
    lots: int
    shares: int
    invested: float
    value: float
    pnl: float
    pnl_pct: float


class DayPnlOut(BaseModel):
    requested: date
    trade_date: date
    close: float
    adj_close: float
    exchange: str
    categories: list[CategoryPnlOut]


class PnlOut(BaseModel):
    isin: str
    listing: DayPnlOut | None
    latest: DayPnlOut | None
    on_date: DayPnlOut | None


class PricePointOut(BaseModel):
    date: date
    close: float
    adj_close: float
    exchange: str


class CorporateActionOut(BaseModel):
    ex_date: date
    kind: str
    share_multiplier: float
    description: str | None


class PriceSeries(BaseModel):
    isin: str
    issue_price: float
    points: list[PricePointOut]
    corporate_actions: list[CorporateActionOut]


class Meta(BaseModel):
    ipo_count: int
    mainboard_count: int
    sme_count: int
    latest_price_date: date | None
    last_successful_ingest: date | None
    failed_days_last_30: int


class AskIn(BaseModel):
    question: str


class ToolCallOut(BaseModel):
    name: str
    input: dict


class AskOut(BaseModel):
    answer: str
    tool_calls: list[ToolCallOut]
