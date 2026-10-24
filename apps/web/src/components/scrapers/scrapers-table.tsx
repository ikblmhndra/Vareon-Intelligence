"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useScraperHealth } from "@/lib/scrapers/health";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { RunStatusText, StatusBadge } from "@/components/scrapers/status-badge";
import { DisableScraperDialog } from "@/components/scrapers/disable-scraper-dialog";
import { useCan } from "@/lib/auth/permissions";

const RUNTIME_ITEMS: Record<string, string> = { __all__: "All runtimes", light: "light", browser: "browser" };
const STATUS_ITEMS: Record<string, string> = {
  __all__: "All statuses",
  ok: "ok",
  disabled: "disabled",
  stale: "stale",
  dead: "dead",
  degraded: "degraded",
  zero_yield: "zero_yield",
};

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const min = Math.round(diffMs / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

/** "in 12m" / "in 3h" / "in 4d" -- slot cron berikutnya (`next_run_at`, QA BUG-D8). */
function untilTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diffMs = new Date(iso).getTime() - Date.now();
  if (diffMs <= 0) return "due";
  const min = Math.round(diffMs / 60_000);
  if (min < 1) return "<1m";
  if (min < 60) return `in ${min}m`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `in ${hr}h`;
  return `in ${Math.round(hr / 24)}d`;
}

/** Tabel 84 scraper -- list (`GET /api/scraper`) DIGABUNG status
 * kesehatan (`GET /api/scraper/health`, cache SAMA kayak `HealthSummaryBar`
 * -- TanStack Query dedupe by queryKey, bukan fetch dobel) client-side:
 * scraper yang gak muncul di `problems` DAN `enabled` dianggap `ok`,
 * yang `!enabled` `disabled` -- partition itu DIJAMIN backend (`compute_
 * health()` selalu balikin TEPAT satu dari 6 status), bukan tebakan. */
export function ScrapersTable({
  onOpenDetail,
}: {
  onOpenDetail: (scraperId: string, status: string) => void;
}) {
  const can = useCan();
  const isAdmin = can("manage_scraper");
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [runtimeFilter, setRuntimeFilter] = useState("__all__");
  const [statusFilter, setStatusFilter] = useState("__all__");
  const [disableTarget, setDisableTarget] = useState<string | null>(null);

  const list = useQuery({
    queryKey: ["scrapers", "list"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/scraper");
      if (error) throw error;
      return data;
    },
    // `next_run_at` + status scheduler ikut basi kalau gak di-refresh.
    refetchInterval: 60_000,
  });

  const health = useScraperHealth();

  const statusById = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of health.data?.problems ?? []) m.set(p.id, p.status);
    return m;
  }, [health.data]);

  // Health belum datang atau gagal: jangan tulis "ok" untuk scraper yang belum dinilai (ROADMAP #24).
  const healthKnown = health.isSuccess;
  function statusFor(id: string, enabled: boolean): string {
    if (!enabled) return "disabled";
    if (!healthKnown) return health.isError ? "unknown" : "loading";
    return statusById.get(id) ?? "ok";
  }

  const triggerMutation = useMutation({
    mutationFn: async (scraperId: string) => {
      const { data, error } = await api.POST("/api/scraper/{scraper_id}/trigger", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) => toast.success(`Triggered ${data.scraper_id} — task ${data.celery_task_id.slice(0, 8)}…`),
    onError: (e: Error) => toast.error(`Trigger failed: ${e.message}`),
  });

  const dryRunMutation = useMutation({
    mutationFn: async (scraperId: string) => {
      const { data, error } = await api.POST("/api/scraper/{scraper_id}/dry-run", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) =>
      toast.success(`${data.scraper_id}: ${data.status}, ${data.items_found} item (${data.duration_ms}ms)`),
    onError: (e: Error) => toast.error(`Dry-run failed: ${e.message}`),
  });

  const enableMutation = useMutation({
    mutationFn: async (scraperId: string) => {
      const { error } = await api.POST("/api/scraper/{scraper_id}/enable", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
    },
    onSuccess: (_data, scraperId) => {
      toast.success(`${scraperId} enabled`);
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
    },
    onError: (e: Error) => toast.error(`Enable failed: ${e.message}`),
  });

  const items = list.data?.scrapers ?? [];
  const schedulerOk = list.data?.scheduler.state === "ok";
  const filtered = items.filter((s) => {
    if (runtimeFilter !== "__all__" && s.runtime !== runtimeFilter) return false;
    const status = statusFor(s.id, s.enabled);
    if (statusFilter !== "__all__" && status !== statusFilter) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!s.id.toLowerCase().includes(q) && !s.source.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-muted-foreground">Search</span>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="id or source…"
            className="w-48 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-muted-foreground">Runtime</span>
          <Select items={RUNTIME_ITEMS} value={runtimeFilter} onValueChange={(v) => v && setRuntimeFilter(v)}>
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(RUNTIME_ITEMS).map(([v, l]) => (
                <SelectItem key={v} value={v} className="font-mono text-xs">
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-medium text-muted-foreground">Status</span>
          <Select items={STATUS_ITEMS} value={statusFilter} onValueChange={(v) => v && setStatusFilter(v)}>
            <SelectTrigger size="sm" className="w-40 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(STATUS_ITEMS).map(([v, l]) => (
                <SelectItem key={v} value={v} className="font-mono text-xs">
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {filtered.length} / {items.length} scraper
        </span>
      </div>

      {health.isError && (
        <p className="mb-2 text-xs text-destructive-text">
          Scraper health could not be loaded, so enabled scrapers show UNKNOWN instead of a status.
        </p>
      )}
      {list.isPending && <Skeleton className="h-96 w-full" />}
      {list.isError && <p className="text-xs text-destructive">Failed to load scrapers.</p>}
      {list.data && (
        <Table framed>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Runtime</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Schedule</TableHead>
              <TableHead>Last Run</TableHead>
              <TableHead>Next Run</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((s) => {
              const status = statusFor(s.id, s.enabled);
              return (
                <TableRow key={s.id} className="cursor-pointer" onClick={() => onOpenDetail(s.id, status)}>
                  <TableCell className="font-code text-xs text-foreground">{s.id}</TableCell>
                  <TableCell className="text-xs text-foreground">{s.source}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {s.runtime}
                    {s.has_override && <span className="ml-1 text-primary" title="config override active">●</span>}
                  </TableCell>
                  <TableCell>
                    {status === "loading" ? (
                      <Skeleton className="h-5 w-14 rounded-full" aria-label="Loading status" />
                    ) : (
                      <StatusBadge status={status} />
                    )}
                    {!s.enabled && <DisabledReason by={s.disabled_by} reason={s.paused_reason} />}
                  </TableCell>
                  <TableCell className="font-code text-xs text-muted-foreground">{s.schedule}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {s.last_status ? <RunStatusText status={s.last_status} /> : "—"}{" "}
                    {relativeTime(s.last_started_at)}
                  </TableCell>
                  <TableCell
                    className={`font-mono text-xs ${schedulerOk ? "text-muted-foreground" : "text-destructive line-through"}`}
                    title={
                      s.next_run_at
                        ? `${s.next_run_at.replace("T", " ").split("+")[0]} UTC${schedulerOk ? "" : " — scheduler down, will NOT fire"}`
                        : s.enabled
                          ? "invalid cron"
                          : "disabled"
                    }
                  >
                    {untilTime(s.next_run_at)}
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" />}>⋮</DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => onOpenDetail(s.id, status)}>View Detail</DropdownMenuItem>
                        {isAdmin && (
                          <>
                            <DropdownMenuItem onClick={() => triggerMutation.mutate(s.id)}>
                              Trigger
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => dryRunMutation.mutate(s.id)}>
                              Dry-run
                            </DropdownMenuItem>
                            {s.enabled ? (
                              <DropdownMenuItem onClick={() => setDisableTarget(s.id)}>Disable</DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem onClick={() => enableMutation.mutate(s.id)}>Enable</DropdownMenuItem>
                            )}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <StatusLegend />
      <DisableScraperDialog scraperId={disableTarget} onOpenChange={(open) => !open && setDisableTarget(null)} />
    </div>
  );
}

const DISABLED_BY_LABEL: Record<string, string> = {
  admin: "Turned off by an admin",
  code: "Off by default in code",
  mirror: "Replaced by the CVE mirror",
};

/** Kenapa scraper DISABLED (`disabled_by` + `paused_reason` dari `GET /api/scraper`). */
function DisabledReason({ by, reason }: { by: string | null | undefined; reason: string | null | undefined }) {
  if (!by && !reason) return null;
  return (
    <div className="mt-1 max-w-56 text-xs text-muted-foreground">
      {by ? (DISABLED_BY_LABEL[by] ?? by) : null}
      {reason ? <>{by ? ": " : ""}{reason}</> : null}
    </div>
  );
}

/** Legenda status, pola "How these metrics are calculated" di CVE Dashboard. Aturannya dari
 * `cti_scraper.health` (fungsi murni yang sama dengan digest Telegram). */
function StatusLegend() {
  return (
    <details className="mt-4 rounded-2xl surface-raised p-4 text-sm">
      <summary className="cursor-pointer font-medium">What the statuses mean</summary>
      <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
        <li>
          <strong className="text-foreground">OK</strong>: the latest run finished without errors or failed items.
        </li>
        <li>
          <strong className="text-foreground">Disabled</strong>: not scheduled. The line under the badge says who turned it off: an
          admin (with the reason they gave), the default in code, or the CVE mirror that replaces it.
        </li>
        <li>
          <strong className="text-foreground">Stale</strong>: the scraper has never run.
        </li>
        <li>
          <strong className="text-foreground">Dead</strong>: the latest run started more than three schedule intervals ago.
        </li>
        <li>
          <strong className="text-foreground">Degraded</strong>: the latest run failed (fetch, parse, rate limit, timeout or
          backpressure) or finished with items that failed to save.
        </li>
        <li>
          <strong className="text-foreground">Zero yield</strong>: the last three runs all finished with zero items.
        </li>
        <li>
          <strong className="text-foreground">Partial</strong> (a run status in Last Run and the Runs tab): the run finished but
          some of its items failed; the scraper then shows as Degraded.
        </li>
        <li>
          <strong className="text-foreground">Unknown</strong>: the health check could not be loaded, so the status is not known.
        </li>
      </ul>
    </details>
  );
}
