"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckIcon, XIcon } from "lucide-react";

import { api } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/format";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";
import { StatePanel } from "@/components/ui/state-panel";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";

const PAGE_SIZE = 10;
const ACCEPTED_ITEMS: Record<string, string> = { __all__: "All", true: "Accepted", false: "Rejected" };

export function ScraperItemsPanel({ scraperId }: { scraperId: string }) {
  const [page, setPage] = useState(1);
  const [acceptedFilter, setAcceptedFilter] = useState("__all__");

  const query = useQuery({
    queryKey: ["scrapers", scraperId, "items", page, acceptedFilter],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/scraper/{scraper_id}/items", {
          params: {
            path: { scraper_id: scraperId },
            query: {
              page,
              page_size: PAGE_SIZE,
              accepted: acceptedFilter === "__all__" ? undefined : acceptedFilter === "true",
            },
          },
        }),
        "Could not load items",
      ),
    retry: noClientRetry,
  });

  const totalPages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <Select
          items={ACCEPTED_ITEMS}
          value={acceptedFilter}
          onValueChange={(v) => {
            if (!v) return;
            setAcceptedFilter(v);
            setPage(1);
          }}
        >
          <SelectTrigger size="sm" aria-label="Filter items by result" className="w-32 font-code text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {Object.entries(ACCEPTED_ITEMS).map(([v, l]) => (
              <SelectItem key={v} value={v} className="font-code text-xs">
                {l}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {query.isPending && <StatePanel variant="loading" title="Loading items" className="py-6" />}
      {query.isError && <StatePanel variant="error" title="Failed to load items" className="py-6" />}
      {query.data && query.data.items.length === 0 && (
        <p className="py-4 text-center text-xs text-muted-foreground">No items logged yet.</p>
      )}
      {query.data && query.data.items.length > 0 && (
        <Table className="table-fixed">
          <colgroup>
            <col className="w-[46%]" />
            <col className="w-[14%]" />
            <col className="w-[22%]" />
            <col className="w-[18%]" />
          </colgroup>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Result</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Run</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.items.map((it) => (
              <TableRow key={it.id}>
                <TableCell className="truncate text-xs text-foreground" title={it.title}>
                  <a href={it.url} target="_blank" rel="noopener noreferrer" className="hover:underline">
                    {it.title}
                  </a>
                </TableCell>
                <TableCell>
                  {it.accepted ? (
                    <CheckIcon className="size-4 text-success" aria-hidden />
                  ) : (
                    <XIcon className="size-4 text-muted-foreground" aria-hidden />
                  )}
                  <span className="sr-only">{it.accepted ? "Accepted" : "Rejected"}</span>
                </TableCell>
                <TableCell className="font-code text-xs text-muted-foreground">{it.reason ?? "—"}</TableCell>
                <TableCell className="font-code text-xs text-muted-foreground">
                  {fmtDateTime(it.run_at)}
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
