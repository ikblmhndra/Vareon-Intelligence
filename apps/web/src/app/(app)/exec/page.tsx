"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useAuth } from "@/components/providers/auth-provider";
import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { ExecFilterBar } from "@/components/exec/exec-filter-bar";
import { KpiStrip, KpiStripSkeleton } from "@/components/exec/kpi-strip";
import { SpikeBanner, TtpList, TaVelocity, SectorCooccurrence } from "@/components/exec/tier2-panels";
import { SectorRiskMatrix } from "@/components/exec/sector-risk";
import { TaLeaderboard } from "@/components/exec/ta-leaderboard";
import { ExecChartsSection } from "@/components/exec/charts-section";
import { CveExposureTable } from "@/components/exec/cve-exposure-table";
import { SectorHeatmap } from "@/components/exec/sector-heatmap";
import { SectorActorMatrix } from "@/components/exec/sector-actor-matrix";
import { ClusterList, CriticalCveFeed, FpQueue } from "@/components/exec/role-gated-panels";
import { ExecBriefModal } from "@/components/exec/brief-modal";
import {
  defaultExecFilters,
  getStoredRolePreview,
  restoreExecWatchlist,
  saveExecWatchlist,
  setStoredRolePreview,
  type ExecFilters,
} from "@/lib/exec/filters";
import { downloadExecCsv } from "@/lib/exec/format";
import type { ExecBriefResponse, ExecDashboardV2 } from "@/lib/api/loose-types";

function initialFilters(): ExecFilters {
  if (typeof window === "undefined") return defaultExecFilters();
  const base = defaultExecFilters();
  const restored = restoreExecWatchlist();
  const rolePreview = getStoredRolePreview();
  return { ...base, ...restored, rolePreview };
}

/**
 * Port `exec.js` (869 baris) -- Executive Dashboard: 6 chart+2 heatmap+
 * AI brief+FP-vote widget, area "Besar" tunggal terbesar kedua Fase 8
 * (setelah CVE Tracker). Backend (`exec_dashboard.py`/`exec_brief.py`/
 * `spike.py`) udah lengkap sejak Fase 7 -- satu-satunya perubahan
 * backend di Grup ini adalah nambah `id` ke `pending_fp_queue` row
 * (gap #7, lihat `services/exec_dashboard.py`).
 *
 * PIR (`_pirXxx` functions, `exec.js:757+`) TIDAK ikut diport --
 * itu fitur beda (Priority Intelligence Requirements, `/intelligence`
 * Grup G2), cuma numpang 1 file fisik sama legacy (pola disorganisasi
 * yang sama kayak newsroom panel loaders numpang di `cve.js`/`ta.js`).
 */
export default function ExecDashboardPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [filters, setFilters] = useState<ExecFilters>(initialFilters);
  const [watchlistSaved, setWatchlistSaved] = useState(() => (typeof window === "undefined" ? false : restoreExecWatchlist() !== null));
  const [brief, setBrief] = useState<ExecBriefResponse | null>(null);

  const dashboard = useQuery({
    queryKey: ["exec", "dashboard-v2", filters.days, filters.incidentOnly, filters.confirmedOnly, filters.rolePreview],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/exec/dashboard-v2", {
        params: {
          query: {
            days: filters.days,
            incident_only: filters.incidentOnly,
            confirmed_only: filters.confirmedOnly,
            role: filters.rolePreview || undefined,
          },
        },
      });
      if (error) throw error;
      return data as unknown as ExecDashboardV2;
    },
  });

  const briefMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/exec/brief", {
        params: { query: { days: filters.days, incident_only: filters.incidentOnly, confirmed_only: filters.confirmedOnly } },
      });
      if (error) throw new Error(JSON.stringify(error));
      return data as unknown as ExecBriefResponse;
    },
    onSuccess: (data) => setBrief(data),
    onError: (e) => toast.error(`Brief generation failed: ${(e as Error).message}`),
  });

  function onFiltersChange(next: ExecFilters) {
    setFilters(next);
    setStoredRolePreview(next.rolePreview);
  }

  const d = dashboard.data;

  return (
    <div className="space-y-1 pb-10">
      <ExecFilterBar
        filters={filters}
        onChange={onFiltersChange}
        isAdmin={isAdmin}
        viewRole={d?.view_config.role ?? null}
        watchlistSaved={watchlistSaved}
        onSaveWatchlist={() => {
          saveExecWatchlist(filters);
          setWatchlistSaved(true);
        }}
        onClearWatchlist={() => {
          localStorage.removeItem("cti_exec_idea_watchlist_v1");
          setWatchlistSaved(false);
        }}
        onGenerateBrief={() => briefMutation.mutate()}
        briefPending={briefMutation.isPending}
        onExportCsv={() => d && downloadExecCsv(d)}
        exportDisabled={!d}
      />

      {dashboard.isPending && <KpiStripSkeleton />}
      {dashboard.isError && <p className="text-sm text-destructive">Failed to load exec dashboard.</p>}

      {d && (
        <>
          <KpiStrip d={d} />
          <SpikeBanner d={d} />

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <DashboardSectionLabel>Sector Risk Matrix</DashboardSectionLabel>
              <SectorRiskMatrix d={d} />
            </div>
            <div>
              <DashboardSectionLabel>Threat Actor Leaderboard</DashboardSectionLabel>
              <TaLeaderboard d={d} />
            </div>
          </div>

          <DashboardSectionLabel>Trends</DashboardSectionLabel>
          <ExecChartsSection d={d} />

          <DashboardSectionLabel>CVE Exposure</DashboardSectionLabel>
          <p className="-mt-2 mb-2 text-xs text-muted-foreground">
            All tracked CVEs across clients (false positives excluded), not filtered by the period above.
          </p>
          <CveExposureTable d={d} />

          <DashboardSectionLabel>Sector Activity Heatmap</DashboardSectionLabel>
          <SectorHeatmap d={d} />

          <DashboardSectionLabel>Secondary Signals</DashboardSectionLabel>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border bg-background p-3">
              <div className="mb-2 font-mono text-xs text-muted-foreground">Top TTPs</div>
              <TtpList d={d} />
            </div>
            <div className="rounded-xl border border-border bg-background p-3">
              <div className="mb-2 font-mono text-xs text-muted-foreground">Threat Actor Velocity</div>
              <TaVelocity d={d} />
            </div>
            <div className="rounded-xl border border-border bg-background p-3">
              <div className="mb-2 font-mono text-xs text-muted-foreground">Sector Co-occurrence</div>
              <SectorCooccurrence d={d} />
            </div>
            <div className="rounded-xl border border-border bg-background p-3">
              <div className="mb-2 font-mono text-xs text-muted-foreground">Sector × Actor Matrix</div>
              <SectorActorMatrix d={d} />
            </div>
          </div>

          {(d.view_config.sections.cluster_list || d.view_config.sections.fp_feedback_queue || d.view_config.sections.critical_cve_feed) && (
            <>
              <DashboardSectionLabel>Role View — {d.view_config.role.toUpperCase()}</DashboardSectionLabel>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                {d.view_config.sections.cluster_list && (
                  <div className="rounded-xl border border-border bg-background p-3">
                    <div className="mb-2 font-mono text-xs text-muted-foreground">Recent Campaign Clusters</div>
                    <ClusterList d={d} />
                  </div>
                )}
                {d.view_config.sections.fp_feedback_queue && (
                  <div className="rounded-xl border border-border bg-background p-3">
                    <div className="mb-2 font-mono text-xs text-muted-foreground">IOC False-Positive Queue</div>
                    <FpQueue d={d} />
                  </div>
                )}
                {d.view_config.sections.critical_cve_feed && (
                  <div className="rounded-xl border border-border bg-background p-3 lg:col-span-2">
                    <div className="mb-2 font-mono text-xs text-muted-foreground">KEV CVE Feed — CISA known exploited</div>
                    <CriticalCveFeed d={d} />
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}

      <ExecBriefModal brief={brief} days={filters.days} onOpenChange={(open) => !open && setBrief(null)} />
    </div>
  );
}
