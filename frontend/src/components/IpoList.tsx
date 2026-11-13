import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { count, longDate, pct, rupees, rupees2, tone } from "../format";
import type { IpoSummary, Meta } from "../types";
import { go } from "../useRoute";

type SortKey = "listing_date" | "listing_return" | "latest_return" | "company";
type SegmentFilter = "all" | "mainboard" | "sme";

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export default function IpoListView({ meta }: { meta: Meta | null }) {
  const [segment, setSegment] = useState<SegmentFilter>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<SortKey>("listing_date");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [items, setItems] = useState<IpoSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params: Record<string, string> = { sort, order };
    if (segment !== "all") params.segment = segment;
    if (q.trim()) params.q = q.trim();
    const t = setTimeout(() => {
      api
        .list(params)
        .then((r) => {
          setItems(r.items);
          setError(null);
        })
        .catch((e) => setError(e.message));
    }, 200); // small debounce while typing
    return () => clearTimeout(t);
  }, [segment, q, sort, order]);

  const stats = useMemo(() => {
    const priced = (items ?? []).filter((i) => i.latest_return != null);
    return {
      n: items?.length ?? 0,
      up: priced.filter((i) => (i.latest_return ?? 0) > 0).length,
      priced: priced.length,
      median: median(priced.map((i) => i.latest_return as number)),
      listingUp: (items ?? []).filter((i) => (i.listing_return ?? 0) > 0).length,
    };
  }, [items]);

  const header = (key: SortKey, label: string, numeric = true) => (
    <th
      className={numeric ? "num" : ""}
      aria-sort={sort === key ? (order === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        onClick={() => {
          if (sort === key) setOrder(order === "asc" ? "desc" : "asc");
          else {
            setSort(key);
            setOrder(key === "company" ? "asc" : "desc");
          }
        }}
      >
        {label}
        {sort === key ? (order === "asc" ? " ↑" : " ↓") : ""}
      </button>
    </th>
  );

  return (
    <section>
      <div className="hero">
        <h1>How did every IPO actually do?</h1>
        <p>
          Pick any mainboard or SME IPO to see what retail, HNI, employee and shareholder investors needed to apply, and what they made on listing
          day, today, or on any date in between.
        </p>
      </div>

      <div className="stats">
        <div className="stat">
          <span className="label">IPOs tracked</span>
          <span className="value">{count(meta?.ipo_count ?? stats.n)}</span>
          <span className="sub">
            {count(meta?.mainboard_count)} mainboard, {count(meta?.sme_count)} SME
          </span>
        </div>
        <div className="stat">
          <span className="label">Gained on listing day</span>
          <span className="value up">{count(stats.listingUp)}</span>
          <span className="sub">of the {count(stats.n)} shown</span>
        </div>
        <div className="stat">
          <span className="label">Above issue price today</span>
          <span className="value up">{count(stats.up)}</span>
          <span className="sub">of {count(stats.priced)} with prices</span>
        </div>
        <div className="stat">
          <span className="label">Median return today</span>
          <span className={"value " + tone(stats.median)}>{pct(stats.median)}</span>
          <span className="sub">split and bonus adjusted</span>
        </div>
      </div>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Segment">
          {(["all", "mainboard", "sme"] as SegmentFilter[]).map((s) => (
            <button key={s} aria-pressed={segment === s} onClick={() => setSegment(s)}>
              {s === "all" ? "All" : s === "mainboard" ? "Mainboard" : "SME"}
            </button>
          ))}
        </div>
        <input className="search" type="search" placeholder="Search company or symbol" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {error && <p className="error">Couldn't load IPOs: {error}</p>}
      {!items && !error && <p className="muted">Loading…</p>}
      {items && (
        <div className="table-wrap">
          <table className="ipo-table">
            <thead>
              <tr>
                {header("company", "Company", false)}
                <th>Segment</th>
                {header("listing_date", "Listed")}
                <th className="num">Issue price</th>
                <th className="num">Lot size</th>
                <th className="num">Min. investment</th>
                {header("listing_return", "Listing day")}
                {header("latest_return", "Today")}
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.isin} onClick={() => go(`/ipo/${i.isin}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && go(`/ipo/${i.isin}`)}>
                  <td>
                    <div className="company">{i.company}</div>
                    <div className="muted small">{i.nse_symbol ?? i.bse_code ?? i.isin}</div>
                  </td>
                  <td>
                    <span className={"badge " + i.segment}>{i.segment === "sme" ? "SME" : "Mainboard"}</span>
                  </td>
                  <td className="num">{longDate(i.listing_date)}</td>
                  <td className="num">{rupees2(i.issue_price)}</td>
                  <td className="num">{count(i.lot_size)}</td>
                  <td className="num">{rupees(i.min_investment)}</td>
                  <td className={"num " + tone(i.listing_return)}>{pct(i.listing_return)}</td>
                  <td className={"num " + tone(i.latest_return)}>{pct(i.latest_return)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && <p className="muted pad">No IPOs match.</p>}
        </div>
      )}
    </section>
  );
}
