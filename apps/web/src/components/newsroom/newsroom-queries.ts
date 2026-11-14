"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { useAuth } from "@/components/providers/auth-provider";
import { useCan } from "@/lib/auth/permissions";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import type { ArticlesQuery } from "@/components/newsroom/use-articles";
import {
  baseArticleQuery,
  rubricArticleQuery,
  useTechStackNames,
  useWatchlistNames,
  type RubricKey,
} from "@/components/newsroom/rubric-queries";

type Params = NonNullable<ArticlesQuery>;

/** Filter artikel halaman depan: param, atau alasan kenapa tidak ada query artikel. */
export type Narrowing = Params | "no-names" | "victims" | "pending";

const isParams = (n: Narrowing): n is Params => typeof n === "object";

/** Rubrik null = filter polos; selain itu `rubricArticleQuery` yang sama dengan `useRubric`.
 * "pending" selagi nama Watchlist / Tech stack dimuat. */
export function useNarrowing(rubric: RubricKey | null, filters: NewsroomFilters): Narrowing {
  const { user } = useAuth();
  const can = useCan();
  const watch = useWatchlistNames(rubric === "watchlist" && can("view_ta"));
  const tech = useTechStackNames(rubric === "techstack" && can("view_cve"));

  if (rubric === null) {
    return { ...baseArticleQuery(filters), country: filters.country ? [filters.country] : undefined };
  }
  if ((rubric === "watchlist" && watch.isLoading) || (rubric === "techstack" && tech.isLoading)) return "pending";
  return rubricArticleQuery(rubric, filters, {
    clientCountries: user?.client_countries ?? [],
    watchNames: watch.data,
    techNames: tech.data,
  });
}

/** Halaman depan: empat artikel teratas (lead + tiga sekunder) berdasarkan prioritas. */
export function useFrontArticles(narrowing: Narrowing) {
  const params: Params = isParams(narrowing) ? { ...narrowing, page: 1, page_size: 4, sort: "priority" } : {};
  return useQuery({
    queryKey: ["newsroom", "front", params],
    queryFn: async () =>
      unwrap(await api.GET("/api/articles", { params: { query: params } }), "Failed to load the front page"),
    retry: noClientRetry,
    enabled: isParams(narrowing),
    placeholderData: keepPreviousData,
  });
}

/** Jumlah artikel (kalimat ringkasan): `page_size=1`, yang dipakai hanya `total`. */
export function useArticleCount(narrowing: Narrowing) {
  const params: Params = isParams(narrowing) ? { ...narrowing, page: 1, page_size: 1, sort: "recent" } : {};
  return useQuery({
    queryKey: ["newsroom", "count", params],
    queryFn: async () =>
      unwrap(await api.GET("/api/articles", { params: { query: params } }), "Failed to load the article count")
        .total,
    retry: noClientRetry,
    enabled: isParams(narrowing),
    placeholderData: keepPreviousData,
  });
}

/** Artikel terbaru tanpa batas periode, untuk state "kosong di periode ini". */
export function useNewestMatch(narrowing: Narrowing, enabled: boolean) {
  const params: Params = isParams(narrowing)
    ? { ...narrowing, posted_on_start: undefined, posted_on_end: undefined, page: 1, page_size: 1, sort: "recent" }
    : {};
  return useQuery({
    queryKey: ["newsroom", "newest", params],
    queryFn: async () => {
      const data = unwrap(
        await api.GET("/api/articles", { params: { query: params } }),
        "Failed to load the newest article",
      );
      return { article: data.articles[0] ?? null };
    },
    retry: noClientRetry,
    enabled: enabled && isParams(narrowing),
  });
}

/** Topik naik (aktor/TTP); limit 6 (dulu dibaca `topics-strip.tsx`). */
export function useTopics(filters: NewsroomFilters) {
  const params = {
    posted_on_start: filters.dateStart || undefined,
    country: filters.country ? [filters.country] : undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
    limit: 6,
  };
  return useQuery({
    queryKey: ["newsroom", "topics", params],
    queryFn: async () =>
      unwrap(await api.GET("/api/newsroom/topics", { params: { query: params } }), "Failed to load active topics"),
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}
