"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";

import { api } from "@/lib/api/client";
import type { TaStats } from "@/lib/api/loose-types";
import { ChartCard, DashboardSectionLabel, Delta, MapCard, StatBox } from "@/components/dashboard/stat-box";
import {
  ClientContextCard,
  CveExposureCard,
  MustReadCard,
  RansomwareCard,
  TrendingCard,
} from "@/components/dashboard/overview-cards";
import {
  useCveExposure,
  useDashboardRansomware,
  useDashboardTrending,
} from "@/components/dashboard/use-dashboard-overview";
import { useAuth } from "@/components/providers/auth-provider";
import { getActiveClientId } from "@/lib/auth/client-id";
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

const noopSubscribe = () => () => {};
// String primitif: snapshot stabil antar panggilan, jadi tidak memicu render ulang.
const todaySnapshot = () =>
  new Date().toLocaleDateString("id-ID", { weekday: "long", day: "numeric", month: "long" });

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
  const ransomware = useDashboardRansomware(filters.days);
  const cve = useCveExposure(filters.days);
  const trending = useDashboardTrending(filters.days);
  const { user } = useAuth();
  // Cookie client dan tanggal hanya ada di browser: snapshot server = placeholder, supaya markup
  // server dan hidrasi sama (tanpa ini React 19 melaporkan hydration mismatch).
  const cookieClient = useSyncExternalStore(noopSubscribe, getActiveClientId, () => null);
  const clientName = cookieClient ?? user?.client_ids[0] ?? "—";
  const todayLabel = useSyncExternalStore(noopSubscribe, todaySnapshot, () => "Dashboard");

  const stats = dashboard.data;
  const kpiStale = dashboard.isPlaceholderData || ransomware.isPlaceholderData || cve.isPlaceholderData;
  const newActors = (trending.data?.items ?? []).filter((x) => x.kind === "actor" && x.is_new).length;
  const periodLabel = filters.days ? `Last ${filters.days} days` : "All time";
  const prevLabel = filters.days ? `${filters.days}d` : "";
  // Penyebut chart: cuma sebagian artikel yang punya negara/aktor/TTP, jadi sebut basisnya.
  const basis = (n: number | undefined, what: string) =>
    stats && n !== undefined ? `${n.toLocaleString()} of ${stats.total_articles.toLocaleString()} articles ${what}` : undefined;

  return (
    <div className="pb-10">
      <PageHeader
        title={todayLabel}
        description={`Klien: ${clientName}`}
        actions={<DashboardFilterBar filters={filters} onChange={setFilters} updatedAt={stats?.generated_at} />}
      />

      <SignalHero days={filters.days} incidentOnly={filters.incidentOnly} />

      {/* ── KPI ── */}
      {dashboard.isPending && <Skeleton className="mt-6 h-28 w-full rounded-2xl" />}
      {dashboard.isError && <ErrorNote />}
      {/* Tiap angka dari endpoint lain tampil "—" bila endpoint-nya belum datang/gagal; KPI artikel tetap utuh. */}
      {stats && (
        <div
          className={`surface-raised mt-6 grid grid-cols-1 divide-y divide-border/70 rounded-2xl p-2 transition-opacity sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-5 xl:divide-x ${kpiStale ? "opacity-60" : ""}`}
        >
          <StatBox
            flat
            emphasis
            label="Artikel"
            value={stats.total_articles}
            sub={
              <>
                {periodLabel}
                {filters.incidentOnly ? " · hanya berita ancaman" : ""}
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
            label="Insiden terkonfirmasi"
            value={stats.confirmed_incidents}
            sub={
              <>
                dari {stats.total_articles.toLocaleString()} artikel
                <Delta
                  value={stats.confirmed_incidents}
                  prev={stats.prev_confirmed_incidents}
                  label={prevLabel}
                  reliable={stats.prev_period_reliable}
                />
              </>
            }
          />
          <StatBox
            flat
            label="Korban ransomware"
            value={ransomware.data?.total}
            sub={ransomware.data ? `${ransomware.data.apac.toLocaleString()} di APAC` : kpiSub(ransomware.isError)}
          />
          <StatBox
            flat
            label="CVE kritis terbuka"
            value={cve.data?.open_critical}
            sub={cve.data ? `${cve.data.open_kev.toLocaleString()} KEV terbuka (semua severity)` : kpiSub(cve.isError)}
          />
          <StatBox
            flat
            label="Aktor di berita"
            value={stats.total_threat_actors}
            sub={trending.data ? `${newActors} baru periode ini` : kpiSub(trending.isError)}
          />
        </div>
      )}

      {/* ── Ringkasan ── (tiap kartu fetch dan gagal sendiri) */}
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-12">
        <MustReadCard days={filters.days} className="lg:col-span-7" />
        <TrendingCard days={filters.days} className="lg:col-span-5" />
        <RansomwareCard days={filters.days} className="lg:col-span-4" />
        <CveExposureCard days={filters.days} className="lg:col-span-4" />
        <ClientContextCard days={filters.days} incidentOnly={filters.incidentOnly} className="lg:col-span-4" />

        {dashboard.isPending && (
          <>
            <Skeleton aria-hidden className="h-80 rounded-2xl lg:col-span-8" />
            <Skeleton aria-hidden className="h-80 rounded-2xl lg:col-span-4" />
          </>
        )}
        {dashboard.isError && (
          <>
            <ErrorCard className="lg:col-span-8" title="Artikel dari waktu ke waktu" noun="grafik artikel dari waktu ke waktu" />
            <ErrorCard className="lg:col-span-4" title="Industri disasar" noun="data industri disasar" />
          </>
        )}
        {stats && (
          <>
            <ChartCard
              className={`lg:col-span-8 transition-opacity ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
              title="Artikel dari waktu ke waktu"
              height={280}
            >
              <TimelineChart
                labels={stats.timeline.map((x) => x.date)}
                data={stats.timeline.map((x) => x.count)}
                label="Semua berita"
                tone="info"
                secondary={{ label: "Insiden", data: stats.timeline.map((x) => x.incidents), tone: "primary" }}
              />
            </ChartCard>
            <MapCard
              flat
              className={`lg:col-span-4 transition-opacity ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
              title="Industri disasar"
              note={
                stats.industry_unspecified > 0
                  ? `${stats.industry_unspecified.toLocaleString()} artikel tanpa sektor spesifik (General) tidak ditampilkan`
                  : undefined
              }
            >
              <BreakdownList
                items={stats.top_industries
                  .filter((x) => x.name.toLowerCase() !== "general")
                  .map((x) => ({ label: toTitleCase(x.name), count: x.count }))}
                limit={8}
              />
            </MapCard>
          </>
        )}
      </div>

      {/* ── TTP ── */}
      {dashboard.isPending && <Skeleton aria-hidden className="mt-4 h-80 rounded-2xl" />}
      {dashboard.isError && <ErrorCard className="mt-4" title="Top MITRE ATT&CK TTPs" noun="grafik TTP" />}
      {stats && (
        <div
          className={`mt-4 grid grid-cols-1 gap-4 transition-opacity lg:grid-cols-12 ${dashboard.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <ChartCard
            className="lg:col-span-12"
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
      {ta.isPending && (
        <div aria-hidden className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <Skeleton className="h-72 rounded-2xl lg:col-span-4" />
          <Skeleton className="h-72 rounded-2xl lg:col-span-8" />
        </div>
      )}
      {ta.isError && <p className="text-sm text-destructive">Gagal memuat statistik Threat Actor Room.</p>}
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

function ErrorCard({ title, noun, className }: { title: string; noun: string; className?: string }) {
  return (
    <MapCard title={title} className={className}>
      <p className="text-sm text-destructive">Gagal memuat {noun}.</p>
    </MapCard>
  );
}

function ErrorNote() {
  return <p className="text-sm text-destructive">Gagal memuat angka KPI dashboard.</p>;
}

/** Sub KPI saat endpoint asalnya (ransomware/CVE/trending) belum datang atau gagal. */
function kpiSub(isError: boolean): string {
  return isError ? "Gagal memuat" : "Memuat…";
}
