"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api/client";
import type { TaStats } from "@/lib/api/loose-types";
import { ChartCard, DashboardSectionLabel, Delta, MapCard, StatBox } from "@/components/dashboard/stat-box";
import { SignalHero } from "@/components/dashboard/signal-hero";
import { BreakdownList } from "@/components/dashboard/breakdown-list";
import { HorizontalBarChart, TimelineChart } from "@/components/dashboard/charts";
import {
  DEFAULT_DASHBOARD_FILTERS,
  DashboardFilterBar,
  type DashboardFilters,
} from "@/components/dashboard/dashboard-filters";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";

function toTitleCase(s: string): string {
  return s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1));
}

function useDashboardStats(filters: DashboardFilters) {
  return useQuery({
    queryKey: ["dashboard", "stats", filters.days, filters.incidentOnly],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/dashboard", {
        params: { query: { days: filters.days ?? undefined, incident_only: filters.incidentOnly } },
      });
      if (error) throw error;
      return data;
    },
    // Ganti periode/toggle: tetap tampilkan angka lama (diredupkan) sampai yang baru datang,
    // bukan mengosongkan semua kartu lalu menggambar ulang.
    placeholderData: keepPreviousData,
  });
}

function useTaStats() {
  return useQuery({
    queryKey: ["dashboard", "ta-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/stats");
      if (error) throw error;
      return data as unknown as TaStats;
    },
  });
}

/**
 * Port `legacy/static/js/newsroom/dashboard.js` + `tab_dashboard.html`.
 * 2 fetch paralel (`/api/dashboard`, `/api/ta/stats`) jadi 2 `useQuery`
 * independen (bukan `Promise.all` kayak lama) -- tiap section render
 * begitu datanya sendiri siap, gak nunggu yang paling lambat.
 *
 * Scraper Health widget (§Scraper Health lama, accept-rate chart + tabel
 * per-script) SENGAJA GAK diport ke sini walau `/api/scraper/health` udah
 * ada (Fase 9) -- keputusan user (2026-09-25): control plane scraper
 * dapet halaman SENDIRI (`/scrapers`), bukan digabung ke dashboard umum.
 *
 * Susunan visual (hierarki permukaan): band burgundy = hero; satu panel KPI raised dengan
 * lima angka datar; chart/peta raised dalam grid 12 kolom asimetris (peta lebih lebar dari
 * daftarnya, TTP lebih lebar dari industri karena labelnya panjang); daftar angka datar.
 */
export default function DashboardPage() {
  const [filters, setFilters] = useState<DashboardFilters>(DEFAULT_DASHBOARD_FILTERS);
  const dashboard = useDashboardStats(filters);
  const ta = useTaStats();

  const stats = dashboard.data;
  const periodLabel = filters.days ? `Last ${filters.days} days` : "All time";
  const prevLabel = filters.days ? `${filters.days}d` : "";
  // Penyebut chart: cuma sebagian artikel yang punya negara/aktor/TTP, jadi sebut basisnya.
  const basis = (n: number | undefined, what: string) =>
    stats && n !== undefined ? `${n.toLocaleString()} of ${stats.total_articles.toLocaleString()} articles ${what}` : undefined;

  return (
    <div className="pb-10">
      <PageHeader
        title="Dashboard"
        description="News coverage, incidents, threat actors and ATT&CK techniques for the selected period."
        actions={<DashboardFilterBar filters={filters} onChange={setFilters} updatedAt={stats?.generated_at} />}
      />

      <SignalHero days={filters.days} />

      {/* ── KPI ── */}
      {dashboard.isPending && <Skeleton className="mt-6 h-28 w-full rounded-2xl" />}
      {dashboard.isError && <ErrorNote />}
      {/* Statistik Threat Actor gagal tidak boleh menghapus KPI artikel: dua kartu TA menulis "—". */}
      {stats && (
        <div
          className={`surface-raised mt-6 grid grid-cols-1 divide-y divide-border/70 rounded-2xl p-2 transition-opacity sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-[1.35fr_1fr_1fr_1fr_1fr] xl:divide-x ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <StatBox
            flat
            emphasis
            label="Total Articles"
            value={stats.total_articles}
            sub={
              <>
                {periodLabel}
                {filters.incidentOnly ? " · incidents only" : ""}
                <Delta
                  value={stats.total_articles}
                  prev={stats.prev_total_articles}
                  label={prevLabel}
                  reliable={stats.prev_period_reliable}
                />
              </>
            }
            spark={stats.timeline.map((x) => x.count)}
          />
          <StatBox
            flat
            label="Confirmed Incidents"
            value={stats.confirmed_incidents}
            sub={
              <>
                of {stats.total_articles.toLocaleString()} articles
                <Delta
                  value={stats.confirmed_incidents}
                  prev={stats.prev_confirmed_incidents}
                  label={prevLabel}
                  reliable={stats.prev_period_reliable}
                />
              </>
            }
          />
          <StatBox flat label="Countries Mentioned" value={stats.total_countries} sub="Unique geographies" />
          <StatBox
            flat
            label="Threat Actors in News"
            value={stats.total_threat_actors}
            sub={
              ta.data
                ? `${ta.data.total_groups.toLocaleString()} APT groups · ${ta.data.total_whitelisted} whitelisted`
                : taSub(ta.isError)
            }
          />
          <StatBox
            flat
            label="Covered in News"
            value={ta.data?.in_news_count}
            sub={ta.data ? `${ta.data.manual_count} added manually` : taSub(ta.isError)}
          />
        </div>
      )}

      {/* ── News Intelligence charts ── */}
      <DashboardSectionLabel aside={periodLabel}>News Intelligence</DashboardSectionLabel>
      {dashboard.isPending && <ChartGridSkeleton />}
      {stats && (
        <div
          className={`grid grid-cols-1 gap-4 transition-opacity lg:grid-cols-12 ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <MapCard flat className="lg:col-span-4" title="Articles by News Type">
            <BreakdownList items={stats.by_news_type.map((x) => ({ label: toTitleCase(x.name), count: x.count }))} limit={9} />
          </MapCard>

          <ChartCard className="lg:col-span-7" title="Articles Over Time" height={280}>
            <TimelineChart
              labels={stats.timeline.map((x) => x.date)}
              data={stats.timeline.map((x) => x.count)}
            />
          </ChartCard>

          <ChartCard
            className="lg:col-span-5"
            title="Top Threat Actors"
            height={280}
            note={basis(stats.coverage.with_actor, "name a threat actor")}
          >
            <HorizontalBarChart
              labels={stats.top_threat_actors.map((x) => toTitleCase(x.name))}
              data={stats.top_threat_actors.map((x) => x.count)}
              tone="info"
            />
          </ChartCard>

          <ChartCard
            className="lg:col-span-5"
            title="Top Targeted Industries"
            height={280}
            note={
              stats.industry_unspecified > 0
                ? `${stats.industry_unspecified.toLocaleString()} articles with no specific sector (General) not shown`
                : undefined
            }
          >
            <HorizontalBarChart
              labels={stats.top_industries.map((x) => toTitleCase(x.name))}
              data={stats.top_industries.map((x) => x.count)}
              tone="info"
            />
          </ChartCard>
          <ChartCard
            className="lg:col-span-7"
            title="Top MITRE ATT&CK TTPs"
            height={280}
            note={basis(stats.coverage.with_ttp, "map to a TTP")}
          >
            <HorizontalBarChart
              labels={stats.top_ttps.map((x) => toTitleCase(x.name))}
              data={stats.top_ttps.map((x) => x.count)}
              tone="info"
            />
          </ChartCard>
        </div>
      )}

      {/* ── Threat Actor Room charts ── (`/api/ta/stats` gak punya filter periode) */}
      <DashboardSectionLabel aside="All time. The period filter does not apply here.">
        Threat Actor Room
      </DashboardSectionLabel>
      {ta.isError && <p className="text-sm text-destructive">Failed to load threat actor stats.</p>}
      {ta.data && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <MapCard flat className="lg:col-span-4" title="APT Groups by Source">
            <BreakdownList items={ta.data.by_source.map((x) => ({ label: toTitleCase(x.name), count: x.count }))} />
          </MapCard>
          <ChartCard className="lg:col-span-8" title="Tracked APT Groups in the News" height={260}>
            {ta.data.top_in_news.length ? (
              <HorizontalBarChart
                labels={ta.data.top_in_news.map((x) => toTitleCase(x.name))}
                data={ta.data.top_in_news.map((x) => x.count)}
                tone="info"
              />
            ) : (
              <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
                No tracked groups mentioned yet.
              </p>
            )}
          </ChartCard>
        </div>
      )}

    </div>
  );
}

/** Placeholder seukuran grid chart di bawahnya, supaya halaman tidak melompat saat data datang. */
function ChartGridSkeleton() {
  return (
    <div aria-hidden className="grid grid-cols-1 gap-4 lg:grid-cols-12">
      <Skeleton className="h-96 rounded-2xl lg:col-span-8" />
      <Skeleton className="h-96 rounded-2xl lg:col-span-4" />
      <Skeleton className="h-80 rounded-2xl lg:col-span-7" />
      <Skeleton className="h-80 rounded-2xl lg:col-span-5" />
    </div>
  );
}

function ErrorNote() {
  return <p className="text-sm text-destructive">Failed to load dashboard data.</p>;
}

/** Sub kartu Threat Actor saat `/api/ta/stats` belum datang atau gagal. */
function taSub(isError: boolean): string {
  return isError ? "Threat actor stats unavailable" : "Loading…";
}
