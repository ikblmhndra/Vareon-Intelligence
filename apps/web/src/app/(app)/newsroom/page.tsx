"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { TabPills, type TabPillItem } from "@/components/ui/tab-pills";
import { parseLocalDate } from "@/lib/format";
import { defaultNewsroomFilters, periodStart, type NewsroomFilters } from "@/lib/newsroom/filters";
import type { components } from "@/lib/api/schema";
import { ArticleModal } from "@/components/newsroom/article-modal";
import { ArticleListSheet, type SheetQuery, type Source as SheetSource } from "@/components/newsroom/article-list-sheet";
import { FilteredView } from "@/components/newsroom/filtered-view";
import { FrontSection, useFrontQuery } from "@/components/newsroom/front-section";
import { Masthead } from "@/components/newsroom/masthead";
import { Rubric } from "@/components/newsroom/rubric";
import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { TopicsStrip } from "@/components/newsroom/topics-strip";
import { useCan } from "@/lib/auth/permissions";

type Article = components["schemas"]["ArticleOut"];

const RUBRIC_TITLES: Record<RubricKey, string> = {
  apac: "APAC",
  global: "Global",
  local: "Local",
  ransomware: "Ransomware",
  watchlist: "Watchlist",
  techstack: "Tech stack",
};

/** Judul sheet; Ransomware berisi daftar korban (bukan artikel), jadi judulnya menyebut itu. */
function sheetTitle(r: RubricKey): string {
  return r === "ransomware" ? "Korban ransomware" : RUBRIC_TITLES[r];
}

function isRubricKey(v: string | null): v is RubricKey {
  return v !== null && v in RUBRIC_TITLES;
}

/** `?period=` dari dashboard: hanya 1|7|30 (chip yang ada); nilai lain diabaikan (default 7). */
const URL_PERIODS = new Set(["1", "7", "30"]);

/** `?from=YYYY-MM-DD`: harus tanggal lokal yang valid (2026-13-40 atau 2026-02-30 ditolak, bukan digeser). */
function validFrom(v: string | null): string | null {
  if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = parseLocalDate(v);
  const [y, m, day] = v.split("-").map(Number);
  // Date menggeser tanggal tak ada (30 Feb -> 2 Mar), jadi cocokkan balik komponennya.
  const ok = d.getFullYear() === y && d.getMonth() + 1 === m && d.getDate() === day;
  return ok ? v : null;
}

/** Nilai param tak kosong (setelah trim); `actor=` dan spasi saja diabaikan. */
function paramValues(sp: URLSearchParams, key: string): string[] {
  return sp.getAll(key).map((v) => v.trim()).filter(Boolean);
}

/** Tautan Intelligence: aktor/industri/TTP membuka sheet gabungan; `country` sendirian tetap filter masthead. */
function linkedSheet(sp: URLSearchParams, dateStart: string): { title: string; source: SheetSource } | null {
  const actors = paramValues(sp, "actor");
  const industries = paramValues(sp, "industry");
  const ttps = paramValues(sp, "ttp");
  if (!actors.length && !industries.length && !ttps.length) return null;
  const country = (sp.get("country")?.trim().toUpperCase() ?? "") || null;
  const query: SheetQuery = {
    threat_actor: actors.length ? actors : undefined,
    industry: industries.length ? industries : undefined,
    ttp: ttps.length ? ttps : undefined,
    country: country ? [country] : undefined,
    posted_on_start: dateStart || undefined,
  };
  return { title: [...actors, ...industries, ...ttps].join(" × "), source: { query } };
}

/**
 * Newsroom: masthead + filter, halaman depan (4 artikel prioritas), topik aktif,
 * lalu rubrik. Filter berlaku langsung (tanpa Apply). Dashboard menaut ke sini
 * lewat `?country=XX`, `?rubric=ransomware|watchlist` dan `?period=1|7|30`, dibaca
 * sekali saat dimuat; `rubric` langsung membuka daftar lengkapnya dan `period`
 * memilih chip periode. Tautan Intelligence memakai `actor`, `industry`, `ttp` (berulang) dan
 * `from=YYYY-MM-DD` (menang atas `period`): sheet gabungan terbuka dengan jumlah yang sama
 * dengan halaman sumber (lihat `lib/newsroom/links.ts`).
 *
 * Auto-refresh countdown legacy (`autorefresh.js`) sengaja tidak diport; tiap
 * query di-refetch lewat react-query.
 */
function NewsroomContent() {
  const can = useCan();
  // Tab Filtered Articles hanya berguna bagi yang boleh Restore, Accept atau Retry.
  const isAdmin = can("manage_sources") || can("manage_scraper");
  const searchParams = useSearchParams();

  // `from` valid menang atas `period` (1|7|30); null bila tak satu pun ada/valid.
  const urlFrom = validFrom(searchParams.get("from"));
  const urlPeriod = searchParams.get("period");
  const urlDateStart =
    urlFrom ?? (urlPeriod && URL_PERIODS.has(urlPeriod) ? periodStart(Number(urlPeriod)) : null);

  const [view, setView] = useState<"cyber" | "filtered">("cyber");
  const [filters, setFilters] = useState<NewsroomFilters>(() => {
    const base = defaultNewsroomFilters();
    return {
      ...base,
      dateStart: urlDateStart ?? base.dateStart,
      country: searchParams.get("country")?.toUpperCase() || null,
    };
  });
  const [selected, setSelected] = useState<Article | null>(null);
  const [sheet, setSheet] = useState<{ open: boolean; title: string; source: SheetSource }>(() => {
    const linked = linkedSheet(searchParams, urlDateStart ?? "");
    if (linked) return { open: true, ...linked };
    const r = searchParams.get("rubric");
    return isRubricKey(r)
      ? { open: true, title: sheetTitle(r), source: { rubric: r } }
      : { open: false, title: "", source: { rubric: "apac" } };
  });
  const front = useFrontQuery(filters);

  // Tab "Filtered Articles" (ditolak klasifikasi + gagal di-enrich) hanya untuk admin.
  const viewTabs: TabPillItem<"cyber" | "filtered">[] = [
    { value: "cyber", label: "Cyber News" },
    ...(isAdmin ? [{ value: "filtered" as const, label: "Filtered Articles", tone: "destructive" as const }] : []),
  ];

  function openRubric(rubric: RubricKey) {
    setSheet({ open: true, title: sheetTitle(rubric), source: { rubric } });
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
          <FrontSection
            filters={filters}
            onSelect={setSelected}
            onOpenStory={(story, title) => setSheet({ open: true, title, source: { story } })}
          />
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
