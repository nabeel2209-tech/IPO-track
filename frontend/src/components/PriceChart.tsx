import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { longDate, rupees2, shortDate } from "../format";
import type { PriceSeries } from "../types";

interface Props {
  series: PriceSeries;
  listingDate: string;
  selected?: string;
  onPick: (date: string) => void;
}

/** Split-adjusted closing price since listing. Click anywhere on the chart to pick that day. */
export default function PriceChart({ series, listingDate, selected, onPick }: Props) {
  const data = series.points.map((p) => ({ date: p.date, price: p.adj_close, traded: p.close }));
  if (!data.length) return <p className="muted pad">No prices yet.</p>;
  const listing = data.find((d) => d.date === listingDate);
  const selectedPoint = selected ? [...data].reverse().find((d) => d.date <= selected) : undefined;

  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart
          data={data}
          margin={{ top: 12, right: 16, bottom: 4, left: 4 }}
          onClick={(e) => {
            if (e && typeof e.activeLabel === "string") onPick(e.activeLabel);
          }}
        >
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={40} tick={{ fill: "var(--muted)", fontSize: 12 }} stroke="var(--grid)" />
          <YAxis
            // always include the issue price so the dashed line is visible
            domain={[(lo: number) => Math.floor(Math.min(lo, series.issue_price) * 0.95), (hi: number) => Math.ceil(Math.max(hi, series.issue_price) * 1.05)]}
            tickFormatter={(v: number) => "₹" + Math.round(v).toLocaleString("en-IN")}
            width={72}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            stroke="var(--grid)"
          />
          <Tooltip
            formatter={(v: number) => [rupees2(v), "Close (adjusted)"]}
            labelFormatter={(l: string) => longDate(l)}
            contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8 }}
          />
          <ReferenceLine
            y={series.issue_price}
            stroke="var(--muted)"
            strokeDasharray="4 4"
            label={{ value: `Issue ${rupees2(series.issue_price)}`, position: "insideTopLeft", fill: "var(--muted)", fontSize: 12 }}
          />
          {series.corporate_actions.map((a) => (
            <ReferenceLine key={a.ex_date} x={a.ex_date} stroke="var(--accent-2)" strokeDasharray="2 3" />
          ))}
          {selectedPoint && <ReferenceLine x={selectedPoint.date} stroke="var(--accent)" />}
          <Line type="linear" dataKey="price" stroke="var(--accent)" strokeWidth={2} dot={false} isAnimationActive={false} />
          {listing && <ReferenceDot x={listing.date} y={listing.price} r={4} fill="var(--accent)" stroke="var(--panel)" />}
        </LineChart>
      </ResponsiveContainer>
      <p className="muted small">
        Click the chart to see profit on that day. The dashed line is the issue price
        {series.corporate_actions.length ? "; dotted lines mark splits or bonuses (prices are adjusted so they compare with the issue price)" : ""}.
      </p>
    </div>
  );
}
