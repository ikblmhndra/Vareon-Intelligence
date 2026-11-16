import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { TweetStats } from "@/lib/api/loose-types";
import { isClientError } from "@/lib/exec/query";
import { toQuery, type XIntelFilters } from "@/lib/xintel/filters";

export const PAGE_SIZE = 20;

/** 4xx tidak sembuh dengan diulang; 5xx maksimal dua kali. */
const retry = (n: number, e: unknown) => n < 2 && !isClientError(e);

/** Daftar tweet. `anchor` ada di key supaya feed tidak bergeser sampai anchor diganti. */
export function useTweets(filters: XIntelFilters, anchor: number, page: number) {
  return useQuery({
    queryKey: ["xintel", "tweets", filters, anchor, page],
    retry,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tweets", {
        params: { query: { page, page_size: PAGE_SIZE, ...toQuery(filters, anchor) } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return data;
    },
  });
}

/** Statistik dengan filter yang persis sama dengan daftar (key tanpa `page`). */
export function useTweetStats(filters: XIntelFilters, anchor: number) {
  return useQuery({
    queryKey: ["xintel", "tweet-stats", filters, anchor],
    retry,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tweets/stats", {
        params: { query: toQuery(filters, anchor) },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return data as unknown as TweetStats;
    },
  });
}
