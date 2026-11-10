"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { invalidateIocViews } from "@/components/intelligence/ioc/ioc-detail-body";
import { BarSeries } from "@/components/ui/bar-series";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { MeterBar } from "@/components/ui/meter-bar";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { IocFpAnalytics, IocFpBucket } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { fmtShortDate } from "@/lib/format";

/** Nada batang FP: >=50% merah, >=25% kuning, selain itu hijau (ambang sama dengan panel lama). */
function fpTone(rate: number): "destructive" | "warning" | "success" {
  return rate >= 0.5 ? "destructive" : rate >= 0.25 ? "warning" : "success";
}

/** Sumber/tipe dengan FP > 50% dari minimal 5 IOC ditandai (sama dengan aturan `source_fp_warning`). */
const isHighFp = (b: IocFpBucket) => b.fp_rate > 0.5 && b.total_iocs >= 5;

/** Tampilan "FP analytics" (spec 2b 6.9): FP per tipe (MeterBar), saran allowlist (>=3 FP, 0 TP) dengan
 * "Apply all suggestions" (`manage_ioc`), lalu FP per sumber dan tren verdict FP 30 hari. */
export function IocFpAnalyticsPanel() {
  const can = useCan();
  const qc = useQueryClient();
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
      invalidateIocViews(qc);
    } catch (e) {
      toast.error(`Failed: ${(e as Error).message}`);
    } finally {
      setApplying(false);
      setConfirmApply(false);
    }
  }

  if (query.isPending) return <StatePanel variant="loading" title="Loading FP analytics" />;
  if (query.isError || !query.data)
    return (
      <StatePanel
        variant="error"
        title="Could not load FP analytics"
        action={
          <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
            Retry
          </Button>
        }
      />
    );

  const d = query.data;
  const byType = Object.entries(d.fp_by_type).sort((a, b) => b[1].fp_rate - a[1].fp_rate);
  const bySource = Object.entries(d.fp_by_source).sort((a, b) => b[1].fp_rate - a[1].fp_rate);
  const suggestions = d.suggested_allowlist;
  const trend = d.fp_trend ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid items-start gap-4 lg:grid-cols-[2fr_3fr]">
        <Card>
          <div className="flex flex-col gap-3 px-5">
            <h2 className="font-heading text-base font-semibold">FP rate by IOC type</h2>
            {byType.length === 0 ? (
              <p className="text-xs text-muted-foreground">No feedback data yet.</p>
            ) : (
              <ul className="flex flex-col gap-2.5">
                {byType.map(([t, b]) => (
                  <li key={t} className="grid grid-cols-[5rem_1fr] items-center gap-3">
                    <span className="font-code text-xs text-foreground">{t}</span>
                    <MeterBar
                      value={Math.round(b.fp_rate * 100)}
                      max={100}
                      tone={fpTone(b.fp_rate)}
                      aria-label={`FP rate for ${t}`}
                      label={`${Math.round(b.fp_rate * 100)}% · ${b.fp_count} / ${b.total_iocs}`}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <Card>
          <div className="flex flex-wrap items-start justify-between gap-3 px-5">
            <div>
              <h2 className="font-heading text-base font-semibold">Suggested for allowlist</h2>
              <p className="text-xs text-muted-foreground">Values with many FP verdicts and no TP</p>
            </div>
            {suggestions.length > 0 && can("manage_ioc") && (
              <Button size="sm" variant="outline" onClick={() => setConfirmApply(true)}>
                Apply all suggestions
              </Button>
            )}
          </div>
          <div className="px-2">
            {suggestions.length === 0 ? (
              <StatePanel
                variant="empty"
                title="No suggestions"
                description="A value is suggested after at least 3 FP verdicts and no TP."
                className="mx-3"
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-3">IOC value</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Verdicts</TableHead>
                    <TableHead>Allowlist as</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {suggestions.map((s) => (
                    <TableRow key={`${s.ioc_type}:${s.value}`}>
                      <TableCell className="max-w-64 truncate pl-3 font-code text-xs text-foreground" title={s.value}>
                        {s.value}
                      </TableCell>
                      <TableCell>
                        <Chip kind="flag" value={s.ioc_type} />
                      </TableCell>
                      <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                        {s.tp_count} TP · {s.fp_count} FP
                      </TableCell>
                      <TableCell className="font-code text-xs text-muted-foreground">{s.allowlist_type}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </Card>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card>
          <div className="px-5">
            <h2 className="font-heading text-base font-semibold">FP rate by source</h2>
          </div>
          <div className="px-2">
            {bySource.length === 0 ? (
              <StatePanel variant="empty" title="No feedback data yet" className="mx-3" />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-3">Source</TableHead>
                    <TableHead className="text-right">FP / total</TableHead>
                    <TableHead>Rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bySource.map(([name, b]) => (
                    <TableRow key={name}>
                      <TableCell className="max-w-56 pl-3 text-xs whitespace-normal text-foreground">
                        {name}
                        {isHighFp(b) && <Chip kind="flag" value="high FP" className="ml-1.5 bg-destructive/15 text-destructive-text" />}
                      </TableCell>
                      <TableCell className="text-right font-code text-xs text-muted-foreground">
                        {b.fp_count} / {b.total_iocs}
                      </TableCell>
                      <TableCell className="min-w-36">
                        <MeterBar
                          value={Math.round(b.fp_rate * 100)}
                          max={100}
                          tone={fpTone(b.fp_rate)}
                          aria-label={`FP rate for ${name}`}
                          label={`${Math.round(b.fp_rate * 100)}%`}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </Card>

        <Card>
          <div className="flex flex-col gap-3 px-5">
            <h2 className="font-heading text-base font-semibold">FP verdicts per day, 30 days</h2>
            {trend.length === 0 ? (
              <p className="text-xs text-muted-foreground">No FP verdicts in the last 30 days.</p>
            ) : (
              <BarSeries
                labels={trend.map((t) => fmtShortDate(t.date))}
                values={trend.map((t) => t.fp_count)}
                aria-label="FP verdicts per day over the last 30 days"
                tone="neutral"
              />
            )}
          </div>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmApply}
        onOpenChange={setConfirmApply}
        title="Apply all suggestions to the allowlist?"
        description={`Adds ${suggestions.length} entr${suggestions.length === 1 ? "y" : "ies"} to the IOC allowlist.`}
        warning="Existing matching IOCs are not deleted; filtering applies to new articles from now on."
        confirmLabel="Apply all"
        cancelVariant="ghost"
        confirmLoading={applying}
        onConfirm={() => void applySuggestions()}
      />
    </div>
  );
}
