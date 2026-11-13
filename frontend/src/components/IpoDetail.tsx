import { Suspense, lazy, useEffect, useState } from "react";
import { api } from "../api";
import { addDays, count, longDate, pct, rupees, rupees2, signedRupees, tone } from "../format";
import type { CategoryPnl, DayPnl, IpoDetail, Pnl, PriceSeries } from "../types";
import { replaceParams } from "../useRoute";

// The charting library is the biggest dependency, so it loads only when a chart is shown.
const PriceChart = lazy(() => import("./PriceChart"));

function byKey(day: DayPnl | null): Record<string, CategoryPnl> {
  return Object.fromEntries((day?.categories ?? []).map((c) => [c.key, c]));
}

function PnlCell({ c, label }: { c?: CategoryPnl; label: string }) {
  if (!c)
    return (
      <td className="num muted" data-label={label}>
        —
      </td>
    );
  return (
    <td className={"num " + tone(c.pnl)} data-label={label}>
      <div>{signedRupees(c.pnl)}</div>
      <div className="small">{pct(c.pnl_pct)}</div>
    </td>
  );
}

export default function IpoDetailView({ isin, date }: { isin: string; date?: string }) {
  const [detail, setDetail] = useState<IpoDetail | null>(null);
  const [series, setSeries] = useState<PriceSeries | null>(null);
  const [pnl, setPnl] = useState<Pnl | null>(null);
  const [picked, setPicked] = useState<string | undefined>(date);
  const [error, setError] = useState<string | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setSeries(null);
    Promise.all([api.detail(isin), api.prices(isin)])
      .then(([d, s]) => {
        setDetail(d);
        setSeries(s);
      })
      .catch((e) => setError(e.message));
  }, [isin]);

  useEffect(() => {
    replaceParams(`/ipo/${isin}`, { date: picked });
    api
      .pnl(isin, picked)
      .then((p) => {
        setPnl(p);
        setDateError(null);
      })
      .catch((e) => setDateError(e.message));
  }, [isin, picked]);

  if (error) return <p className="error">Couldn't load this IPO: {error}</p>;
  if (!detail || !series) return <p className="muted">Loading…</p>;

  const listing = byKey(pnl?.listing ?? null);
  const latest = byKey(pnl?.latest ?? null);
  const onDate = byKey(pnl?.on_date ?? null);
  const latestDate = detail.latest_price_date ?? undefined;
  const quick: [string, string | undefined][] = [
    ["Listing day", detail.listing_date],
    ["+1 week", addDays(detail.listing_date, 7)],
    ["+1 month", addDays(detail.listing_date, 30)],
    ["+3 months", addDays(detail.listing_date, 91)],
    ["+6 months", addDays(detail.listing_date, 182)],
  ];
  const listingGain = pnl?.listing ? pnl.listing.adj_close / detail.issue_price - 1 : null;
  const latestGain = pnl?.latest ? pnl.latest.adj_close / detail.issue_price - 1 : null;

  return (
    <section>
      <a className="back" href="#/">
        Back to all IPOs
      </a>
      <div className="detail-head">
        <h1>{detail.company}</h1>
        <div className="meta-line">
          <span className={"badge " + detail.segment}>{detail.segment === "sme" ? "SME" : "Mainboard"}</span>
          <span>{detail.nse_symbol ?? detail.bse_code}</span>
          <span>Trades on {detail.exchanges.replace(",", " and ")}</span>
          <span>Listed {longDate(detail.listing_date)}</span>
          {detail.issue_open && (
            <span>
              Open for bids {longDate(detail.issue_open)} to {longDate(detail.issue_close)}
            </span>
          )}
        </div>
      </div>

      <div className="stats">
        <div className="stat">
          <span className="label">Issue price</span>
          <span className="value">{rupees2(detail.issue_price)}</span>
          <span className="sub">
            {detail.price_band_low && detail.price_band_high && detail.price_band_low !== detail.price_band_high
              ? `Band ${rupees2(detail.price_band_low)} – ${rupees2(detail.price_band_high)}`
              : "Fixed price"}
          </span>
        </div>
        <div className="stat">
          <span className="label">Lot size</span>
          <span className="value">{count(detail.lot_size)} shares</span>
          <span className="sub">{rupees(detail.lot_size * detail.issue_price)} per lot</span>
        </div>
        <div className="stat">
          <span className="label">Listing-day close</span>
          <span className={"value " + tone(listingGain)}>{pnl?.listing ? rupees2(pnl.listing.close) : "—"}</span>
          <span className={"sub " + tone(listingGain)}>{pct(listingGain)} vs issue</span>
        </div>
        <div className="stat">
          <span className="label">Latest close</span>
          <span className={"value " + tone(latestGain)}>{pnl?.latest ? rupees2(pnl.latest.adj_close) : "—"}</span>
          <span className={"sub " + tone(latestGain)}>
            {pct(latestGain)} vs issue, on {longDate(pnl?.latest?.trade_date)}
          </span>
          {pnl?.latest && Math.abs(pnl.latest.adj_close - pnl.latest.close) > 0.005 && (
            <span className="sub">Trades at {rupees2(pnl.latest.close)} after a split or bonus; shown per original share</span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Profit or loss by investor category</h2>
          <div className="date-picker">
            <label htmlFor="pick">Also show profit on</label>
            <input
              id="pick"
              type="date"
              min={detail.listing_date}
              max={latestDate}
              value={picked ?? ""}
              onChange={(e) => setPicked(e.target.value || undefined)}
            />
            {picked && (
              <button className="link" onClick={() => setPicked(undefined)}>
                Clear
              </button>
            )}
          </div>
        </div>
        <div className="chips">
          {quick
            .filter(([, d]) => d && (!latestDate || d <= latestDate))
            .map(([label, d]) => (
              <button key={label} className="chip" aria-pressed={picked === d} onClick={() => setPicked(d)}>
                {label}
              </button>
            ))}
        </div>
        {dateError && <p className="error small">{dateError}</p>}
        {pnl?.on_date && pnl.on_date.trade_date !== pnl.on_date.requested && (
          <p className="muted small">
            {longDate(pnl.on_date.requested)} was not a trading day, so the close on {longDate(pnl.on_date.trade_date)} is used.
          </p>
        )}

        <div className="table-wrap">
          <table className="cat-table">
            <thead>
              <tr>
                <th>Category</th>
                <th className="num">Minimum application</th>
                <th className="num">Amount</th>
                <th className="num">Listing day</th>
                <th className="num">Today</th>
                <th className={"num " + (pnl?.on_date ? "" : "muted")}>{pnl?.on_date ? longDate(pnl.on_date.trade_date) : "Chosen date"}</th>
              </tr>
            </thead>
            <tbody>
              {detail.categories.map((c) => (
                <tr key={c.key}>
                  <td>
                    <div className="company">{c.label}</div>
                    <div className="muted small">{c.eligibility}</div>
                  </td>
                  <td className="num" data-label="Minimum application">
                    <div>
                      {count(c.min_lots)} lot{c.min_lots > 1 ? "s" : ""}
                    </div>
                    <div className="muted small">
                      {count(c.shares)} shares{c.max_lots ? `, up to ${count(c.max_lots)} lots` : ""}
                    </div>
                  </td>
                  <td className="num" data-label="Amount">
                    <div>{rupees(c.amount)}</div>
                    {c.buy_price !== detail.issue_price && <div className="muted small">at {rupees2(c.buy_price)}/share</div>}
                  </td>
                  <PnlCell c={listing[c.key]} label="Listing day" />
                  <PnlCell c={latest[c.key]} label="Today" />
                  {pnl?.on_date ? (
                    <PnlCell c={onDate[c.key]} label={longDate(pnl.on_date.trade_date)} />
                  ) : (
                    <td className="num muted small" data-label="Chosen date">
                      Pick a date
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          Each row is the smallest application allowed in that category. When a category is oversubscribed, winners are picked by lottery and each
          gets this minimum, so this is what a successful applicant typically received.
        </p>
      </div>

      <div className="card">
        <h2>Price since listing</h2>
        <Suspense fallback={<p className="muted">Loading chart…</p>}>
          <PriceChart series={series} listingDate={detail.listing_date} selected={pnl?.on_date?.trade_date} onPick={setPicked} />
        </Suspense>
      </div>

      {(detail.subscription.total ?? detail.subscription.individual) != null && (
        <div className="card">
          <h2>How many times each category was subscribed</h2>
          <div className="chips">
            {(
              [
                ["Retail / individual", detail.subscription.individual],
                ["Small HNI", detail.subscription.snii],
                ["Big HNI", detail.subscription.bnii],
                ["QIB", detail.subscription.qib],
                ["Overall", detail.subscription.total],
              ] as [string, number | null][]
            )
              .filter(([, v]) => v != null)
              .map(([k, v]) => (
                <span key={k} className="pill">
                  {k}: <b>{(v as number).toFixed(2)}×</b>
                </span>
              ))}
          </div>
        </div>
      )}
      {detail.notes && <p className="muted small">Note: {detail.notes}</p>}
    </section>
  );
}
