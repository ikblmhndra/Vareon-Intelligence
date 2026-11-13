"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { HealthTiles } from "@/components/scrapers/health-summary-bar";
import { SchedulerChip, SchedulerNotice } from "@/components/scrapers/scheduler-status";
import { ScraperDetailDialog } from "@/components/scrapers/scraper-detail-dialog";
import { DisableScraperDialog } from "@/components/scrapers/disable-scraper-dialog";
import { StatusLegend } from "@/components/scrapers/status-legend";
import { ScrapersTable, type ScraperRow } from "@/components/scrapers/scrapers-table";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/components/ui/filter-select";
import { SearchInput } from "@/components/ui/search-input";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { useCan } from "@/lib/auth/permissions";
import { errorStatus } from "@/lib/exec/query";
import { useScraperHealth } from "@/lib/scrapers/health";
import { useEnableScraper, useScraperList } from "@/lib/scrapers/queries";
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
  const [status, setStatus] = useState("all");
  const [runtime, setRuntime] = useState("all");
  const [queue, setQueue] = useState("all");
  const [legendOpen, setLegendOpen] = useState(false);
  const [disableTarget, setDisableTarget] = useState<{ id: string; source: string } | null>(null);
  const enable = useEnableScraper();

  /** `router.replace` ke URL yang sama membuat Next memasang ulang judul layout, jadi no-op bila tak berubah. */
  function select(id: string | null) {
    if (id === selectedId) return;
    router.replace(id ? `/scrapers?scraper=${encodeURIComponent(id)}` : "/scrapers", { scroll: false });
  }

  // Health belum datang atau gagal: jangan tulis "ok" untuk scraper yang belum dinilai (ROADMAP #24).
  // Data lama dari refetch yang gagal tetap dipakai (halaman tidak boleh kosong karena satu refetch gagal).
  const healthFailed = health.isError && !health.data;
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
            state={list.isPending || (health.isPending && !health.data) ? "loading" : healthFailed ? "error" : "ready"}
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
            <ScrapersTable
              rows={rows}
              total={list.data.scrapers.length}
              filtered={filtering ? rows.length : null}
              schedulerOk={list.data.scheduler.state === "ok"}
              nowMs={list.data.nowMs}
              selectedId={selectedId}
              canManage={canManage}
              enablingId={enable.isPending ? enable.variables : null}
              onSelect={select}
              onDisable={(row) => setDisableTarget({ id: row.id, source: row.source })}
              onEnable={(id) => enable.mutate(id)}
              onClearFilters={clearFilters}
            />
          )}
          <StatusLegend open={legendOpen} onOpenChange={setLegendOpen} />
        </>
      )}
      <DisableScraperDialog
        target={disableTarget}
        onOpenChange={(open) => !open && setDisableTarget(null)}
      />
      <ScraperDetailDialog
        scraperId={selectedId}
        healthStatus={allRows.find((s) => s.id === selectedId)?.status}
        onOpenChange={(open) => !open && select(null)}
      />
    </div>
  );
}
