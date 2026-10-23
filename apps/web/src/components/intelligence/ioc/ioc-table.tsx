"use client";

import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { cn } from "@/lib/utils";
import { iocTypeStyle } from "@/lib/intelligence/ioc-style";
import { IocActionabilityChip, IocConfidenceChip, IocTypeBadge } from "@/components/intelligence/ioc/ioc-badges";
import type { IocListResponse, IocStats } from "@/lib/api/loose-types";
import type { IocTarget } from "@/components/intelligence/ioc/ioc-detail-dialog";

const ALL = "__all__";
const IOC_TYPES = Object.keys({
  ip: 0,
  domain: 0,
  url: 0,
  url_with_path: 0,
  email: 0,
  sha256: 0,
  sha1: 0,
  md5: 0,
  cve: 0,
});
const ACTIONABILITY_OPTIONS = ["block_now", "investigate", "monitor", "archive"];
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200];

/** Port `iocmgmtLoad()`+`_renderIocStats()`+`iocmgmtFeedback()`
 * (`ioc_mgmt.js:48-156,623-663`) -- tabel IOC + stat bar per-tipe
 * (klik buat filter) + feedback TP/FP inline. */
export function IocTable({ onSelect }: { onSelect: (target: IocTarget) => void }) {
  const queryClient = useQueryClient();
  const [type, setType] = useState("");
  const [search, setSearch] = useState("");
  const [actionability, setActionability] = useState("");
  const [sortBy, setSortBy] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [feedbackPending, setFeedbackPending] = useState<number | null>(null);

  const statsQuery = useQuery({
    queryKey: ["intelligence", "ioc-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/stats");
      if (error) throw error;
      return data as unknown as IocStats;
    },
  });

  const listQuery = useQuery({
    queryKey: ["intelligence", "ioc-list", type, search, actionability, sortBy, pageSize, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs", {
        params: {
          query: {
            ioc_type: type || undefined,
            search: search || undefined,
            sort_by: sortBy || undefined,
            actionability: actionability || undefined,
            page,
            page_size: pageSize,
          },
        },
      });
      if (error) throw error;
      return data as unknown as IocListResponse;
    },
  });

  async function submitFeedback(iocId: number, verdict: "tp" | "fp") {
    setFeedbackPending(iocId);
    try {
      const { error } = await api.POST("/api/iocs/{ioc_id}/feedback", {
        params: { path: { ioc_id: iocId } },
        body: { verdict },
      });
      if (error) throw new Error(JSON.stringify(error));
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-list"] });
    } finally {
      setFeedbackPending(null);
    }
  }

  const total = listQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      {statsQuery.data && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {statsQuery.data.by_type.map((t) => {
            const s = iocTypeStyle(t.type);
            const active = type === t.type;
            return (
              <button
                key={t.type}
                type="button"
                onClick={() => {
                  setType(active ? "" : t.type);
                  setPage(1);
                }}
                className="rounded-full border px-2 py-1 font-mono text-xs transition-colors"
                style={{
                  background: active ? s.color : s.bg,
                  borderColor: s.border,
                  color: active ? "var(--surface)" : s.color,
                }}
              >
                {s.label}: {t.count}
              </button>
            );
          })}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-end gap-2 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="IOC value…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-48 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Type</Label>
          <Select
            items={{ [ALL]: "All Types", ...Object.fromEntries(IOC_TYPES.map((t) => [t, iocTypeStyle(t).label])) }}
            value={type || ALL}
            onValueChange={(v) => {
              setType(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Types
              </SelectItem>
              {IOC_TYPES.map((t) => (
                <SelectItem key={t} value={t} className="font-mono text-xs">
                  {iocTypeStyle(t).label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Actionability</Label>
          <Select
            items={{ [ALL]: "All", ...Object.fromEntries(ACTIONABILITY_OPTIONS.map((a) => [a, a.replace("_", " ")])) }}
            value={actionability || ALL}
            onValueChange={(v) => {
              setActionability(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All
              </SelectItem>
              {ACTIONABILITY_OPTIONS.map((a) => (
                <SelectItem key={a} value={a} className="font-mono text-xs capitalize">
                  {a.replace("_", " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Sort</Label>
          <Select
            items={{ last_seen: "Last Seen", confidence: "Confidence" }}
            value={sortBy || "last_seen"}
            onValueChange={(v) => {
              setSortBy(v === "last_seen" ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="last_seen" className="font-mono text-xs">
                Last Seen
              </SelectItem>
              <SelectItem value="confidence" className="font-mono text-xs">
                Confidence
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Page Size</Label>
          <Select
            items={Object.fromEntries(PAGE_SIZE_OPTIONS.map((n) => [String(n), String(n)]))}
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(Number(v) || 50);
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-20 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)} className="font-mono text-xs">
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <span className="ml-auto font-mono text-xs text-muted-foreground">{total} IOCs</span>
      </div>

      {listQuery.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {listQuery.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load IOCs.</p>}

      {listQuery.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Value</TableHead>
                <TableHead className="text-center">Confidence</TableHead>
                <TableHead className="text-center">Action</TableHead>
                <TableHead className="text-center">Seen</TableHead>
                <TableHead>First Seen</TableHead>
                <TableHead>Last Seen</TableHead>
                <TableHead className="text-center">Feedback</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {listQuery.data.iocs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="py-6 text-center text-xs text-muted-foreground">
                    No IOCs found
                  </TableCell>
                </TableRow>
              )}
              {listQuery.data.iocs.map((ioc) => (
                <TableRow key={ioc.id} className="cursor-pointer" onClick={() => onSelect({ type: ioc.type, value: ioc.value })}>
                  <TableCell>
                    <IocTypeBadge type={ioc.type} />
                  </TableCell>
                  <TableCell className="max-w-[320px] truncate font-code text-xs text-foreground" title={ioc.value}>
                    {ioc.value}
                  </TableCell>
                  <TableCell className="text-center">
                    <IocConfidenceChip score={ioc.confidence_score} />
                  </TableCell>
                  <TableCell className="text-center">
                    <IocActionabilityChip label={ioc.actionability_label} />
                  </TableCell>
                  <TableCell className="text-center font-mono text-xs text-muted-foreground">{ioc.seen_count || 1}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{ioc.first_seen || "—"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{ioc.last_seen || "—"}</TableCell>
                  <TableCell className="text-center whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      disabled={feedbackPending === ioc.id}
                      onClick={() => void submitFeedback(ioc.id, "tp")}
                      title="True Positive"
                      className={cn("rounded-full border border-success/35 bg-success/10 px-1.5 py-0.5 text-xs text-success-text", feedbackPending === ioc.id && "opacity-50")}
                    >
                      <ThumbsUpIcon aria-hidden />
                    </button>
                    <button
                      type="button"
                      disabled={feedbackPending === ioc.id}
                      onClick={() => void submitFeedback(ioc.id, "fp")}
                      title="False Positive"
                      className={cn("ml-1 rounded-full border border-destructive/35 bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive-text", feedbackPending === ioc.id && "opacity-50")}
                    >
                      <ThumbsDownIcon aria-hidden />
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} total`} onPageChange={setPage} />
          </div>
        </>
      )}
    </div>
  );
}
