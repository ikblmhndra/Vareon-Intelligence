"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/format";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { RunStatusText } from "@/components/scrapers/status-badge";
import { StatePanel } from "@/components/ui/state-panel";

const PAGE_SIZE = 10;

/** "850 ms" / "12.4 s" / "3 m 05 s" -- `duration_ms` mentah susah dibaca untuk run browser yang lama. */
function humanDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} m ${String(Math.round(s % 60)).padStart(2, "0")} s`;
}

/** Ringkasan error run: hanya `stage`, `type`, dan `message` (dipotong). `traceback` SENGAJA tidak
 * ditampilkan: isinya bisa membocorkan path, header, atau potongan respons vendor. */
function errorSummary(errors: { [key: string]: unknown }[]): string | null {
  const first = errors[0];
  if (!first) return null;
  const parts = [first.stage, first.type].filter((x): x is string => typeof x === "string" && x !== "");
  const message = typeof first.message === "string" ? first.message.slice(0, 160) : "";
  const head = parts.join(" · ");
  const more = errors.length > 1 ? ` (+${errors.length - 1} more)` : "";
  return `${head}${head && message ? ": " : ""}${message}${more}` || null;
}

export function ScraperRunsPanel({ scraperId }: { scraperId: string }) {
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["scrapers", scraperId, "runs", page],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/scraper/{scraper_id}/runs", {
          params: { path: { scraper_id: scraperId }, query: { page, page_size: PAGE_SIZE } },
        }),
        "Could not load runs",
      ),
    retry: noClientRetry,
  });

  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div>
      {query.isPending && <StatePanel variant="loading" title="Loading runs" className="py-6" />}
      {query.isError && <StatePanel variant="error" title="Failed to load runs" className="py-6" />}
      {query.data && query.data.runs.length === 0 && (
        <p className="py-4 text-center text-xs text-muted-foreground">No runs recorded yet.</p>
      )}
      {query.data && query.data.runs.length > 0 && (
        <Table className="table-fixed">
          <colgroup>
            <col className="w-[24%]" />
            <col className="w-[14%]" />
            <col className="w-[9%]" />
            <col className="w-[9%]" />
            <col className="w-[12%]" />
            <col className="w-[32%]" />
          </colgroup>
          <TableHeader>
            <TableRow>
              <TableHead>Started</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Found</TableHead>
              <TableHead>New</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.runs.map((r) => (
              <TableRow key={r.run_id}>
                <TableCell className="text-xs text-muted-foreground">
                  <span className="font-code">{fmtDateTime(r.started_at)}</span>
                  <span className="block text-2xs">{r.trigger}</span>
                </TableCell>
                <TableCell>
                  <RunStatusText status={r.status} />
                </TableCell>
                <TableCell className="font-code text-xs text-foreground">{r.items_found}</TableCell>
                <TableCell className="font-code text-xs text-foreground">
                  {r.items_new} new
                  {r.items_dropped > 0 && ` · ${r.items_dropped} dropped`}
                  {r.items_failed > 0 && (
                    <span className="text-destructive-text">{` · ${r.items_failed} failed`}</span>
                  )}
                </TableCell>
                <TableCell className="font-code text-xs whitespace-nowrap text-muted-foreground">
                  {humanDuration(r.duration_ms)}
                </TableCell>
                <TableCell className="text-xs break-words whitespace-normal text-muted-foreground">
                  {errorSummary(r.errors) ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <div className="mt-2">
        <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
      </div>
    </div>
  );
}
