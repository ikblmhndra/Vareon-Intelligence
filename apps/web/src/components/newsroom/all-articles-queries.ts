"use client";

import { useMemo } from "react";
import { keepPreviousData, useInfiniteQuery, useQueries, useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/providers/auth-provider";
import {
  useTechStackNames,
  useWatchlistNames,
  type RubricKey,
} from "@/components/newsroom/rubric-queries";
import type { ArticlesQuery } from "@/components/newsroom/use-articles";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RansomwareVictim } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { allStateToQuery, type AllState } from "@/lib/newsroom/all-state";
import { periodStart } from "@/lib/newsroom/filters";
import { newsroomPeriodInfo } from "@/lib/newsroom/period";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

type Article = components["schemas"]["ArticleOut"];
type ArticleIocsOut = components["schemas"]["ArticleIocsOut"];
type ArticleParams = NonNullable<ArticlesQuery>;

const PAGE_SIZE = 20;
const RELATED_PAGE_SIZE = 8;

/** Halaman berikutnya bila baris yang sudah dimuat belum mencapai `total`. */
function nextPage(loaded: number, total: number, pages: number): number | undefined {
  return loaded < total ? pages + 1 : undefined;
}

/** Daftar All articles, 20 per langkah, halaman baru ditambahkan (`LoadMoreFooter`). `undefined`
 * (state "empty" / "pending" / non-artikel) mematikan query. Data lama ditahan saat filter
 * berganti; tampilan meredupkannya lewat `isPlaceholderData`. */
export function useAllArticles(query: ArticlesQuery) {
  return useInfiniteQuery({
    queryKey: ["newsroom", "all", query],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/articles", {
          params: { query: { ...query, page: pageParam, page_size: PAGE_SIZE } },
        }),
        "Failed to load articles",
      ),
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      nextPage(
        pages.reduce((n, p) => n + p.articles.length, 0),
        last.total,
        pages.length,
      ),
    enabled: query !== undefined,
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

/** Rencana + query daftar All articles untuk state ini. AllArticlesView dan AllList wajib memanggil
 * pasangan yang sama (`useAllArticles(useAllListQuery(state).query)`) supaya berbagi satu kunci cache.
 * `plan` = hasil mentah `allStateToQuery`; `query` = objeknya atau undefined. */
export function useAllListQuery(state: AllState): {
  plan: ReturnType<typeof allStateToQuery>;
  query: ArticleParams | undefined;
  namesError?: { error: unknown; refetch: () => void };
} {
  const can = useCan();
  const { user } = useAuth();
  const watch = useWatchlistNames(can("view_ta"));
  const tech = useTechStackNames(can("view_cve"));
  const clientCountries = user?.client_countries ?? [];
  // Jam dibaca sekali per perubahan periode, bukan tiap render.
  const dateStart = useMemo(
    () => state.from ?? periodStart(newsroomPeriodInfo(state.period).days ?? 0),
    [state.from, state.period],
  );
  const plan = allStateToQuery(state, {
    clientCountries,
    watchNames: watch.data,
    techNames: tech.data,
    dateStart,
  });
  // Galat query nama rubrik aktif: tanpa nama `allStateToQuery` memberi "pending" selamanya, jadi
  // pemanggil butuh galatnya untuk menampilkan panel galat + Retry (spec 6.6).
  const active = state.rubric === "watchlist" ? watch : state.rubric === "techstack" ? tech : null;
  const namesError =
    active !== null && active.isError
      ? { error: active.error as unknown, refetch: () => void active.refetch() }
      : undefined;
  return { plan, query: typeof plan === "object" ? plan : undefined, namesError };
}

/** Hitungan rubrik di rail: `undefined` = memuat, `null` = galat atau rubrik tidak terlihat
 * (tanpa izin; tidak ada request). */
export type RubricCounts = Record<"all" | RubricKey, number | null | undefined>;

const COUNT_KEYS: readonly ("all" | RubricKey)[] = [
  "all",
  "apac",
  "global",
  "local",
  "ransomware",
  "watchlist",
  "techstack",
];

type CountPlan =
  | { kind: "value"; value: number | null | undefined }
  | { kind: "articles"; query: ArticleParams }
  | { kind: "victims"; dateStart: string; country: string | null };

/** Satu query `page_size=1` per baris rubrik dengan filter state tanpa rubriknya. Hitungan selalu
 * semantik recent (artikel, bukan cerita; aturan 4). Ransomware = total korban dengan periode +
 * negara pertama saja (aturan 7). */
export function useRubricCounts(state: AllState): RubricCounts {
  const can = useCan();
  const { user } = useAuth();
  const clientCountries = user?.client_countries ?? [];
  const canIntel = can("view_intel");
  const canWatch = can("view_ta");
  const canTech = can("view_cve");
  const watch = useWatchlistNames(canWatch);
  const tech = useTechStackNames(canTech);
  // Jam dibaca sekali per perubahan periode, bukan tiap render.
  const dateStart = useMemo(
    () => state.from ?? periodStart(newsroomPeriodInfo(state.period).days ?? 0),
    [state.from, state.period],
  );
  const ctx = { clientCountries, watchNames: watch.data, techNames: tech.data, dateStart };

  const plans = COUNT_KEYS.map((key): CountPlan => {
    if (key === "ransomware") {
      return canIntel
        ? { kind: "victims", dateStart, country: state.countries[0] ?? null }
        : { kind: "value", value: null };
    }
    if (key === "watchlist" && !canWatch) return { kind: "value", value: null };
    if (key === "techstack" && !canTech) return { kind: "value", value: null };
    if (key === "watchlist" && watch.isError) return { kind: "value", value: null };
    if (key === "techstack" && tech.isError) return { kind: "value", value: null };
    const q = allStateToQuery(
      { ...state, rubric: key === "all" ? null : key, sort: "recent" },
      ctx,
    );
    if (q === "empty" || q === "no-names") return { kind: "value", value: 0 };
    if (q === "pending") return { kind: "value", value: undefined };
    if (q === "victims") return { kind: "value", value: null };
    return { kind: "articles", query: q };
  });

  const results = useQueries({
    queries: plans.map((plan, i) => ({
      queryKey: ["newsroom", "all-count", COUNT_KEYS[i], plan],
      queryFn: async (): Promise<number> => {
        if (plan.kind === "articles") {
          const data = unwrap(
            await api.GET("/api/articles", {
              params: { query: { ...plan.query, page: 1, page_size: 1 } },
            }),
            "Failed to load articles",
          );
          return data.total;
        }
        if (plan.kind === "victims") {
          const data = unwrap(
            await api.GET("/api/ransomware/victims", {
              params: {
                query: {
                  page: 1,
                  page_size: 1,
                  country: plan.country || undefined,
                  date_start: plan.dateStart || undefined,
                },
              },
            }),
            "Failed to load ransomware victims",
          );
          return (data as unknown as { total: number }).total;
        }
        return 0;
      },
      enabled: plan.kind !== "value",
      retry: noClientRetry,
    })),
  });

  const out = {} as RubricCounts;
  COUNT_KEYS.forEach((key, i) => {
    const plan = plans[i];
    if (plan.kind === "value") out[key] = plan.value;
    else if (results[i].isError) out[key] = null;
    else out[key] = results[i].data;
  });
  return out;
}

/** Artikel terpilih yang tidak ada di daftar (deep link atau di luar filter). */
export function useArticleById(id: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ["newsroom", "article", id],
    queryFn: async (): Promise<Article> =>
      unwrap(
        await api.GET("/api/articles/{article_id}", { params: { path: { article_id: id as number } } }),
        "Failed to load the article",
      ),
    enabled: enabled && id !== null,
    retry: noClientRetry,
  });
}

/** IOC artikel (konteks + reputasi), dimuat malas saat pembaca menampilkan artikel itu. */
export function useArticleIocs(id: number | null) {
  return useQuery({
    queryKey: ["newsroom", "article-iocs", id],
    queryFn: async (): Promise<ArticleIocsOut> =>
      unwrap(
        await api.GET("/api/articles/{article_id}/iocs", { params: { path: { article_id: id as number } } }),
        "Failed to load the indicators",
      ),
    enabled: id !== null,
    retry: noClientRetry,
  });
}

/** Sumber lain satu cerita (nama unik) untuk "also reported by". `sort: "recent"` karena di bawah
 * priority cerita runtuh jadi satu baris (aturan 5). `excludeId` dan sumbernya (bila barisnya ikut
 * termuat, maks 50) dibuang; `select` memisahkannya dari cache bersama per cerita. */
export function useStorySources(storyId: number | null, excludeId: number | null) {
  return useQuery({
    queryKey: ["newsroom", "story-sources", storyId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/articles", {
          params: { query: { story_id: storyId as number, sort: "recent", page_size: 50 } },
        }),
        "Failed to load the story sources",
      ),
    select: (data): string[] => {
      const own = data.articles.find((a) => a.id === excludeId)?.source;
      const names = data.articles
        .filter((a) => a.id !== excludeId && a.source !== own)
        .map((a) => a.source);
      return [...new Set(names)];
    },
    enabled: storyId !== null,
    retry: noClientRetry,
  });
}

/** Baris korban rubrik Ransomware (aturan 7): periode (`date_start`), negara pertama, serta select
 * Group / Industry. Grade, sektor, sumber, pencarian, insiden tidak berlaku. */
export function useVictimRows(state: AllState, enabled: boolean) {
  // Pemanggil wajib menggerbang dengan `view_intel` lewat `enabled`.
  const dateStart = useMemo(
    () => state.from ?? periodStart(newsroomPeriodInfo(state.period).days ?? 0),
    [state.from, state.period],
  );
  const country = state.countries[0] ?? null;
  return useInfiniteQuery({
    queryKey: ["newsroom", "all-victims", dateStart, country, state.group, state.vindustry],
    queryFn: async ({ pageParam }) => {
      const data = unwrap(
        await api.GET("/api/ransomware/victims", {
          params: {
            query: {
              page: pageParam,
              page_size: PAGE_SIZE,
              country: country || undefined,
              date_start: dateStart || undefined,
              group: state.group || undefined,
              industry: state.vindustry || undefined,
            },
          },
        }),
        "Failed to load ransomware victims",
      );
      return data as unknown as { victims: RansomwareVictim[]; total: number };
    },
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      nextPage(
        pages.reduce((n, p) => n + p.victims.length, 0),
        last.total,
        pages.length,
      ),
    enabled,
    retry: noClientRetry,
    placeholderData: keepPreviousData,
  });
}

/** "Related articles" rubrik Ransomware: `/api/ransomware/related-articles` hanya menerima
 * page/page_size (tanpa param periode), sama seperti sheet lama, 8 per langkah. */
// Pemanggil wajib menggerbang dengan `view_intel` lewat `enabled`.
export function useRelatedArticles(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: ["newsroom", "all-related"],
    queryFn: async ({ pageParam }) => {
      const r = await api.GET("/api/ransomware/related-articles", {
        params: { query: { page: pageParam, page_size: RELATED_PAGE_SIZE } },
      });
      return unwrap(r, "Failed to load related articles") as unknown as { articles: Article[]; total: number };
    },
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      nextPage(
        pages.reduce((n, p) => n + p.articles.length, 0),
        last.total,
        pages.length,
      ),
    enabled,
    retry: noClientRetry,
  });
}
