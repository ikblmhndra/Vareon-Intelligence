"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { useAuth } from "@/components/providers/auth-provider";
import { DashboardSectionLabel } from "@/components/dashboard/stat-box";
import { ExecFilterBar } from "@/components/exec/exec-filter-bar";
import { BriefingView } from "@/components/exec/briefing-view";
import { ExecFootnote } from "@/components/exec/exec-footnote";
import { ExecPageHeader } from "@/components/exec/exec-page-header";
import { TaVelocity, SectorCooccurrence } from "@/components/exec/tier2-panels";
import { CveExposureCard } from "@/components/exec/cve-exposure-card";
import { TopTechniquesCard } from "@/components/exec/top-techniques-card";
import { SectorHeatmap } from "@/components/exec/sector-heatmap";
import { SectorActorMatrix } from "@/components/exec/sector-actor-matrix";
import { ClusterList, CriticalCveFeed, FpQueue } from "@/components/exec/role-gated-panels";
import { BriefCard } from "@/components/exec/brief-card";
import { ExecBriefModal } from "@/components/exec/brief-modal";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import {
  clearExecWatchlist,
  defaultExecFilters,
  execCountLabel,
  getStoredRolePreview,
  parseExecView,
  restoreExecWatchlist,
  saveExecWatchlist,
  setStoredRolePreview,
  type ExecFilters,
  type ExecView,
} from "@/lib/exec/filters";
import { downloadExecCsv } from "@/lib/exec/format";
import { errorStatus, isClientError } from "@/lib/exec/query";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useBrief, useGenerateBrief } from "@/lib/exec/use-brief";
import { fmtTime } from "@/lib/format";
import { PLATFORM_NAME } from "@/lib/brand";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";

type ExecBriefFilters = components["schemas"]["ExecBriefFilters"];

const VIEW_TITLE: Record<ExecView, string> = { briefing: "Exec briefing", board: "Analyst board" };

function initialFilters(): ExecFilters {
  if (typeof window === "undefined") return defaultExecFilters();
  const base = defaultExecFilters();
  const r = restoreExecWatchlist();
  return {
    days: r?.days ?? base.days,
    incidentOnly: r?.incidentOnly ?? base.incidentOnly,
    confirmedOnly: r?.confirmedOnly ?? base.confirmedOnly,
    rolePreview: getStoredRolePreview(),
  };
}

/** Isi sementara Analyst board: bagian lama yang rinci; diganti `BoardView` (Task 14). */
function BoardContent({ d, days }: { d: ExecDashboardV2; days: number }) {
  return (
    <>
          <DashboardSectionLabel>CVE Exposure</DashboardSectionLabel>
          <p className="-mt-2 mb-2 text-xs text-muted-foreground">
            All tracked CVEs across clients (false positives excluded), not filtered by the period above.
          </p>
          <CveExposureCard d={d} />

          <DashboardSectionLabel>Sector Activity Heatmap</DashboardSectionLabel>
          <SectorHeatmap d={d} />

          <DashboardSectionLabel>Secondary Signals</DashboardSectionLabel>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <TopTechniquesCard d={d} days={days} />
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
  );
}

/**
 * Halaman Exec: satu query dashboard-v2 dipakai bersama kedua tampilan (Briefing | Analyst board, `?view=`),
 * jadi berpindah tampilan tidak memicu fetch ulang. Filter, role preview, dan watchlist hidup di sini.
 * Asal halaman: port `exec.js` (Fase 8); PIR ada di `/intelligence`, bukan di sini.
 */
function ExecDashboardPage() {
  const { user } = useAuth();
  const can = useCan();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const [filters, setFilters] = useState<ExecFilters>(initialFilters);
  const [saved] = useState(() => (typeof window === "undefined" ? null : restoreExecWatchlist()));
  const [watchlistSaved, setWatchlistSaved] = useState(saved !== null);
  const [dialogOpen, setDialogOpen] = useState(false);
  // Filter yang menunggu konfirmasi "Replace today's brief?"; null = dialog konfirmasi tertutup.
  const [confirmFilters, setConfirmFilters] = useState<ExecBriefFilters | null>(null);
  // `null` = bawaan server (hari ini, atau yang terbaru); sukses generate mengembalikannya ke hari ini.
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const briefQuery = useBrief(selectedDate);
  const defaultBrief = useBrief(null);
  const generate = useGenerateBrief();
  const shown = briefQuery.data?.brief ?? null;
  // Brief hari ini (bila ada) dari query bawaan: dasar keputusan perlu-tidaknya konfirmasi timpa.
  const todayBrief =
    defaultBrief.data?.brief && defaultBrief.data.brief.brief_date === defaultBrief.data.today ? defaultBrief.data.brief : null;
  const today = useMemo(() => new Date(), []);
  // `?view=` eksplisit menang atas tampilan tersimpan; nilai tak valid jatuh ke Briefing.
  const rawView = params.get("view");
  const view: ExecView = rawView !== null ? (parseExecView(rawView) ?? "briefing") : (saved?.view ?? "briefing");
  // Pilihan "Role preview" tersimpan per browser (localStorage). Non-admin yang memakai browser
  // bekas admin ikut mengirimnya, dan API menjawab 403 "Role preview is admin-only" untuk SELURUH
  // halaman. Hanya admin yang mengirim role preview.
  const rolePreview = isAdmin ? filters.rolePreview : "";

  const dashboard = useQuery({
    queryKey: ["exec", "dashboard-v2", filters.days, filters.incidentOnly, filters.confirmedOnly, rolePreview],
    retry: (n, e) => n < 2 && !isClientError(e),
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/exec/dashboard-v2", {
        params: {
          query: {
            days: filters.days,
            incident_only: filters.incidentOnly,
            confirmed_only: filters.confirmedOnly,
            role: rolePreview || undefined,
          },
        },
      });
      if (error) throw new Error(`exec dashboard gagal (${response.status})`, { cause: response.status });
      return data as unknown as ExecDashboardV2;
    },
  });

  function runGenerate(f: ExecBriefFilters) {
    generate.mutate(f, {
      onSuccess: (data) => {
        setSelectedDate(data.brief_date);
        toast.success("Brief generated", { action: { label: "Open", onClick: () => setDialogOpen(true) } });
      },
      // 502: detail server jadi pesan; brief lama tidak berubah.
      onError: (e) => toast.error(e.message),
      onSettled: () => setConfirmFilters(null),
    });
  }

  /** Ada brief hari ini -> tanya dulu (menimpa baris bersama semua klien); belum ada -> langsung. */
  function requestGenerate(f: ExecBriefFilters) {
    if (todayBrief) setConfirmFilters(f);
    else runGenerate(f);
  }

  const pageBriefFilters: ExecBriefFilters = {
    days: filters.days,
    incident_only: filters.incidentOnly,
    confirmed_only: filters.confirmedOnly,
  };

  // Judul tab per tampilan; dipulihkan saat ganti tampilan/unmount (pola entity-view).
  useEffect(() => {
    const previous = document.title;
    const mine = `${VIEW_TITLE[view]} · ${PLATFORM_NAME}`;
    document.title = mine;
    return () => {
      if (document.title === mine) document.title = previous;
    };
  }, [view]);

  function onFiltersChange(next: ExecFilters) {
    setFilters(next);
    setStoredRolePreview(next.rolePreview);
  }

  function onViewChange(next: ExecView) {
    router.replace(`${pathname}?view=${next}`, { scroll: false });
  }

  const d = dashboard.data;
  const status = errorStatus(dashboard.error);

  return (
    <div className="pb-10">
      <ExecPageHeader
        days={filters.days}
        today={today}
        data={d}
        updatedAt={dashboard.dataUpdatedAt}
        filters={filters}
        view={view}
        onViewChange={onViewChange}
      />
      <ExecFilterBar
        filters={filters}
        onChange={onFiltersChange}
        isAdmin={isAdmin}
        viewRole={d?.view_config.role ?? null}
        watchlistSaved={watchlistSaved}
        onToggleWatchlist={() => {
          if (watchlistSaved) clearExecWatchlist();
          else saveExecWatchlist(filters, view);
          setWatchlistSaved(!watchlistSaved);
        }}
        onExportCsv={can("export_data") ? () => d && downloadExecCsv(d, execCountLabel(filters)) : undefined}
        exportDisabled={!d}
        onGenerateBrief={can("manage_intel") ? () => requestGenerate(pageBriefFilters) : undefined}
        generating={generate.isPending}
      />

      {dashboard.isPending && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" aria-hidden="true">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-24 rounded-lg" />
            ))}
          </div>
          <StatePanel variant="loading" title="Loading exec dashboard…" />
        </div>
      )}
      {dashboard.isError &&
        (status === 403 ? (
          <StatePanel
            variant="no-access"
            title="No access to the Exec dashboard"
            description="Your role cannot view this page. Ask an administrator if you need it."
          />
        ) : (
          <StatePanel
            variant="error"
            title="Could not load the exec dashboard"
            action={
              <Button size="sm" variant="outline" onClick={() => void dashboard.refetch()}>
                Retry
              </Button>
            }
          />
        ))}

      {d && (view === "briefing" ? <BriefingView d={d} filters={filters} brief={
              <BriefCard
                filters={filters}
                selectedDate={selectedDate}
                onSelectDate={setSelectedDate}
                onOpenDialog={() => setDialogOpen(true)}
                onGenerate={() => requestGenerate(pageBriefFilters)}
                generating={generate.isPending}
              />
            }
            today={today}
          /> : <BoardContent d={d} days={filters.days} />)}
      {d && <ExecFootnote filters={filters} />}

      <ExecBriefModal
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        brief={shown}
        canRegenerate={can("manage_intel") && shown !== null && shown.brief_date === briefQuery.data?.today}
        onRegenerate={() => shown && requestGenerate(shown.filters)}
        regenerating={generate.isPending}
      />
      <ConfirmDialog
        open={confirmFilters !== null}
        onOpenChange={(open) => !open && setConfirmFilters(null)}
        title="Replace today's brief?"
        description={`Everyone who opens Exec, for every client, sees the new brief. The current one (${todayBrief?.generated_by ?? ""}, ${todayBrief ? fmtTime(todayBrief.generated_at) : ""}) is overwritten. Generating takes up to a minute and is one LLM call.`}
        confirmLabel="Generate brief"
        confirmLoading={generate.isPending}
        cancelVariant="ghost"
        onConfirm={() => confirmFilters && runGenerate(confirmFilters)}
      />
    </div>
  );
}

/** `useSearchParams` butuh batas Suspense agar build tidak gagal pada prerender. */
export default function ExecPage() {
  return (
    <Suspense>
      <ExecDashboardPage />
    </Suspense>
  );
}
