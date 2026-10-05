"use client";

import { useState } from "react";

import { useAuth } from "@/components/providers/auth-provider";
import { cn } from "@/lib/utils";
import { defaultNewsroomFilters, type NewsroomFilters } from "@/lib/newsroom/filters";
import type { components } from "@/lib/api/schema";
import { FilterBar } from "@/components/newsroom/filter-bar";
import { ArticleModal } from "@/components/newsroom/article-modal";
import { FilteredView } from "@/components/newsroom/filtered-view";
import { NewsTypePanel } from "@/components/newsroom/panels/news-type-panel";
import { RansomwarePanel } from "@/components/newsroom/panels/ransomware-panel";
import { LocalPanel } from "@/components/newsroom/panels/local-panel";
import { WatchlistPanel } from "@/components/newsroom/panels/watchlist-panel";
import { TechStackPanel } from "@/components/newsroom/panels/techstack-panel";

type Article = components["schemas"]["ArticleOut"];

const GLOBAL_NEWS_TYPES = [
  "global",
  "Security Technology & Best Practices",
  "Vendor Report Article",
  "Data Breach Article",
  "Tech Stack Article",
  "OT Article",
];

/**
 * Port `tab_newsroom.html` + `{core,api,tabs,render,modal,ttp}.js` --
 * gak ada file lama sendiri, logic-nya tersebar 7 file (survei Fase 8,
 * "Besar | Newsroom (gak ada file sendiri) | tersebar"). 6 panel + 2
 * sub-view.
 *
 * **Filter bar SCOPE `/newsroom` doang** -- legacy nge-share SATU filter
 * bar antara tab Dashboard dan Newsroom (`applyFilters()` manggil
 * `loadDashboard()` juga kalau lagi di tab itu). Di app baru itu 2 route
 * TERPISAH; nyambungin filter state lintas-route butuh arsitektur baru
 * (URL search params atau store di layout `(app)`) yang belum ada
 * keputusannya -- dicatat sebagai gap eksplisit di docs/PROGRESS.md,
 * BUKAN diselesaikan diam-diam di sini. `/dashboard` (Grup B) tetap
 * unfiltered untuk sekarang.
 *
 * **Auto-refresh countdown (`autorefresh.js`) SENGAJA gak diport** --
 * chrome "nice to have", tiap panel udah punya tombol refresh manual
 * sendiri (core requirement). Admiralty/source-reliability badge di
 * kartu artikel juga belum (`/intelligence` Source Reliability, Grup G).
 */
export default function NewsroomPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";

  const [view, setView] = useState<"cyber" | "filtered">("cyber");
  const [draft, setDraft] = useState<NewsroomFilters>(defaultNewsroomFilters);
  const [filters, setFilters] = useState<NewsroomFilters>(defaultNewsroomFilters);
  const [selected, setSelected] = useState<Article | null>(null);

  return (
    <div className="pb-10">
      <div className="mb-4 flex gap-1.5 border-b border-border pb-3 overflow-x-auto">
        <button
          onClick={() => setView("cyber")}
          className={cn(
            "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
            view === "cyber"
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          Cyber News
        </button>
        {isAdmin && (
          <button
            onClick={() => setView("filtered")}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              view === "filtered"
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            Not Related Cyber
          </button>
        )}
      </div>

      {view === "cyber" ? (
        <>
          <FilterBar
            draft={draft}
            onDraftChange={setDraft}
            // Objek BARU tiap Apply (walau nilainya sama) -- panel reset ke
            // page 1 berdasarkan identitas `filters` (`usePageResetOn`).
            onApply={() => setFilters({ ...draft })}
            onReset={() => setFilters(defaultNewsroomFilters())}
          />

          <div className="space-y-3">
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <NewsTypePanel
                title="APAC News"
                dotClassName="bg-primary shadow-[0_0_6px_var(--primary)]"
                newsType={["apac"]}
                filters={filters}
                onSelect={setSelected}
              />
              <NewsTypePanel
                title="Global News"
                dotClassName="bg-ring shadow-[0_0_6px_var(--ring)]"
                newsType={GLOBAL_NEWS_TYPES}
                filters={filters}
                onSelect={setSelected}
              />
              <RansomwarePanel onSelect={setSelected} />
            </div>

            <LocalPanel filters={filters} onSelect={setSelected} />
            <WatchlistPanel filters={filters} onSelect={setSelected} />
            <TechStackPanel filters={filters} onSelect={setSelected} />
          </div>
        </>
      ) : (
        <FilteredView />
      )}

      <ArticleModal article={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}
