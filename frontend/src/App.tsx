import { useEffect, useState } from "react";
import { api } from "./api";
import AskPanel from "./components/AskPanel";
import IpoDetailView from "./components/IpoDetail";
import IpoListView from "./components/IpoList";
import { longDate } from "./format";
import type { Meta } from "./types";
import { useRoute } from "./useRoute";

export default function App() {
  const { path, params } = useRoute();
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  const ipoMatch = path.match(/^\/ipo\/([A-Z0-9]{12})$/i);

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden>
            ▲
          </span>
          IPO Tracker
        </a>
        <nav>
          <a href="#/" className={!ipoMatch && path !== "/ask" ? "active" : ""}>
            All IPOs
          </a>
          <a href="#/ask" className={path === "/ask" ? "active" : ""}>
            Ask AI
          </a>
        </nav>
        <span className="asof">{meta?.latest_price_date ? `Prices as of ${longDate(meta.latest_price_date)}` : ""}</span>
      </header>

      <main>
        {ipoMatch ? (
          <IpoDetailView isin={ipoMatch[1].toUpperCase()} date={params.get("date") ?? undefined} />
        ) : path === "/ask" ? (
          <AskPanel />
        ) : (
          <IpoListView meta={meta} />
        )}
      </main>

      <footer>
        Prices are end-of-day closes from NSE and BSE bhavcopy files, with Yahoo Finance filling gaps. Profit and loss assume the minimum
        application in each category was allotted at the issue price, and ignore brokerage, taxes and dividends. This shows past performance only
        and is not investment advice.
      </footer>
    </div>
  );
}
