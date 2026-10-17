"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { TweetStats } from "@/lib/api/loose-types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { SimplePager } from "@/components/pager";
import { TweetCard } from "@/components/xintel/tweet-card";
import { TweetDetailDialog } from "@/components/xintel/tweet-detail-dialog";

type Tweet = components["schemas"]["TweetOut"];

const PAGE_SIZE = 20;

interface Filters {
  search: string;
  author: string;
  dateStart: string;
  dateEnd: string;
  apacOnly: boolean;
  otOnly: boolean;
  confirmedOnly: boolean;
}

const EMPTY_FILTERS: Filters = {
  search: "",
  author: "",
  dateStart: "",
  dateEnd: "",
  apacOnly: false,
  otOnly: false,
  confirmedOnly: false,
};

/** Zona IANA browser user (mis. "Asia/Jakarta") -- backend pakai ini buat
 * batas hari `posted_on_start`/`posted_on_end` (`YYYY-MM-DD`), jadi
 * From/To = hari LOKAL user penuh (To inklusif), konsisten sama waktu tweet
 * yang dirender lokal di `tweet-card.tsx`. Dulu To dibaca 00:00 UTC,
 * same-day range selalu 0 hasil (QA BUG-B5). */
function userTimeZone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** Param tanggal bareng list & stats -- `tz` cuma dikirim kalau ada tanggal. */
function dateParams(filters: Filters) {
  const hasDate = Boolean(filters.dateStart || filters.dateEnd);
  return {
    posted_on_start: filters.dateStart || undefined,
    posted_on_end: filters.dateEnd || undefined,
    tz: hasDate ? userTimeZone() : undefined,
  };
}

function useTweets(filters: Filters, page: number) {
  return useQuery({
    queryKey: ["xintel", "tweets", filters, page],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tweets", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            search: filters.search || undefined,
            author: filters.author || undefined,
            ...dateParams(filters),
            apac_only: filters.apacOnly,
            ot_only: filters.otOnly,
            confirmed_only: filters.confirmedOnly,
          },
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return data;
    },
  });
}

function useTweetStats(filters: Filters) {
  return useQuery({
    queryKey: ["xintel", "tweet-stats", filters],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tweets/stats", {
        params: {
          query: {
            search: filters.search || undefined,
            author: filters.author || undefined,
            ...dateParams(filters),
            apac_only: filters.apacOnly,
            ot_only: filters.otOnly,
            confirmed_only: filters.confirmedOnly,
          },
        },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return data as unknown as TweetStats;
    },
  });
}

/** Port sub-tab Tweets di `xintel.js`. Filter teks/tanggal butuh klik
 * APPLY (port apa adanya -- `draft` beda dari `filters` yang beneran
 * dipakai query), 3 checkbox langsung apply on-change sama kayak lama. */
export function TweetList() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [draft, setDraft] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Tweet | null>(null);

  const tweets = useTweets(filters, page);
  const stats = useTweetStats(filters);

  function applyDraft() {
    setFilters(draft);
    setPage(1);
  }

  function toggleCheckbox(key: "apacOnly" | "otOnly" | "confirmedOnly", checked: boolean) {
    const next = { ...draft, [key]: checked };
    setDraft(next);
    setFilters(next);
    setPage(1);
  }

  function resetFilters() {
    setDraft(EMPTY_FILTERS);
    setFilters(EMPTY_FILTERS);
    setPage(1);
  }

  const totalPages = tweets.data ? Math.ceil(tweets.data.total / PAGE_SIZE) : 0;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-border pb-2.5">
        <span className="text-sm font-semibold text-muted-foreground">
          Filter
        </span>
        <Input
          placeholder="Search tweets…"
          value={draft.search}
          onChange={(e) => setDraft({ ...draft, search: e.target.value })}
          className="w-44 font-mono text-xs"
        />
        <Input
          placeholder="@handle…"
          value={draft.author}
          onChange={(e) => setDraft({ ...draft, author: e.target.value })}
          className="w-32 font-mono text-xs"
        />
        <Input
          type="date" aria-label="From date"
          value={draft.dateStart}
          onChange={(e) => setDraft({ ...draft, dateStart: e.target.value })}
          className="w-auto font-mono text-xs"
        />
        <span className="text-xs text-muted-foreground">→</span>
        <Input
          type="date" aria-label="To date"
          value={draft.dateEnd}
          onChange={(e) => setDraft({ ...draft, dateEnd: e.target.value })}
          className="w-auto font-mono text-xs"
        />
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox checked={draft.apacOnly} onCheckedChange={(c) => toggleCheckbox("apacOnly", c === true)} />
          APAC
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox checked={draft.otOnly} onCheckedChange={(c) => toggleCheckbox("otOnly", c === true)} />
          OT
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox
            checked={draft.confirmedOnly}
            onCheckedChange={(c) => toggleCheckbox("confirmedOnly", c === true)}
          />
          Confirmed Incident
        </label>
        <Button size="sm" onClick={applyDraft}>
          Apply
        </Button>
        <Button size="sm" variant="outline" onClick={resetFilters}>
          Reset
        </Button>
      </div>

      <div className="mb-3 flex flex-wrap gap-4 font-mono text-xs text-muted-foreground">
        {stats.data && (
          <>
            <span>
              Total: <strong className="text-foreground">{stats.data.total}</strong>
            </span>
            {stats.data.top_authors.length > 0 && (
              <span className="border-l border-border pl-4">
                Top:{" "}
                {stats.data.top_authors.slice(0, 5).map((a, i) => (
                  <span key={a.author}>
                    {i > 0 && " · "}
                    <span className="text-primary">@{a.author}</span> ({a.count})
                  </span>
                ))}
              </span>
            )}
          </>
        )}
      </div>

      {tweets.isPending && (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}
      {tweets.isError && <p className="text-sm text-destructive">Failed to load tweets.</p>}
      {tweets.data && tweets.data.tweets.length === 0 && (
        <div className="rounded-md border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          No tweets found
        </div>
      )}
      {tweets.data && tweets.data.tweets.length > 0 && (
        <div className="flex flex-col gap-2">
          {tweets.data.tweets.map((t) => (
            <TweetCard key={t.id} tweet={t} onClick={() => setSelected(t)} />
          ))}
        </div>
      )}

      <div className="mt-3">
        <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
      </div>

      <TweetDetailDialog tweet={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}
