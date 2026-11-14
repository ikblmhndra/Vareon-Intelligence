"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/providers/auth-provider";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { CampaignsResponse, TaStats } from "@/lib/api/loose-types";
import { getActiveClientId } from "@/lib/auth/client-id";
import { fmtAgo, fmtCompactAge, fmtDateTime, fmtShortDate, parseLocalDate } from "@/lib/format";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

type Schemas = components["schemas"];
export type DashboardMap = Schemas["DashboardMap"];
export type DashboardAttention = Schemas["DashboardAttention"];
export type TrendingResponse = Schemas["TrendingResponse"];
export type TrendItem = Schemas["TrendItemOut"];
export type RansomwareOverview = Schemas["RansomwareOverview"];
export type CveExposure = Schemas["CveExposure"];
export type DashboardStats = Schemas["DashboardStats"];
export type Article = Schemas["ArticleOut"];

/** Client aktif ikut masuk query key: ganti client (reload penuh) tidak boleh memakai cache client lain. */
function useClientKey(): string | null {
  const { user } = useAuth();
  return getActiveClientId() ?? user?.client_ids[0] ?? null;
}

/** Jenis tren yang ditampilkan Dashboard (TTP sengaja tidak: ia punya halaman sendiri). */
export const TREND_KINDS = ["actor", "malware", "cve"] as const;

// Semua query: lewat `unwrap` (502 body kosong = galat, bukan data kosong), tanpa retry 4xx, tanpa
// polling. Ganti periode: data lama tetap tampil sampai yang baru datang (`keepPreviousData`).

export function useDashboardStats(days: number | null, incidentOnly: boolean) {
  return useQuery({
    queryKey: ["dashboard", "stats", days, incidentOnly],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard", {
          params: { query: { days: days ?? undefined, incident_only: incidentOnly } },
        }),
        "Failed to load dashboard stats",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useDashboardMap(days: number | null) {
  const clientId = useClientKey();
  return useQuery({
    queryKey: ["dashboard", "map", days, clientId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard/map", { params: { query: { days: days ?? undefined } } }),
        "Failed to load the signal map",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useDashboardAttention(days: number | null) {
  const clientId = useClientKey();
  return useQuery({
    queryKey: ["dashboard", "attention", days, clientId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard/attention", { params: { query: { days: days ?? undefined } } }),
        "Failed to load the briefing",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useDashboardTrending(days: number | null, kinds: readonly TrendItem["kind"][]) {
  return useQuery({
    queryKey: ["dashboard", "trending", days, kinds.join(",")],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard/trending", {
          params: { query: { days: days ?? undefined, kinds: [...kinds] } },
        }),
        "Failed to load trending",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useDashboardRansomware(days: number | null) {
  return useQuery({
    queryKey: ["dashboard", "ransomware", days],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard/ransomware", { params: { query: { days: days ?? undefined } } }),
        "Failed to load ransomware",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useCveExposure(days: number | null, limit: number) {
  const clientId = useClientKey();
  return useQuery({
    queryKey: ["dashboard", "cve-exposure", days, limit, clientId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/dashboard/cve-exposure", {
          params: { query: { days: days ?? undefined, limit } },
        }),
        "Failed to load CVE exposure",
      ),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

/** Lima berita prioritas. "Sekarang" dan awal periode dibaca di dalam queryFn (bukan saat render);
 * `fetchedAt` ikut dikembalikan supaya `articleWhen` memakai jam yang sama dengan datanya. */
export function useMustRead(days: number | null) {
  return useQuery({
    queryKey: ["dashboard", "must-read", days],
    queryFn: async () => {
      const fetchedAt = Date.now();
      const postedOnStart =
        days == null ? undefined : new Date(fetchedAt - days * 86_400_000).toISOString().slice(0, 10);
      const data = unwrap(
        await api.GET("/api/articles", {
          params: { query: { page: 1, page_size: 5, posted_on_start: postedOnStart, sort: "priority" } },
        }),
        "Failed to load the must-read list",
      );
      return { articles: data.articles as Article[], fetchedAt };
    },
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

export function useTaStats(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard", "ta-stats"],
    queryFn: async () => unwrap(await api.GET("/api/ta/stats"), "Failed to load threat actor stats") as unknown as TaStats,
    retry: noClientRetry,
    enabled,
  });
}

export function useNewestCluster(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard", "newest-cluster"],
    queryFn: async () => {
      const data = unwrap(
        await api.GET("/api/clusters/recent", { params: { query: { days: 30 } } }),
        "Failed to load the newest campaign",
      ) as unknown as CampaignsResponse;
      return data.campaigns[0] ?? null;
    },
    retry: noClientRetry,
    enabled,
  });
}

/** Antrean LLM dari data-health; menit-an saja cukup, jadi tanpa polling. */
export function useLlmQueue(enabled: boolean) {
  return useQuery({
    queryKey: ["dashboard", "llm-queue"],
    queryFn: async () => unwrap(await api.GET("/api/data-health"), "Failed to load the LLM queue"),
    select: (d) => d.llm.queue,
    retry: noClientRetry,
    staleTime: 60_000,
    enabled,
  });
}

/** Kapan artikel terjadi: < 24 jam sejak first_seen_at = umur relatif; selebihnya tanggal terbit
 * (`posted_on`), lalu first_seen_at bila terbit kosong. `title` = tooltip first seen. */
export function articleWhen(
  a: Pick<Article, "first_seen_at" | "posted_on">,
  fetchedAt: number,
  compact = false,
): { text: string; title?: string } {
  const seen = a.first_seen_at ? new Date(a.first_seen_at).getTime() : NaN;
  const title = a.first_seen_at ? "First seen " + fmtDateTime(a.first_seen_at) : undefined;
  if (!Number.isNaN(seen) && fetchedAt - seen < 86_400_000) {
    return { text: (compact ? fmtCompactAge : fmtAgo)(a.first_seen_at, fetchedAt), title };
  }
  return {
    text: a.posted_on ? fmtShortDate(parseLocalDate(a.posted_on)) : fmtShortDate(a.first_seen_at),
    title,
  };
}
