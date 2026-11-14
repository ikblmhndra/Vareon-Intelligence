"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useArticleOpener } from "@/components/dashboard/article-opener";
import { useDashboardStats } from "@/components/dashboard/use-dashboard-overview";
import { ArticleListSheet, type SheetQuery, type Source as SheetSource } from "@/components/newsroom/article-list-sheet";
import { FilterBar } from "@/components/newsroom/filter-bar";
import { FilteredView } from "@/components/newsroom/filtered-view";
import { FrontPage } from "@/components/newsroom/front-page";
import { useArticleCount, useNarrowing } from "@/components/newsroom/newsroom-queries";
import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { RubricGrid } from "@/components/newsroom/rubric-grid";
import { TopicsSection } from "@/components/newsroom/topics-section";
import { PageHeader } from "@/components/page-header";
import { useAuth } from "@/components/providers/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { normalizeCountry } from "@/lib/dashboard/countries";
import { fmtShortDate, parseLocalDate } from "@/lib/format";
import { periodStart } from "@/lib/newsroom/filters";
import {
  newsroomPeriodInfo,
  parseNewsroomPeriod,
  uiToFilters,
  type NewsroomUi,
} from "@/lib/newsroom/period";

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
  return r === "ransomware" ? "Ransomware victims" : RUBRIC_TITLES[r];
}

function isRubricKey(v: string | null): v is RubricKey {
  return v !== null && v in RUBRIC_TITLES;
}

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

/** Tautan Intelligence: aktor/industri/TTP membuka sheet gabungan; `country` sendirian tetap filter halaman. */
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

const VIEW_OPTIONS = [
  { value: "front", label: "Front page" },
  { value: "filtered", label: "Filtered" },
] as const;

/** Cangkang Newsroom 5b: gerbang view_news; isi baru dipasang (dan query jalan) bila diizinkan. */
export function NewsroomView() {
  const can = useCan();
  const { user } = useAuth();
  if (!can("view_news")) {
    return (
      <div className="pb-10">
        <PageHeader kicker="NEWSROOM" title="Newsroom" />
        <StatePanel
          variant="no-access"
          title="Newsroom needs the view_news permission"
          description={`Your role (${user?.role ?? "unknown"}) does not have it.`}
        />
      </div>
    );
  }
  return <NewsroomBody />;
}

function NewsroomBody() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const { openArticle, host } = useArticleOpener();

  const view = sp.get("view") === "filtered" ? "filtered" : "front";
  // Periode, from, negara dibaca dari URL tiap render: URL satu-satunya sumber.
  const period = parseNewsroomPeriod(sp.get("period"));
  const from = validFrom(sp.get("from"));
  const rawCountry = sp.get("country")?.trim();
  const country = rawCountry ? normalizeCountry(rawCountry) : null;

  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [incidentOnly, setIncidentOnly] = useState(false);
  const [rubric, setRubric] = useState<RubricKey | null>(null);
  // Deep link dibaca sekali saat dimuat (initializer); menutup sheet tidak menyentuh URL.
  const [sheet, setSheet] = useState<{ open: boolean; title: string; source: SheetSource }>(() => {
    const dateStart =
      validFrom(sp.get("from")) ??
      (sp.get("period") ? periodStart(newsroomPeriodInfo(parseNewsroomPeriod(sp.get("period"))).days ?? 0) : "");
    const linked = linkedSheet(sp, dateStart);
    if (linked) return { open: true, ...linked };
    const r = sp.get("rubric");
    return isRubricKey(r)
      ? { open: true, title: sheetTitle(r), source: { rubric: r } }
      : { open: false, title: "", source: { rubric: "apac" } };
  });

  // Debounce 300 ms; setState hanya di callback timer.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(t);
  }, [searchText]);

  const ui: NewsroomUi = useMemo(
    () => ({ period, from, country, search, incidentOnly, rubric }),
    [period, from, country, search, incidentOnly, rubric],
  );
  // `uiToFilters` membaca jam: hitung hanya saat masukan berubah, bukan tiap render.
  const filters = useMemo(
    () => uiToFilters({ period, from, country, search, incidentOnly, rubric: null }),
    [period, from, country, search, incidentOnly],
  );
  const narrowing = useNarrowing(rubric, filters);
  const count = useArticleCount(narrowing);
  const info = newsroomPeriodInfo(period);
  const stats = useDashboardStats(info.days, incidentOnly);

  /** Satu-satunya penulis URL: salin param, terapkan patch, `replace` hanya bila URL berubah. */
  function writeParams(patch: Record<string, string | null>) {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    const href = pathname + (qs ? "?" + qs : "");
    if (href === pathname + (sp.toString() ? "?" + sp.toString() : "")) return;
    router.replace(href, { scroll: false });
  }

  function onChange(p: Partial<NewsroomUi>) {
    const patch: Record<string, string | null> = {};
    // Memilih ulang pilihan yang sama bukan perubahan (kecuali `from` ada: memilih periode melepasnya).
    if (p.period !== undefined && (p.period !== period || from)) {
      patch.period = p.period === "7" ? null : p.period;
      patch.from = null;
    }
    if (p.from !== undefined) patch.from = p.from;
    if (p.country !== undefined && p.country !== country) patch.country = p.country;
    if (Object.keys(patch).length) writeParams(patch);
    if (p.incidentOnly !== undefined) setIncidentOnly(p.incidentOnly);
    if (p.rubric !== undefined) setRubric(p.rubric);
  }

  const suffix = from ? `since ${fmtShortDate(from)}` : info.suffix;
  const sources =
    !search && !country && !from && stats.data ? stats.data.total_sources : undefined;
  const n = count.data;
  // Skeleton selagi hitungan dimuat; galat atau tanpa query (no-names) = baris dihilangkan.
  const description =
    n === undefined ? (
      count.isPending && count.fetchStatus !== "idle" ? (
        <Skeleton aria-hidden className="h-5 w-80 max-w-full" />
      ) : undefined
    ) : (
      `${n.toLocaleString("en-US")} cyber articles${
          sources !== undefined ? ` from ${sources.toLocaleString("en-US")} sources` : ""
        } ${suffix}`
    );

  return (
    <div className="pb-10">
      <PageHeader
        kicker="NEWSROOM"
        title="Newsroom"
        description={description}
        actions={
          <SegmentedControl
            aria-label="Newsroom view"
            options={VIEW_OPTIONS}
            value={view}
            onChange={(v) => writeParams({ view: v === "filtered" ? "filtered" : null })}
          />
        }
      />
      {view === "front" ? (
        <>
          <FilterBar ui={ui} searchText={searchText} onSearchText={setSearchText} onChange={onChange} />
          <div className="space-y-8">
            <FrontPage
              ui={ui}
              filters={filters}
              narrowing={narrowing}
              onChange={onChange}
              openArticle={openArticle}
              onOpenStory={(story, title) => setSheet({ open: true, title, source: { story } })}
            />
            <TopicsSection
              filters={filters}
              words={info.words}
              onOpen={(source, title) => setSheet({ open: true, title, source })}
            />
            <RubricGrid
              filters={filters}
              rubric={rubric}
              openArticle={openArticle}
              onSeeAll={(key) => setSheet({ open: true, title: sheetTitle(key), source: { rubric: key } })}
            />
          </div>
          <ArticleListSheet
            open={sheet.open}
            onOpenChange={(open) => setSheet((s) => ({ ...s, open }))}
            title={sheet.title}
            source={sheet.source}
            filters={filters}
            onSelect={openArticle}
          />
        </>
      ) : (
        <FilteredView />
      )}
      {host}
    </div>
  );
}
