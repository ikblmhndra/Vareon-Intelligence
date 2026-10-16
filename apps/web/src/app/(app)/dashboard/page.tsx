"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api/client";
import type { TaStats } from "@/lib/api/loose-types";
import { ChartCard, DashboardSectionLabel, Delta, MapCard, StatBox } from "@/components/dashboard/stat-box";
import { AttentionBand } from "@/components/dashboard/attention-band";
import { BreakdownList } from "@/components/dashboard/breakdown-list";
import { CountryMap } from "@/components/dashboard/country-map";
import { HorizontalBarChart, TimelineChart } from "@/components/dashboard/charts";
import {
  DEFAULT_DASHBOARD_FILTERS,
  DashboardFilterBar,
  type DashboardFilters,
} from "@/components/dashboard/dashboard-filters";
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
    <div className="space-y-1 pb-10">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-sm text-muted-foreground">Ringkasan intelijen</div>
          <h1 className="font-heading text-3xl font-extrabold tracking-tight text-foreground">Dashboard</h1>
        </div>
        <DashboardFilterBar filters={filters} onChange={setFilters} updatedAt={stats?.generated_at} />
      </header>

      <AttentionBand />

      {/* ── KPI ── */}
      {(dashboard.isPending || ta.isPending) && <StatGridSkeleton count={5} />}
      {dashboard.isError && <ErrorNote />}
      {stats && ta.data && (
        <div
          className={`mt-6 grid grid-cols-1 gap-4 transition-opacity sm:grid-cols-2 xl:grid-cols-5 ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <StatBox
            label="Total Articles"
            value={stats.total_articles}
            sub={
              <>
                {periodLabel}
                {filters.incidentOnly ? " · incidents only" : ""}
                <Delta value={stats.total_articles} prev={stats.prev_total_articles} label={prevLabel} />
              </>
            }
            spark={stats.timeline.map((x) => x.count)}
          />
          <StatBox
            label="Confirmed Incidents"
            value={stats.confirmed_incidents}
            sub={
              <>
                of {stats.total_articles.toLocaleString()} articles
                <Delta value={stats.confirmed_incidents} prev={stats.prev_confirmed_incidents} label={prevLabel} />
              </>
            }
          />
          <StatBox label="Countries Mentioned" value={stats.total_countries} sub="Unique geographies" />
          <StatBox
            label="Threat Actors in News"
            value={stats.total_threat_actors}
            sub={`${ta.data.total_groups.toLocaleString()} APT groups · ${ta.data.total_whitelisted} whitelisted`}
          />
          <StatBox
            label="Covered in News"
            value={ta.data.in_news_count}
            sub={`${ta.data.manual_count} added manually`}
          />
        </div>
      )}

      {/* ── News Intelligence charts ── */}
      <DashboardSectionLabel>News Intelligence</DashboardSectionLabel>
      {stats && (
        <div className={`space-y-3 transition-opacity ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <MapCard title="Mentioned Countries" note={basis(stats.coverage.with_country, "name a country")}>
              <CountryMap data={stats.country_counts} />
            </MapCard>
            <MapCard title="Articles by News Type">
              <BreakdownList items={stats.by_news_type.map((x) => ({ label: toTitleCase(x.name), count: x.count }))} limit={9} />
            </MapCard>
          </div>

          <ChartCard title="Articles Over Time" height={200}>
            <TimelineChart
              labels={stats.timeline.map((x) => x.date)}
              data={stats.timeline.map((x) => x.count)}
            />
          </ChartCard>

          <ChartCard
            title="Top Threat Actors"
            height={280}
            note={basis(stats.coverage.with_actor, "name a threat actor")}
          >
            <HorizontalBarChart
              labels={stats.top_threat_actors.map((x) => toTitleCase(x.name))}
              data={stats.top_threat_actors.map((x) => x.count)}
              tone="critical"
            />
          </ChartCard>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <ChartCard
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
                tone="warning"
              />
            </ChartCard>
            <ChartCard
              title="Top MITRE ATT&CK TTPs"
              height={280}
              note={basis(stats.coverage.with_ttp, "map to a TTP")}
            >
              <HorizontalBarChart
                labels={stats.top_ttps.map((x) => toTitleCase(x.name))}
                data={stats.top_ttps.map((x) => x.count)}
                tone="success"
              />
            </ChartCard>
          </div>
        </div>
      )}

      {/* ── Threat Actor Room charts ── (`/api/ta/stats` gak punya filter periode) */}
      <DashboardSectionLabel>Threat Actor Room — Charts · all time</DashboardSectionLabel>
      {ta.data && (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <MapCard title="APT Groups by Source">
            <BreakdownList items={ta.data.by_source.map((x) => ({ label: toTitleCase(x.name), count: x.count }))} />
          </MapCard>
          <ChartCard title="Tracked APT Groups — News Mentions" height={260}>
            {ta.data.top_in_news.length ? (
              <HorizontalBarChart
                labels={ta.data.top_in_news.map((x) => toTitleCase(x.name))}
                data={ta.data.top_in_news.map((x) => x.count)}
                tone="success"
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

function StatGridSkeleton({ count }: { count: number }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-20 w-full" />
      ))}
    </div>
  );
}

function ErrorNote() {
  return <p className="text-sm text-destructive">Failed to load dashboard data.</p>;
}
