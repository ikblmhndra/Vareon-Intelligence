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
import { useCan } from "@/lib/auth/permissions";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import { useArticlesQuery, type ArticlesQuery } from "@/components/newsroom/use-articles";

type Article = components["schemas"]["ArticleOut"];

export type RubricKey = "apac" | "global" | "local" | "ransomware" | "watchlist" | "techstack";

/** Satu baris rubrik. Korban ransomware tidak punya `article`; `href` = `post_url`-nya. */
export interface RubricItem {
  id: string;
  title: string;
  meta: string;
  article?: Article;
  victim?: RansomwareVictim;
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
    victim: v,
    href: v.post_url && v.post_url !== "Unknown" ? v.post_url : undefined,
  };
}

export function useWatchlistNames(enabled: boolean) {
  return useQuery({
    queryKey: ["ta", "watchlist-names"],
    queryFn: async () => {
      const data = unwrap(await api.GET("/api/ta/watchlist-names"), "Failed to load watchlist names");
      return (data as { names?: string[] }).names ?? [];
    },
    retry: noClientRetry,
    enabled,
  });
}

export function useTechStackNames(enabled: boolean) {
  return useQuery({
    queryKey: ["techstack", "names"],
    queryFn: async () => {
      const data = unwrap(
        await api.GET("/api/techstack", { params: { query: { page_size: 500 } } }),
        "Failed to load tech stack names",
      );
      return data.items.map((t) => t.name);
    },
    retry: noClientRetry,
    enabled,
  });
}

/** "Why it matters": artikel cocok watchlist (salah satu `threat_actors` ada di nama watchlist
 * klien) dan/atau tech stack (judul memuat nama tech stack), keduanya case-insensitive. Aturan
 * yang sama dengan rubrik Watchlist (`threat_actor`) dan Tech stack (`title_keyword`). Query nama
 * dipakai bersama rubrik (key react-query sama). */
export function useArticleMatchers(): (a: Article) => { watchlist: boolean; techstack: boolean } {
  // Gate permission backend (view_ta / view_cve): tanpa izin, query tidak ditembak (403 sia-sia).
  const can = useCan();
  const watch = useWatchlistNames(can("view_ta"));
  const tech = useTechStackNames(can("view_cve"));
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
      const data = unwrap(
        await api.GET("/api/ransomware/victims", {
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
        }),
        "Failed to load ransomware victims",
      );
      return data as unknown as { victims: RansomwareVictim[]; total: number };
    },
    retry: noClientRetry,
    enabled,
    placeholderData: keepPrevious ? keepPreviousData : undefined,
  });
}

type ArticleParams = NonNullable<ArticlesQuery>;

/** Param filter murni (tanpa page/page_size/sort) yang dipakai semua jalur artikel. */
export function baseArticleQuery(filters: NewsroomFilters): ArticleParams {
  return {
    posted_on_start: filters.dateStart || undefined,
    posted_on_end: filters.dateEnd || undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
  };
}

/** Filter artikel per rubrik, satu-satunya sumber untuk `useRubric` dan query halaman depan supaya
 * keduanya identik (spec 6.4). Local memakai `client_countries` (bukan filter country); Watchlist/Tech
 * stack tanpa nama = "no-names"; Ransomware bukan artikel = "victims". */
export function rubricArticleQuery(
  key: RubricKey,
  filters: NewsroomFilters,
  ctx: { clientCountries: string[]; watchNames: string[] | undefined; techNames: string[] | undefined },
): ArticleParams | "no-names" | "victims" {
  const base = baseArticleQuery(filters);
  const country = filters.country ? [filters.country] : undefined;
  switch (key) {
    case "apac":
      return { ...base, news_type: ["apac"], country };
    case "global":
      return { ...base, news_type: GLOBAL_NEWS_TYPES, country };
    case "local":
      return { ...base, country: ctx.clientCountries.length ? ctx.clientCountries : undefined };
    case "watchlist":
      return ctx.watchNames?.length ? { ...base, threat_actor: ctx.watchNames, country } : "no-names";
    case "techstack":
      return ctx.techNames?.length ? { ...base, title_keyword: ctx.techNames, country } : "no-names";
    case "ransomware":
      return "victims";
  }
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
  /** `dataUpdatedAt` query aktif (0 selagi belum ada data); dibaca tampilan, bukan jam render. */
  updatedAt: number;
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

  const ctx = { clientCountries: countries, watchNames: watchNames.data, techNames: techNames.data };
  const paged = (q: ReturnType<typeof rubricArticleQuery>) =>
    q === "no-names" || q === "victims" ? undefined : { page, page_size: pageSize, ...q };

  const newsType = key === "apac" ? ["apac"] : GLOBAL_NEWS_TYPES;
  const byType = useArticlesQuery(
    ["news-type", newsType],
    paged(rubricArticleQuery(key === "apac" ? "apac" : "global", filters, ctx)),
    (key === "apac" || key === "global"),
    keepPrevious,
  );
  const local = useArticlesQuery(
    ["local", countries],
    paged(rubricArticleQuery("local", filters, ctx)),
    key === "local",
    keepPrevious,
  );
  const watch = useArticlesQuery(
    ["watchlist", watchNames.data],
    paged(rubricArticleQuery("watchlist", filters, ctx)),
    key === "watchlist" && hasWatch,
    keepPrevious,
  );
  const tech = useArticlesQuery(
    ["techstack", techNames.data],
    paged(rubricArticleQuery("techstack", filters, ctx)),
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

  const empty = { items: [], total: 0, updatedAt: 0, isPending: false, isError: false };

  if (key === "ransomware") {
    return {
      items: victims.data?.victims.map(victimItem) ?? [],
      total: victims.data?.total,
      updatedAt: victims.dataUpdatedAt,
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
      updatedAt: q.dataUpdatedAt,
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
    updatedAt: q.dataUpdatedAt,
    isPending: q.isPending,
    isError: q.isError,
    refetch: () => void q.refetch(),
  };
}
