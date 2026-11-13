import { useEffect, useState } from "react";

/** Tiny hash router: "#/ipo/INE0BJO01010?date=2026-10-29" → { path: "/ipo/INE0BJO01010", params }.
 *  Hash URLs work on any static host (GitHub Pages, Netlify) without server rewrites. */
export function useRoute() {
  const read = () => {
    const raw = window.location.hash.replace(/^#/, "") || "/";
    const [path, query = ""] = raw.split("?");
    return { path, params: new URLSearchParams(query) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function go(path: string, params?: Record<string, string | undefined>) {
  const q = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => v && q.set(k, v));
  const s = q.toString();
  window.location.hash = path + (s ? "?" + s : "");
}

/** Change the query string without adding a history entry (used while picking dates). */
export function replaceParams(path: string, params: Record<string, string | undefined>) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v && q.set(k, v));
  const s = q.toString();
  history.replaceState(null, "", "#" + path + (s ? "?" + s : ""));
}
