"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RansomwareVictim } from "@/lib/api/loose-types";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { GLOBAL_NEWS_TYPES } from "@/lib/newsroom/news-types";
import { useAuth } from "@/components/providers/auth-provider";
import { useArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

export type RubricKey = "apac" | "global" | "local" | "ransomware" | "watchlist" | "techstack";

/** Satu baris rubrik. Korban ransomware tidak punya `article`; `href` = `post_url`-nya. */
export interface RubricItem {
  id: string;
  title: string;
  meta: string;
  article?: Article;
  href?: string;
}

function articleItem(a: Article): RubricItem {
  return {
    id: String(a.id),
    title: a.title,
    meta: `${a.source} · ${a.posted_on.slice(0, 10)}`,
    article: a,
  };
}

function victimItem(v: RansomwareVictim): RubricItem {
  const meta = [v.group_name, v.industry, (v.published ?? "").slice(0, 10)].filter(Boolean).join(" · ");
  return {
    id: `victim-${v.id}`,
    title: v.victim,
    meta,
    href: v.post_url && v.post_url !== "Unknown" ? v.post_url : undefined,
  };
}

function useWatchlistNames(enabled: boolean) {
  return useQuery({
    queryKey: ["ta", "watchlist-names"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/ta/watchlist-names");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (data as { names?: string[] } | undefined)?.names ?? [];
    },
    enabled,
  });
}

function useTechStackNames(enabled: boolean) {
  return useQuery({
    queryKey: ["techstack", "names"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack", { params: { query: { page_size: 500 } } });
      if (error) throw error;
      return data.items.map((t) => t.name);
    },
    enabled,
  });
}

function useVictims(
  page: number,
  pageSize: number,
  country: string | null,
  enabled: boolean,
  keepPrevious: boolean,
) {
  return useQuery({
    queryKey: ["ransomware", "victims", page, pageSize, country ?? "", "", ""],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/victims", {
        params: { query: { page, page_size: pageSize, country: country || undefined } },
      });
      if (error) throw error;
      return data as unknown as { victims: RansomwareVictim[]; total: number };
    },
    enabled,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
}

/**
 * Query tiap rubrik newsroom, dipindah apa adanya dari `panels/*.tsx` (param,
 * daftar `news_type`, lookup nama watchlist/techstack, request ransomware).
 * Semua hook dipanggil tanpa syarat (aturan hooks); `enabled` yang memilih
 * satu rubrik yang benar-benar menembak jaringan.
 *
 * Filter `incidentOnly` (`confirmed_only`) dan `country` berlaku di semua rubrik,
 * kecuali: Local tetap memakai `client_countries` (bukan filter country) dan
 * Ransomware hanya menerima `country` (endpoint-nya tidak punya filter insiden).
 * `keepPrevious` menahan data halaman lama selama halaman baru dimuat (pager sheet).
 */
export function useRubric(
  key: RubricKey,
  filters: NewsroomFilters,
  page: number,
  pageSize: number,
  keepPrevious = false,
): {
  items: RubricItem[];
  total: number | undefined;
  isPending: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const { user } = useAuth();
  const countries = user?.client_countries ?? [];

  const watchNames = useWatchlistNames(key === "watchlist");
  const techNames = useTechStackNames(key === "techstack");
  const hasWatch = (watchNames.data?.length ?? 0) > 0;
  const hasTech = (techNames.data?.length ?? 0) > 0;

  const common = {
    page,
    page_size: pageSize,
    posted_on_start: filters.dateStart || undefined,
    posted_on_end: filters.dateEnd || undefined,
    industry: filters.industry ? [filters.industry] : undefined,
    threat_actor: filters.actor ? [filters.actor] : undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
  };
  const countryParam = filters.country ? [filters.country] : undefined;

  const newsType = key === "apac" ? ["apac"] : GLOBAL_NEWS_TYPES;
  const byType = useArticlesQuery(
    ["news-type", newsType],
    { ...common, news_type: newsType, country: countryParam },
    key === "apac" || key === "global",
    keepPrevious,
  );
  const local = useArticlesQuery(
    ["local", countries],
    { ...common, country: countries.length ? countries : undefined },
    key === "local",
    keepPrevious,
  );
  const watch = useArticlesQuery(
    ["watchlist", watchNames.data],
    {
      page,
      page_size: pageSize,
      threat_actor: watchNames.data,
      search: filters.search || undefined,
      confirmed_only: filters.incidentOnly || undefined,
      country: countryParam,
    },
    key === "watchlist" && hasWatch,
    keepPrevious,
  );
  const tech = useArticlesQuery(
    ["techstack", techNames.data],
    { ...common, title_keyword: techNames.data, country: countryParam },
    key === "techstack" && hasTech,
    keepPrevious,
  );
  const victims = useVictims(page, pageSize, filters.country, key === "ransomware", keepPrevious);

  const empty = { items: [], total: 0, isPending: false, isError: false };

  if (key === "ransomware") {
    return {
      items: victims.data?.victims.map(victimItem) ?? [],
      total: victims.data?.total,
      isPending: victims.isPending,
      isError: victims.isError,
      refetch: () => void victims.refetch(),
    };
  }
  if (key === "watchlist" || key === "techstack") {
    const names = key === "watchlist" ? watchNames : techNames;
    const has = key === "watchlist" ? hasWatch : hasTech;
    const q = key === "watchlist" ? watch : tech;
    const refetch = () => {
      void names.refetch();
      void q.refetch();
    };
    // Nama kosong = rubrik kosong (query artikel tidak ditembak), bukan loading.
    if (names.isPending) return { ...empty, items: [], total: undefined, isPending: true, refetch };
    if (names.isError) return { ...empty, isError: true, refetch };
    if (!has) return { ...empty, refetch };
    return {
      items: q.data?.articles.map(articleItem) ?? [],
      total: q.data?.total,
      isPending: q.isPending,
      isError: q.isError,
      refetch,
    };
  }
  const q = key === "local" ? local : byType;
  return {
    items: q.data?.articles.map(articleItem) ?? [],
    total: q.data?.total,
    isPending: q.isPending,
    isError: q.isError,
    refetch: () => void q.refetch(),
  };
}
