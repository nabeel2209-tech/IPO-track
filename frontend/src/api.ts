import type { AskAnswer, IpoDetail, IpoList, Meta, Pnl, PriceSeries } from "./types";

// Same origin in development (Vite proxies /api); set VITE_API_URL when the API lives elsewhere.
const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  list: (params: Record<string, string>) => request<IpoList>("/api/ipos?" + new URLSearchParams(params)),
  detail: (isin: string) => request<IpoDetail>(`/api/ipos/${isin}`),
  pnl: (isin: string, date?: string) => request<Pnl>(`/api/ipos/${isin}/pnl` + (date ? `?date=${date}` : "")),
  prices: (isin: string) => request<PriceSeries>(`/api/ipos/${isin}/prices`),
  ask: (question: string) =>
    request<AskAnswer>("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }),
};
