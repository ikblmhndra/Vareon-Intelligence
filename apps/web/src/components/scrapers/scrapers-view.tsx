"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { HealthTiles } from "@/components/scrapers/health-summary-bar";
import { SchedulerChip, SchedulerNotice } from "@/components/scrapers/scheduler-status";
import { ScraperConfigDialog } from "@/components/scrapers/scraper-config-dialog";
import { ScraperItemsPanel } from "@/components/scrapers/scraper-items-panel";
import { ScraperRunsPanel } from "@/components/scrapers/scraper-runs-panel";
import { ScraperPanel } from "@/components/scrapers/scraper-panel";
import { DisableScraperDialog } from "@/components/scrapers/disable-scraper-dialog";
import { StatusLegend } from "@/components/scrapers/status-legend";
import { ScrapersTable, type ScraperRow } from "@/components/scrapers/scrapers-table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import { MasterDetail } from "@/components/ui/master-detail";
import { FilterSelect } from "@/components/ui/filter-select";
import { Sheet } from "@/components/ui/sheet";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { errorStatus } from "@/lib/exec/query";
import { api } from "@/lib/api/client";
import { useScraperHealth } from "@/lib/scrapers/health";
import { unwrap, useEnableScraper, useScraperList, writeErrorMessage } from "@/lib/scrapers/queries";
import { usePageTitle } from "@/lib/use-page-title";

const STATUS_OPTIONS = [
  { value: "all", label: "all" },
  { value: "ok", label: "ok" },
  { value: "degraded", label: "degraded" },
  { value: "stale", label: "stale" },
  { value: "zero_yield", label: "zero yield" },
  { value: "dead", label: "dead" },
  { value: "disabled", label: "disabled" },
] as const;
const RUNTIME_OPTIONS = [
  { value: "all", label: "all" },
  { value: "light", label: "light" },
  { value: "browser", label: "browser" },
] as const;
const QUEUE_OPTIONS = [
  { value: "all", label: "all" },
  { value: "scrape.rss", label: "scrape.rss" },
  { value: "scrape.api", label: "scrape.api" },
  { value: "scrape.browser", label: "scrape.browser" },
] as const;

/** Halaman control plane scraper: header + chip scheduler, enam tile kesehatan, toolbar filter, tabel
 * sumber. Daftar, kesehatan, filter, dan pilihan (`?scraper={id}`) dimiliki di sini; tabel dan panel hanya
 * menyajikan. Filter dan pencarian state komponen (daftar ada di memori, tidak perlu debounce). */
export function ScrapersView() {
  usePageTitle("Scrapers");
  const router = useRouter();
  const selectedId = useSearchParams().get("scraper");
  const canManage = useCan()("manage_scraper");

  const list = useScraperList();
  const health = useScraperHealth();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatus] = useState("all");
  const [runtime, setRuntime] = useState("all");
  const [queue, setQueue] = useState("all");
  const [legendOpen, setLegendOpen] = useState(false);
  const [disableTarget, setDisableTarget] = useState<{
    id: string;
    source: string;
  } | null>(null);
  const enable = useEnableScraper();
  const [configOpen, setConfigOpen] = useState(false);
  const [historyTarget, setHistoryTarget] = useState<string | null>(null);
  const [dedupTarget, setDedupTarget] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const panelRef = useRef<HTMLDivElement>(null);

  const dedup = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/reset-dedup", { params: { path: { scraper_id: id } } }),
        "Reset dedup failed",
      ),
    onSuccess: (data) => {
      toast.success(`Dedup reset · ${data.deleted} entries cleared`);
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
      setDedupTarget(null);
    },
    onError: (e: Error) => toast.error(`Reset dedup failed: ${writeErrorMessage(e)}`),
  });

  /** `router.replace` ke URL yang sama membuat Next memasang ulang judul layout, jadi no-op bila tak berubah. */
  function select(id: string | null) {
    if (id === selectedId) return;
    router.replace(id ? `/scrapers?scraper=${encodeURIComponent(id)}` : "/scrapers", { scroll: false });
    // Di bawah 1024 px panel menumpuk di bawah tabel: bawa ke layar saat baris dipilih.
    if (id && !window.matchMedia("(min-width: 1024px)").matches) {
      panelRef.current?.scrollIntoView({ block: "start" });
    }
  }

  // Health belum datang atau gagal: jangan tulis "ok" untuk scraper yang belum dinilai (ROADMAP #24).
  // Data lama dari refetch yang gagal tetap dipakai (halaman tidak boleh kosong karena satu refetch gagal).
  const healthFailed = health.isError && !health.data;
  // "unknown" hanya ditawarkan saat health gagal; begitu pulih, filter itu dianggap "all" (tanpa effect).
  const status = statusFilter === "unknown" && !healthFailed ? "all" : statusFilter;
  const problemById = new Map((health.data?.problems ?? []).map((p) => [p.id, p.status]));
  function statusFor(id: string, enabled: boolean): string {
    if (!enabled) return "disabled";
    if (!health.data) return healthFailed ? "unknown" : "loading";
    return problemById.get(id) ?? "ok";
  }

  const allRows: ScraperRow[] = (list.data?.scrapers ?? []).map((s) => ({
    ...s,
    status: statusFor(s.id, s.enabled),
  }));
  const selectedRow = allRows.find((r) => r.id === selectedId);
  const q = search.trim().toLowerCase();
  const rows = allRows.filter(
    (s) =>
      (status === "all" || s.status === status) &&
      (runtime === "all" || s.runtime === runtime) &&
      (queue === "all" || s.queue === queue) &&
      (!q || s.id.toLowerCase().includes(q) || s.source.toLowerCase().includes(q)),
  );
  const filtering = q !== "" || status !== "all" || runtime !== "all" || queue !== "all";
  function clearFilters() {
    setSearch("");
    setStatus("all");
    setRuntime("all");
    setQueue("all");
  }

  const statusOptions = healthFailed
    ? [...STATUS_OPTIONS, { value: "unknown", label: "unknown" }]
    : STATUS_OPTIONS;
  const listFailed = list.isError && !list.data;

  return (
    <div className="pb-10">
      <PageHeader
        kicker="OPERATIONS"
        title="Scrapers"
        description="Every source the platform reads, its schedule and how its last run went"
        actions={<SchedulerChip />}
      />
      {listFailed ? (
        errorStatus(list.error) === 403 ? (
          <StatePanel variant="no-access" title="You need the view_ops permission to see scrapers" />
        ) : (
          <StatePanel
            variant="error"
            title="Failed to load scrapers"
            action={
              <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
                Retry
              </Button>
            }
          />
        )
      ) : (
        <>
          <SchedulerNotice />
          <HealthTiles
            counts={health.data?.counts ?? {}}
            generatedAt={health.data?.generated_at ?? null}
            state={
              list.isPending || (health.isPending && !health.data)
                ? "loading"
                : healthFailed
                  ? "error"
                  : "ready"
            }
            selected={status}
            onSelect={(s) => setStatus((cur) => (cur === s ? "all" : s))}
            onRetry={() => void health.refetch()}
          />
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search source or id"
              aria-label="Search source or id"
              className="w-64"
            />
            <FilterSelect prefix="Status" value={status} onChange={setStatus} options={statusOptions} />
            <FilterSelect prefix="Runtime" value={runtime} onChange={setRuntime} options={RUNTIME_OPTIONS} />
            <FilterSelect prefix="Queue" value={queue} onChange={setQueue} options={QUEUE_OPTIONS} />
            <a
              href="#status-legend"
              onClick={() => setLegendOpen(true)}
              className="ml-auto rounded-md text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
            >
              What the statuses mean →
            </a>
          </div>
          {list.isPending || !list.data ? (
            <Skeleton className="h-96 w-full" />
          ) : (
            <MasterDetail
              list={
                <ScrapersTable
                  rows={rows}
                  total={list.data.scrapers.length}
                  filtered={filtering ? rows.length : null}
                  schedulerOk={(health.data?.scheduler ?? list.data.scheduler).state === "ok"}
                  nowMs={list.data.nowMs}
                  selectedId={selectedId}
                  canManage={canManage}
                  enablingId={enable.isPending ? enable.variables : null}
                  onSelect={select}
                  onDisable={(row) => setDisableTarget({ id: row.id, source: row.source })}
                  onEnable={(id) => enable.mutate(id)}
                  onClearFilters={clearFilters}
                />
              }
              detail={
                <div ref={panelRef}>
                  <ScraperPanel
                    id={selectedId}
                    row={selectedRow}
                    entry={health.data?.problems.find((p) => p.id === selectedId)}
                    listReady={!!list.data}
                    nowMs={list.data.nowMs}
                    canManage={canManage}
                    onClose={() => select(null)}
                    onDisable={(row) => setDisableTarget({ id: row.id, source: row.source })}
                    onEditConfig={() => setConfigOpen(true)}
                    onResetDedup={() => setDedupTarget(selectedId)}
                    onOpenHistory={() => setHistoryTarget(selectedId)}
                  />
                </div>
              }
            />
          )}
          <StatusLegend open={legendOpen} onOpenChange={setLegendOpen} />
        </>
      )}
      <DisableScraperDialog target={disableTarget} onOpenChange={(open) => !open && setDisableTarget(null)} />
      <ScraperConfigDialog id={selectedId} open={configOpen} onOpenChange={setConfigOpen} />
      <ConfirmDialog
        open={dedupTarget !== null}
        onOpenChange={(open) => !open && setDedupTarget(null)}
        tone="danger"
        title="Reset dedup state?"
        description={`All dedup history for ${dedupTarget} is deleted. The next run is a cold start: only its newest items are processed and the rest are marked seen.`}
        confirmLabel="Reset dedup"
        confirmLoading={dedup.isPending}
        onConfirm={() => dedupTarget && dedup.mutate(dedupTarget)}
      />
      <Sheet
        open={historyTarget !== null}
        onOpenChange={(open) => !open && setHistoryTarget(null)}
        title={`Run history · ${allRows.find((r) => r.id === historyTarget)?.source ?? historyTarget}`}
        description="Every recorded run and every item the scraper logged."
      >
        {historyTarget && (
          <div className="space-y-6">
            <section>
              <h3 className="mb-2 text-sm font-semibold text-foreground">Runs</h3>
              <ScraperRunsPanel key={historyTarget} scraperId={historyTarget} />
            </section>
            <section>
              <h3 className="mb-2 text-sm font-semibold text-foreground">Items</h3>
              <ScraperItemsPanel key={historyTarget} scraperId={historyTarget} />
            </section>
          </div>
        )}
      </Sheet>
    </div>
  );
}
