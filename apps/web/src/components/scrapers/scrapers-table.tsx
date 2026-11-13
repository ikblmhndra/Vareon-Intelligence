"use client";

import type { components } from "@/lib/api/schema";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatusBadge, runStatusClass } from "@/components/scrapers/status-badge";
import { fmtAgo, fmtDateTime, fmtShortDate, fmtTime } from "@/lib/format";
import { humanizeCron, isHumanized } from "@/lib/scrapers/cron";
import { disabledReasonText, lastRunOutcome } from "@/lib/scrapers/reason";

export type ScraperRow = components["schemas"]["ScraperListItem"] & { status: string };

const DAY_MS = 86_400_000;

/** Tabel sumber scraper, murni presentasi: baris sudah digabung status dan disaring `ScrapersView`.
 * `filtered` null = tidak ada filter aktif. Baris tidak punya `onClick`; SOURCE adalah `<button>` sungguhan
 * dan aksi ada di sel saudaranya, supaya tidak ada elemen interaktif bersarang. */
export function ScrapersTable({
  rows,
  total,
  filtered,
  schedulerOk,
  nowMs,
  selectedId,
  canManage,
  enablingId,
  onSelect,
  onDisable,
  onEnable,
  onClearFilters,
}: {
  rows: ScraperRow[];
  total: number;
  filtered: number | null;
  schedulerOk: boolean;
  nowMs: number;
  selectedId: string | null;
  canManage: boolean;
  enablingId: string | null;
  onSelect: (id: string) => void;
  onDisable: (row: ScraperRow) => void;
  onEnable: (id: string) => void;
  onClearFilters: () => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="font-heading text-base font-semibold text-foreground">Sources</h2>
        <span className="text-xs text-muted-foreground">
          {filtered === null ? total : `${filtered} of ${total}`} scrapers
        </span>
      </div>
      {rows.length === 0 ? (
        <StatePanel
          variant="empty"
          title="No scraper matches these filters"
          action={
            <Button variant="outline" size="sm" onClick={onClearFilters}>
              Clear filters
            </Button>
          }
        />
      ) : (
        <Table framed className="table-fixed">
          <colgroup>
            <col className="w-[28%]" />
            <col className="w-[9%]" />
            <col className="w-[13%]" />
            <col className="w-[18%]" />
            <col className="w-[14%]" />
            <col className="w-[8%]" />
            <col className="w-[10%]" />
          </colgroup>
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead>Runtime</TableHead>
              <TableHead>Schedule</TableHead>
              <TableHead>Last run</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Next</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) => {
              const selected = s.id === selectedId;
              const disabledText = s.enabled ? null : disabledReasonText(s.disabled_by, s.paused_reason);
              const startedMs = s.last_started_at ? Date.parse(s.last_started_at) : null;
              const nextMs = s.next_run_at ? Date.parse(s.next_run_at) : null;
              return (
                <TableRow key={s.id} selected={selected} aria-current={selected ? "true" : undefined}>
                  <TableCell className="overflow-hidden">
                    <button
                      type="button"
                      onClick={() => onSelect(s.id)}
                      className="block w-full rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                    >
                      <span className="block truncate text-xs font-medium text-foreground" title={s.source}>
                        {s.source}
                      </span>
                      <span className="block truncate font-code text-2xs text-muted-foreground">{s.id}</span>
                    </button>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    <span title={`runtime ${s.runtime} · queue ${s.queue}`}>{s.queue.replace("scrape.", "")}</span>
                    {s.has_override && (
                      <span
                        role="img"
                        aria-label="config override active"
                        title="config override active"
                        className="ml-1.5 inline-block size-1.5 rounded-full bg-primary align-middle"
                      />
                    )}
                  </TableCell>
                  <TableCell className="overflow-hidden text-xs text-muted-foreground">
                    <span
                      title={s.schedule}
                      className={`block truncate ${isHumanized(s.schedule) ? "" : "font-code"}`}
                    >
                      {humanizeCron(s.schedule)}
                    </span>
                  </TableCell>
                  <TableCell className="overflow-hidden text-xs text-muted-foreground">
                    {startedMs === null ? (
                      "never"
                    ) : (
                      <span className="block truncate" title={fmtDateTime(s.last_started_at)}>
                        {nowMs - startedMs < DAY_MS ? fmtTime(s.last_started_at) : fmtAgo(s.last_started_at, nowMs)}
                        {" · "}
                        <span className={runStatusClass(s.last_status ?? "")}>{lastRunOutcome(s)}</span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="overflow-hidden">
                    {s.status === "loading" ? (
                      <Skeleton className="h-5 w-14 rounded-full" aria-label="Loading status" />
                    ) : (
                      <StatusBadge status={s.status} />
                    )}
                    {disabledText && (
                      <div className="mt-1 truncate text-2xs text-muted-foreground" title={disabledText}>
                        {disabledText}
                      </div>
                    )}
                  </TableCell>
                  <TableCell
                    className={`text-xs ${schedulerOk || nextMs === null ? "text-muted-foreground" : "text-destructive-text line-through"}`}
                    title={
                      nextMs === null
                        ? s.enabled
                          ? "invalid cron"
                          : "disabled"
                        : schedulerOk
                          ? fmtDateTime(s.next_run_at)
                          : `${fmtDateTime(s.next_run_at)} · scheduler down, will not fire`
                    }
                  >
                    {nextMs === null
                      ? "–"
                      : nextMs - nowMs < DAY_MS
                        ? fmtTime(s.next_run_at)
                        : fmtShortDate(s.next_run_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {canManage &&
                      (s.enabled ? (
                        <Button variant="ghost" size="sm" aria-label={`Disable ${s.source}`} onClick={() => onDisable(s)}>
                          Disable
                        </Button>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Enable ${s.source}`}
                          onClick={() => onEnable(s.id)}
                          disabled={enablingId === s.id}
                        >
                          {enablingId === s.id ? "Enabling…" : "Enable"}
                        </Button>
                      ))}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
