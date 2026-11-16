"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

export type ArticlesQuery = paths["/api/articles"]["get"]["parameters"]["query"];

/** Fetch hook bareng buat `GET /api/articles` -- dipakai semua panel
 * (APAC/Global/Local/Watchlist/Techstack), tiap panel susun `params`-nya
 * sendiri (filter mana yang kepake beda-beda per panel, port apa adanya
 * dari `loadPanel()`/`loadLocalPanel()`/`loadWatchlistPanel()`/
 * `loadTechStackPanel()` lama -- lihat catatan di tiap panel file).
 * `sort` ("recent"|"priority"), `ttp` dan `confirmed_only` ikut diteruskan
 * apa adanya (tipe dari `schema.d.ts`). */
export function useArticlesQuery(key: readonly unknown[], params: ArticlesQuery, enabled = true, keepPrevious = false) {
  return useQuery({
    queryKey: ["newsroom", "articles", ...key, params],
    queryFn: async () => {
      return unwrap(
        await api.GET("/api/articles", { params: { query: params ?? {} } }),
        "Failed to load articles",
      );
    },
    retry: noClientRetry,
    enabled,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
}
