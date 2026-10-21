"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { RansomwareVictim } from "@/lib/api/loose-types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArticleCollection } from "@/components/newsroom/article-card";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { SimplePager } from "@/components/pager";

type Article = components["schemas"]["ArticleOut"];
type Victim = RansomwareVictim;

const VICTIM_PAGE_SIZE = 20;
const ARTICLE_PAGE_SIZE = 8;

function VictimRow({ v }: { v: Victim }) {
  return (
    <div className="grid grid-cols-[80px_1fr_76px_16px] items-start gap-1 border-b border-border/60 py-1.5 text-xs">
      <span className="truncate font-semibold text-destructive" title={v.group_name}>
        {v.group_name}
      </span>
      <div className="min-w-0">
        <div className="truncate text-foreground" title={v.victim}>
          {v.victim}
        </div>
        <div className="truncate text-xs text-muted-foreground" title={v.industry ?? undefined}>
          {v.industry}
        </div>
      </div>
      <div className="font-mono text-xs text-muted-foreground">
        <div title="Published">{(v.published ?? "").slice(0, 10)}</div>
        <div className="italic" title="Discovered">
          {(v.discovered ?? "").slice(0, 10)}
        </div>
      </div>
      {v.post_url && v.post_url !== "Unknown" ? (
        <a
          href={v.post_url}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open leak post for ${v.victim}`}
          className="inline-flex min-h-6 min-w-6 items-center justify-center text-destructive no-underline"
        >
          ↗
        </a>
      ) : (
        <span className="text-muted-foreground">—</span>
      )}
    </div>
  );
}

function useVictims(page: number, group: string, country: string, industry: string) {
  return useQuery({
    queryKey: ["ransomware", "victims", page, group, country, industry],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/victims", {
        params: {
          query: {
            page,
            page_size: VICTIM_PAGE_SIZE,
            group: group || undefined,
            country: country || undefined,
            industry: industry || undefined,
          },
        },
      });
      if (error) throw error;
      return data as unknown as { victims: Victim[]; total: number };
    },
  });
}

function useRwArticles(page: number) {
  return useQuery({
    queryKey: ["ransomware", "articles", page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/related-articles", {
        params: { query: { page, page_size: ARTICLE_PAGE_SIZE } },
      });
      if (error) throw error;
      return data as unknown as { articles: Article[]; total: number };
    },
  });
}

/** Port panel "Ransomware Activity" (`tab_newsroom.html`) -- 2 sub-section
 * independen: tabel live victims (`ransomware.live`, mini-filter sendiri
 * group/country/industry, gak nyentuh filter bar global) + artikel
 * terkait (`related-articles`, tanpa filter apa pun, port apa adanya). */
export function RansomwarePanel({ onSelect }: { onSelect: (a: Article) => void }) {
  const [victimPage, setVictimPage] = useState(1);
  const [group, setGroup] = useState("");
  const [country, setCountry] = useState("");
  const [industry, setIndustry] = useState("");
  const [appliedFilter, setAppliedFilter] = useState({ group: "", country: "", industry: "" });
  const [articlePage, setArticlePage] = useState(1);

  const victims = useVictims(victimPage, appliedFilter.group, appliedFilter.country, appliedFilter.industry);
  const articles = useRwArticles(articlePage);

  const victimTotalPages = victims.data ? Math.ceil(victims.data.total / VICTIM_PAGE_SIZE) : 0;
  const articleTotalPages = articles.data ? Math.ceil(articles.data.total / ARTICLE_PAGE_SIZE) : 0;

  function applyVictimFilter() {
    setAppliedFilter({ group, country, industry });
    setVictimPage(1);
  }

  return (
    <PanelShell
      title="Ransomware Activity"
      count={articles.data?.total}
      onRefresh={() => {
        void victims.refetch();
        void articles.refetch();
      }}
      isRefreshing={victims.isFetching || articles.isFetching}
    >
      <div className="mb-3">
        <div className="mb-1.5 border-b border-border pb-1 text-sm font-semibold text-muted-foreground">
          Live victims from ransomware.live
        </div>
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <Input
            aria-label="Filter victims by group"
            placeholder="Group…"
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            className="w-24 font-mono text-[13px]"
          />
          <Input
            aria-label="Filter victims by country"
            placeholder="Country…"
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="w-24 font-mono text-[13px]"
          />
          <Input
            aria-label="Filter victims by industry"
            placeholder="Industry…"
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="w-28 font-mono text-[13px]"
          />
          <Button size="sm" onClick={applyVictimFilter}>
            Filter
          </Button>
        </div>
        <div className="grid grid-cols-[80px_1fr_76px_16px] gap-1 border-b border-border pb-1 text-sm font-semibold text-muted-foreground">
          <span>Group</span>
          <span>Victim / Industry</span>
          <span>Published / Disc.</span>
          <span />
        </div>
        <div className="max-h-[280px] overflow-y-auto">
          {victims.isPending && <PanelLoading />}
          {victims.isError && <PanelError />}
          {victims.data && victims.data.victims.length === 0 && <PanelEmpty message="No victims found" />}
          {victims.data?.victims.map((v) => <VictimRow key={v.id} v={v} />)}
        </div>
        <div className="mt-1 flex justify-center">
          <SimplePager page={victimPage} totalPages={victimTotalPages} onPageChange={setVictimPage} />
        </div>
      </div>

      <div className="mb-1.5 border-t border-b border-border py-1 text-sm font-semibold text-muted-foreground">
        Related Articles
      </div>
      {articles.isPending && <PanelLoading />}
      {articles.isError && <PanelError />}
      {articles.data && articles.data.articles.length === 0 && (
        <PanelEmpty message="No related ransomware articles" />
      )}
      {articles.data && articles.data.articles.length > 0 && (
        <ArticleCollection articles={articles.data.articles} layout="list" onSelect={onSelect} />
      )}
      <div className="mt-2">
        <SimplePager page={articlePage} totalPages={articleTotalPages} onPageChange={setArticlePage} />
      </div>
    </PanelShell>
  );
}
