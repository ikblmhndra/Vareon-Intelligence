"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useDashboardStats } from "@/components/dashboard/use-dashboard-overview";
import { AllArticlesView } from "@/components/newsroom/all-articles-view";
import { FilterBar } from "@/components/newsroom/filter-bar";
import { FilteredView } from "@/components/newsroom/filtered-view";
import { FrontPage } from "@/components/newsroom/front-page";
import { useArticleCount, useNarrowing } from "@/components/newsroom/newsroom-queries";
import type { RubricKey } from "@/components/newsroom/rubric-queries";
import { RubricGrid } from "@/components/newsroom/rubric-grid";
import { TopicsSection } from "@/components/newsroom/topics-section";
import { PageHeader } from "@/components/page-header";
import { useAuth } from "@/components/providers/auth-provider";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { normalizeCountry } from "@/lib/dashboard/countries";
import { fmtShortDate } from "@/lib/format";
import {
  allStateToParams,
  isAllViewUrl,
  newsroomAllHref,
  parseAllState,
  validFromParam,
  type AllState,
} from "@/lib/newsroom/all-state";
import {
  newsroomPeriodInfo,
  parseNewsroomPeriod,
  uiToFilters,
  type NewsroomUi,
} from "@/lib/newsroom/period";

const VIEW_OPTIONS = [
  { value: "front", label: "Front page" },
  { value: "all", label: "All articles" },
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
  const can = useCan();

  // Tampilan turunan: tanpa `view`, tautan lama (article/rubric/actor/...) mendarat di All articles tanpa redirect.
  const viewParam = sp.get("view");
  const view = viewParam === "filtered" ? "filtered" : isAllViewUrl(sp) ? "all" : "front";
  // Periode, from, negara dibaca dari URL tiap render: URL satu-satunya sumber.
  const period = parseNewsroomPeriod(sp.get("period"));
  const from = validFromParam(sp.get("from"));
  const rawCountry = sp.get("country")?.trim();
  const country = rawCountry ? normalizeCountry(rawCountry) : null;

  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [incidentOnly, setIncidentOnly] = useState(false);
  const [rubric, setRubric] = useState<RubricKey | null>(null);
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
  // Tampilan All articles tidak memakai hitungan header Front page: "pending" mematikan query.
  const count = useArticleCount(view === "all" ? "pending" : narrowing);
  const info = newsroomPeriodInfo(period);
  const stats = useDashboardStats(info.days, incidentOnly);

  /** Satu-satunya penulis URL: `replace` hanya bila URL berubah (tidak pernah ke URL yang sama). */
  function replaceParams(next: URLSearchParams) {
    const qs = next.toString();
    const href = pathname + (qs ? "?" + qs : "");
    if (href === pathname + (sp.toString() ? "?" + sp.toString() : "")) return;
    router.replace(href, { scroll: false });
  }

  /** Salin param, terapkan patch, lalu tulis lewat `replaceParams`. */
  function writeParams(patch: Record<string, string | null>) {
    const next = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    replaceParams(next);
  }

  // Rubrik yang tidak boleh dilihat pemakai (izin backend) dianggap null (All news), tanpa request.
  const allState: AllState = useMemo(() => {
    const s = parseAllState(new URLSearchParams(sp.toString()));
    const r = s.rubric;
    const allowed =
      r === "ransomware" ? can("view_intel") : r === "techstack" ? can("view_cve") : r === "watchlist" ? can("view_ta") : true;
    return allowed ? s : { ...s, rubric: null };
  }, [sp, can]);

  /** Tulis patch state All articles; `allStateToParams` mempertahankan `view` dan param lain. */
  function onAllChange(patch: Partial<AllState>) {
    const next = allStateToParams(patch, new URLSearchParams(sp.toString()));
    // Di URL turunan (mis. `?actor=Qilin`) menghapus param tautan terakhir akan menjatuhkan tampilan ke
    // Front page; tulis `view=all` eksplisit (hanya pada aksi pemakai, bukan saat mount).
    if (!next.has("view")) next.set("view", "all");
    replaceParams(next);
  }

  /** Periode, negara, pencarian, dan insiden Front page dibawa ke All articles (`from` menang atas `period`). */
  const carry = (): Partial<AllState> => ({
    ...(from ? { from } : { period }),
    countries: country ? [country] : [],
    q: search,
    incidents: incidentOnly,
  });
  /** Hanya periode dan negara (tautan "See all" rubrik): rubrik punya hitungan sendiri. */
  const carryScope = (): Partial<AllState> => ({
    ...(from ? { from } : { period }),
    countries: country ? [country] : [],
  });
  const go = (href: string) => router.push(href);

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
    if (p.search !== undefined) {
      setSearchText(p.search);
      setSearch(p.search);
    }
    if (p.incidentOnly !== undefined) setIncidentOnly(p.incidentOnly);
    if (p.rubric !== undefined) setRubric(p.rubric);
  }

  const suffix = from ? `since ${fmtShortDate(from)}` : info.suffix;
  const sources =
    !search && !country && !from && !rubric && stats.data ? stats.data.total_sources : undefined;
  const n = count.data;
  const plural = (k: number, word: string) => `${k.toLocaleString("en-US")} ${word}${k === 1 ? "" : "s"}`;
  // Skeleton selagi hitungan dimuat; tanpa query artikel (Ransomware, no-names, galat nama) atau galat = baris dihilangkan.
  const hasQuery = typeof narrowing === "object" && !("namesError" in narrowing);
  const description = !hasQuery ? undefined : n === undefined ? (
    count.isPending && count.fetchStatus !== "idle" ? <Skeleton aria-hidden className="h-5 w-80 max-w-full" /> : undefined
  ) : (
    `${plural(n, "cyber article")}${sources !== undefined ? ` from ${plural(sources, "source")}` : ""} ${suffix}`
  );

  return (
    <div className="pb-10">
      <PageHeader
        kicker="NEWSROOM"
        title="Newsroom"
        description={view === "all" ? undefined : description}
        actions={
          <SegmentedControl
            aria-label="Newsroom view"
            options={VIEW_OPTIONS}
            value={view}
            onChange={(v) => {
              if (v === "front") {
                // Dengan param tautan lama, tanpa `view` tampilan turun ke All articles; tulis `front` eksplisit.
                const bare = new URLSearchParams(sp.toString());
                bare.delete("view");
                writeParams({ view: isAllViewUrl(bare) ? "front" : null });
              } else writeParams({ view: v });
            }}
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
              openArticle={(a) => go(newsroomAllHref({ ...carry(), article: a.id }))}
              // Anggota cerita bisa di luar periode (perilaku sheet lama): semua waktu, tanpa filter lain.
              onOpenStory={(story) => go(newsroomAllHref({ story, period: "all" }))}
            />
            <TopicsSection
              filters={filters}
              words={info.words}
              since={from ? fmtShortDate(from) : undefined}
              onOpen={(t) =>
                go(
                  newsroomAllHref({
                    ...carry(),
                    sort: "recent",
                    ...("actor" in t ? { actors: [t.actor] } : { ttps: [t.ttp] }),
                  }),
                )
              }
            />
            <RubricGrid
              filters={filters}
              rubric={rubric}
              openArticle={(a) => go(newsroomAllHref({ ...carry(), article: a.id }))}
              onSeeAll={(key) => go(newsroomAllHref({ ...carryScope(), rubric: key, sort: "recent" }))}
            />
          </div>
        </>
      ) : view === "all" ? (
        <AllArticlesView state={allState} onChange={onAllChange} />
      ) : (
        <FilteredView />
      )}
    </div>
  );
}
