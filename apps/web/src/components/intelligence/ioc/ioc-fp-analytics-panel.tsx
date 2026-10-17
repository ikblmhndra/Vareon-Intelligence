"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { IocTypeBadge } from "@/components/intelligence/ioc/ioc-badges";
import type { IocFpAnalytics, IocFpBucket } from "@/lib/api/loose-types";

function FpBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100);
  const color = pct >= 50 ? "bg-destructive" : pct >= 25 ? "bg-warning" : "bg-success";
  const textColor = pct >= 50 ? "text-destructive" : pct >= 25 ? "text-warning" : "text-success";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-background">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`min-w-[34px] font-mono text-xs ${textColor}`}>{pct}%</span>
    </div>
  );
}

/** Port bagian "FP ANALYTICS" (`ioc_mgmt.js:489-621`) -- heuristik
 * false-positive per sumber/tipe + saran allowlist otomatis (>=3 FP,
 * 0 TP pada IOC yang sama). */
export function IocFpAnalyticsPanel() {
  const queryClient = useQueryClient();
  const [applying, setApplying] = useState(false);
  const [confirmApply, setConfirmApply] = useState(false);

  const query = useQuery({
    queryKey: ["intelligence", "ioc-fp-analytics"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/fp-analytics");
      if (error) throw error;
      return data as unknown as IocFpAnalytics;
    },
  });

  async function applySuggestions() {
    setApplying(true);
    try {
      const { data, error } = await api.POST("/api/iocs/fp-analytics/apply-suggestions");
      if (error) throw new Error(JSON.stringify(error));
      const r = data as { added: number; skipped: number };
      toast.success(`Added ${r.added} entr${r.added === 1 ? "y" : "ies"}${r.skipped ? `, ${r.skipped} skipped` : ""}.`);
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-fp-analytics"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-allowlist"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-list"] });
    } catch (e) {
      toast.error(`Failed: ${(e as Error).message}`);
    } finally {
      setApplying(false);
    }
  }

  const d = query.data;
  const bySource = d ? Object.entries(d.fp_by_source).sort((a, b) => b[1].fp_rate - a[1].fp_rate) : [];
  const byType = d ? Object.entries(d.fp_by_type).sort((a, b) => b[1].fp_rate - a[1].fp_rate) : [];
  const suggestions = d?.suggested_allowlist ?? [];

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">FP Analytics</h2>

      {query.isPending && <p className="py-4 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-4 text-center text-xs text-destructive">Failed to load FP analytics.</p>}

      {d && (
        <>
          <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <div className="mb-2 text-sm font-semibold text-muted-foreground">FP Rate by Source</div>
              <FpBucketTable rows={bySource} nameHeader="Source" showTypeBadge={false} />
            </div>
            <div>
              <div className="mb-2 text-sm font-semibold text-muted-foreground">FP Rate by IOC Type</div>
              <FpBucketTable rows={byType} nameHeader="Type" showTypeBadge />
            </div>
          </div>

          <div className="mb-2 flex flex-wrap items-center gap-2.5">
            <span className="text-sm font-semibold text-muted-foreground">
              Suggested Allowlist Entries ({suggestions.length})
            </span>
            {suggestions.length > 0 && (
              <Button size="sm" variant="outline" disabled={applying} className="h-6 border-destructive/40 px-2 text-xs text-destructive" onClick={() => setConfirmApply(true)}>
                Apply All to Allowlist
              </Button>
            )}
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>IOC Value</TableHead>
                <TableHead className="text-center">Verdicts</TableHead>
                <TableHead>Allowlist As</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {suggestions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-4 text-center text-xs text-muted-foreground">
                    No suggestions — need ≥3 FP verdicts and 0 TP on same IOC
                  </TableCell>
                </TableRow>
              )}
              {suggestions.map((s) => (
                <TableRow key={`${s.ioc_type}:${s.value}`}>
                  <TableCell>
                    <IocTypeBadge type={s.ioc_type} />
                  </TableCell>
                  <TableCell className="max-w-[280px] truncate font-code text-[13px] text-foreground" title={s.value}>
                    {s.value}
                  </TableCell>
                  <TableCell className="text-center font-mono text-xs text-destructive">{s.fp_count} FP</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{s.allowlist_type}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}

      <ConfirmDialog
        open={confirmApply}
        onOpenChange={setConfirmApply}
        title="Apply all suggestions to allowlist?"
        description={`Adds ${suggestions.length} entr${suggestions.length === 1 ? "y" : "ies"} to the IOC allowlist.`}
        warning="Existing matching IOCs are NOT deleted retroactively -- filtering only applies to new articles going forward."
        confirmLabel="Apply All"
        onConfirm={() => void applySuggestions()}
      />
    </div>
  );
}

function FpBucketTable({ rows, nameHeader, showTypeBadge }: { rows: [string, IocFpBucket][]; nameHeader: string; showTypeBadge: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{nameHeader}</TableHead>
          <TableHead className="text-center">FP/Total</TableHead>
          <TableHead>Rate</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.length === 0 && (
          <TableRow>
            <TableCell colSpan={3} className="py-4 text-center text-xs text-muted-foreground">
              No feedback data yet
            </TableCell>
          </TableRow>
        )}
        {rows.map(([name, s]) => {
          const highFp = s.fp_rate > 0.5 && s.total_iocs >= 5;
          return (
            <TableRow key={name}>
              <TableCell className="font-mono text-xs text-foreground">
                {showTypeBadge ? <IocTypeBadge type={name} /> : name}
                {highFp && (
                  <span className="ml-1.5 rounded-full border border-destructive/35 bg-destructive/12 px-1 py-0.5 text-xs text-destructive-text">HIGH FP</span>
                )}
              </TableCell>
              <TableCell className="text-center font-mono text-xs text-muted-foreground">
                {s.fp_count} / {s.total_iocs}
              </TableCell>
              <TableCell className="min-w-[120px]">
                <FpBar rate={s.fp_rate} />
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
