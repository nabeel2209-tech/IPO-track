// Number and date formatting in Indian style (₹1,23,456).

const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const int = new Intl.NumberFormat("en-IN");

export const rupees = (v: number | null | undefined) => (v == null ? "—" : "₹" + inr0.format(Math.round(v)));
export const rupees2 = (v: number | null | undefined) => (v == null ? "—" : "₹" + inr2.format(v));
export const count = (v: number | null | undefined) => (v == null ? "—" : int.format(v));

export function signedRupees(v: number | null | undefined): string {
  if (v == null) return "—";
  const r = Math.round(v);
  return (r > 0 ? "+" : r < 0 ? "−" : "") + "₹" + inr0.format(Math.abs(r));
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  const x = v * 100;
  const s = Math.abs(x).toFixed(digits);
  return (x > 0.05 ? "+" : x < -0.05 ? "−" : "") + s + "%";
}

export const tone = (v: number | null | undefined) => (v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");

export function longDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function shortDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** ISO date `days` after `iso`. */
export function addDays(iso: string, days: number): string {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
