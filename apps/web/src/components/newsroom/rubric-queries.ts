"use client";

import { useMemo } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RansomwareVictim } from "@/lib/api/loose-types";
import { formatPostedOn } from "@/lib/newsroom/dates";
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
    meta: `${a.source} · ${formatPostedOn(a.posted_on)}`,
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

export function useWatchlistNames(enabled: boolean) {
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

export function useTechStackNames(enabled: boolean) {
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

/** "Why it matters": artikel cocok watchlist (salah satu `threat_actors` ada di nama watchlist
 * klien) dan/atau tech stack (judul memuat nama tech stack), keduanya case-insensitive. Aturan
 * yang sama dengan rubrik Watchlist (`threat_actor`) dan Tech stack (`title_keyword`). Query nama
 * dipakai bersama rubrik (key react-query sama). */
export function useArticleMatchers(): (a: Article) => { watchlist: boolean; techstack: boolean } {
  const watch = useWatchlistNames(true);
  const tech = useTechStackNames(true);
  return useMemo(() => {
    const watchSet = new Set((watch.data ?? []).map((n) => n.toLowerCase()));
    const techNames = (tech.data ?? []).map((n) => n.toLowerCase()).filter(Boolean);
    return (a: Article) => {
      const title = a.title.toLowerCase();
      return {
        watchlist: a.threat_actors.some((t) => watchSet.has(t.toLowerCase())),
        techstack: techNames.some((n) => title.includes(n)),
      };
    };
  }, [watch.data, tech.data]);
}

/** Filter khusus daftar korban (sheet Ransomware): nilai dari `/api/ransomware/victims/filters`. */
export interface VictimFilter {
  group: string;
  industry: string;
}

function useVictims(
  page: number,
  pageSize: number,
  country: string | null,
  dateStart: string,
  victimFilter: VictimFilter,
  enabled: boolean,
  keepPrevious: boolean,
) {
  return useQuery({
    queryKey: [
      "ransomware",
      "victims",
      page,
      pageSize,
      country ?? "",
      dateStart,
      victimFilter.group,
      victimFilter.industry,
    ],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/victims", {
        params: {
          query: {
            page,
            page_size: pageSize,
            country: country || undefined,
            // Periode newsroom; API memfilter `published >= date_start`.
            date_start: dateStart || undefined,
            group: victimFilter.group || undefined,
            industry: victimFilter.industry || undefined,
          },
        },
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
 * Filter periode, `incidentOnly` (`confirmed_only`) dan `country` berlaku di semua
 * rubrik, kecuali: Local tetap memakai `client_countries` (bukan filter country) dan
 * Ransomware hanya menerima `country` + periode (`date_start`; endpoint-nya tidak punya
 * filter insiden), ditambah `victimFilter` (group/industri) dari sheet.
 * `keepPrevious` menahan data halaman lama selama halaman baru dimuat (pager sheet).
 */
const NO_VICTIM_FILTER: VictimFilter = { group: "", industry: "" };

export function useRubric(
  key: RubricKey | null,
  filters: NewsroomFilters,
  page: number,
  pageSize: number,
  keepPrevious = false,
  victimFilter: VictimFilter = NO_VICTIM_FILTER,
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
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
  };
  const countryParam = filters.country ? [filters.country] : undefined;

  const newsType = key === "apac" ? ["apac"] : GLOBAL_NEWS_TYPES;
  const byType = useArticlesQuery(
    ["news-type", newsType],
    { ...common, news_type: newsType, country: countryParam },
    (key === "apac" || key === "global"),
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
    { ...common, threat_actor: watchNames.data, country: countryParam },
    key === "watchlist" && hasWatch,
    keepPrevious,
  );
  const tech = useArticlesQuery(
    ["techstack", techNames.data],
    { ...common, title_keyword: techNames.data, country: countryParam },
    key === "techstack" && hasTech,
    keepPrevious,
  );
  const victims = useVictims(
    page,
    pageSize,
    filters.country,
    filters.dateStart,
    victimFilter,
    key === "ransomware",
    keepPrevious,
  );

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
  if (key === null) return { ...empty, refetch: () => {} };
  const q = key === "local" ? local : byType;
  return {
    items: q.data?.articles.map(articleItem) ?? [],
    total: q.data?.total,
    isPending: q.isPending,
    isError: q.isError,
    refetch: () => void q.refetch(),
  };
}
