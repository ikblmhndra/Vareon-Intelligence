"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/components/providers/auth-provider";
import { TabPills, type TabPillItem } from "@/components/ui/tab-pills";
import { defaultNewsroomFilters, type NewsroomFilters } from "@/lib/newsroom/filters";
import type { components } from "@/lib/api/schema";
import { ArticleModal } from "@/components/newsroom/article-modal";
import { ArticleListSheet } from "@/components/newsroom/article-list-sheet";
import { FilteredView } from "@/components/newsroom/filtered-view";
import { FrontSection, useFrontQuery } from "@/components/newsroom/front-section";
import { Masthead } from "@/components/newsroom/masthead";
import { Rubric } from "@/components/newsroom/rubric";
import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { TopicsStrip } from "@/components/newsroom/topics-strip";

type Article = components["schemas"]["ArticleOut"];
type SheetSource = { rubric: RubricKey } | { actor: string } | { ttp: string };

const RUBRIC_TITLES: Record<RubricKey, string> = {
  apac: "APAC",
  global: "Global",
  local: "Local",
  ransomware: "Ransomware",
  watchlist: "Watchlist",
  techstack: "Tech stack",
};

function isRubricKey(v: string | null): v is RubricKey {
  return v !== null && v in RUBRIC_TITLES;
}

/**
 * Newsroom: masthead + filter, halaman depan (4 artikel prioritas), topik aktif,
 * lalu rubrik. Filter berlaku langsung (tanpa Apply). Dashboard menaut ke sini
 * lewat `?country=XX` dan `?rubric=ransomware|watchlist`, dibaca sekali saat
 * dimuat; `rubric` langsung membuka daftar lengkapnya.
 *
 * Auto-refresh countdown legacy (`autorefresh.js`) sengaja tidak diport; tiap
 * query di-refetch lewat react-query.
 */
function NewsroomContent() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const searchParams = useSearchParams();

  const [view, setView] = useState<"cyber" | "filtered">("cyber");
  const [filters, setFilters] = useState<NewsroomFilters>(() => ({
    ...defaultNewsroomFilters(),
    country: searchParams.get("country")?.toUpperCase() || null,
  }));
  const [selected, setSelected] = useState<Article | null>(null);
  const [sheet, setSheet] = useState<{ open: boolean; title: string; source: SheetSource }>(() => {
    const r = searchParams.get("rubric");
    return isRubricKey(r)
      ? { open: true, title: RUBRIC_TITLES[r], source: { rubric: r } }
      : { open: false, title: "", source: { rubric: "apac" } };
  });
  const front = useFrontQuery(filters);

  // Tab "Filtered Articles" (ditolak klasifikasi + gagal di-enrich) hanya untuk admin.
  const viewTabs: TabPillItem<"cyber" | "filtered">[] = [
    { value: "cyber", label: "Cyber News" },
    ...(isAdmin ? [{ value: "filtered" as const, label: "Filtered Articles", tone: "destructive" as const }] : []),
  ];

  function openRubric(rubric: RubricKey) {
    setSheet({ open: true, title: RUBRIC_TITLES[rubric], source: { rubric } });
  }

  function rubric(key: RubricKey, hideWhenEmpty?: boolean) {
    return (
      <Rubric
        rubric={key}
        title={RUBRIC_TITLES[key]}
        filters={filters}
        onSelect={setSelected}
        onSeeAll={() => openRubric(key)}
        hideWhenEmpty={hideWhenEmpty}
      />
    );
  }

  return (
    <div className="pb-10">
      <TabPills
        aria-label="Newsroom views"
        className="mb-4 border-b border-border pb-3"
        items={viewTabs}
        value={view}
        onChange={setView}
      />

      {view === "cyber" ? (
        <>
          <Masthead filters={filters} onChange={setFilters} total={front.data?.total} />
          <FrontSection filters={filters} onSelect={setSelected} />
          <TopicsStrip
            filters={filters}
            onOpen={(source, title) => setSheet({ open: true, title, source })}
          />
          <div className="grid grid-cols-1 gap-x-6 gap-y-8 md:grid-cols-2 lg:grid-cols-4">
            {rubric("apac")}
            {rubric("global")}
            {rubric("local")}
            {rubric("ransomware")}
          </div>
          <div className="mt-8 grid grid-cols-1 gap-x-6 gap-y-8 md:grid-cols-2">
            {rubric("watchlist", true)}
            {rubric("techstack", true)}
          </div>
          <ArticleListSheet
            open={sheet.open}
            onOpenChange={(open) => setSheet((s) => ({ ...s, open }))}
            title={sheet.title}
            source={sheet.source}
            filters={filters}
            onSelect={setSelected}
          />
        </>
      ) : (
        <FilteredView />
      )}

      <ArticleModal article={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}

export default function NewsroomPage() {
  // `useSearchParams` butuh Suspense supaya halaman tetap bisa di-prerender.
  return (
    <Suspense>
      <NewsroomContent />
    </Suspense>
  );
}
