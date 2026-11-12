export type Signal = "ot" | "zero_day" | "databreach" | "report";
export type Period = "24h" | "7d" | "30d" | "custom";

export interface XIntelFilters {
  search: string;
  period: Period;
  /** Hanya bermakna untuk `custom`: hari lokal `YYYY-MM-DD`, keduanya inklusif. */
  from: string | null;
  to: string | null;
  signal: Signal | "all";
  confirmed: boolean;
  apac: boolean;
  cve: boolean;
}

export const DEFAULT_FILTERS: XIntelFilters = {
  search: "",
  period: "7d",
  from: null,
  to: null,
  signal: "all",
  confirmed: false,
  apac: false,
  cve: false,
};

export function isDefault(f: XIntelFilters): boolean {
  return (Object.keys(DEFAULT_FILTERS) as (keyof XIntelFilters)[]).every((k) => f[k] === DEFAULT_FILTERS[k]);
}

const PERIOD_MS = { "24h": 86_400_000, "7d": 7 * 86_400_000, "30d": 30 * 86_400_000 } as const;

/** Judul kartu rail dan teks "{periode}" di kartu lain (D24). */
export function periodTitle(f: XIntelFilters): string {
  switch (f.period) {
    case "24h":
      return "Last 24 hours";
    case "7d":
      return "This week";
    case "30d":
      return "Last 30 days";
    default:
      return "Selected range";
  }
}

/** Param query bersama `GET /api/tweets` dan `/api/tweets/stats`. openapi-typescript menandai param
 * ber-default sebagai wajib, jadi empat boolean selalu dikirim; sisanya hanya bila terisi. */
export interface TweetQuery {
  search?: string;
  posted_on_start?: string;
  posted_on_end?: string;
  tz?: string;
  apac_only: boolean;
  ot_only: boolean;
  confirmed_only: boolean;
  has_cve: boolean;
  signal?: Signal;
}

/** `anchor` = epoch ms yang dipegang state halaman: preset memakai instan `anchor - N`, bukan `Date.now()`
 * di render, supaya query key stabil dan daftar tidak refetch tiap render. */
export function toQuery(f: XIntelFilters, anchor: number): TweetQuery {
  const q: TweetQuery = {
    apac_only: f.apac,
    ot_only: false,
    confirmed_only: f.confirmed,
    has_cve: f.cve,
  };
  const search = f.search.trim();
  if (search) q.search = search;
  if (f.signal !== "all") q.signal = f.signal;
  if (f.period === "custom") {
    // Tanggal polos = hari penuh di zona `tz` (zona browser), To inklusif -- kontrak backend (QA BUG-B5).
    if (f.from) q.posted_on_start = f.from;
    if (f.to) q.posted_on_end = f.to;
    if (f.from || f.to) {
      try {
        q.tz = Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
      } catch {
        // zona tak terbaca: backend jatuh ke UTC
      }
    }
  } else {
    q.posted_on_start = new Date(anchor - PERIOD_MS[f.period]).toISOString();
  }
  return q;
}
