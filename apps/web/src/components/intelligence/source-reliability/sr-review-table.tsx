"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { GRADE_BADGE_CLASS } from "@/lib/intelligence/format";
import type { components } from "@/lib/api/schema";
import { SrEntryDialog } from "@/components/intelligence/source-reliability/sr-entry-dialog";
import { useCan } from "@/lib/auth/permissions";

type SREntry = components["schemas"]["SREntryOut"];

/** Kode alasan saran dari `cti_core.confidence.suggest_grade` -> teks UI (P6 spec 5.3). */
const REASON_TEXT: Record<string, string> = {
  off_topic: "often off-topic (rejected ≥30%) with few artefacts",
  ioc_false_positives: "IOCs often marked false positive",
  reports_first: "often reports first",
};

function pct(v: number) {
  return `${Math.round(v)}%`;
}

/** Tab "Needs review": baris grade bawaan (`origin='default'`) dengan statistik 30 hari dan saran
 * grade dari data. Konfirmasi mengubah baris jadi milik analis (`origin='analyst'`), jadi baris itu
 * keluar dari antrean ini dan muncul sebagai entri analis di tab "All sources". */
export function SrReviewTable() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [editEntry, setEditEntry] = useState<SREntry | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const reviewQuery = useQuery({
    queryKey: ["intelligence", "sr-review"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/review");
      if (error) throw error;
      return data.items;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "sr-review"] });
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "sr-entries"] });
  }

  async function confirm(entry: SREntry, grade: string | null) {
    setBusyId(entry.id);
    const { error } = await api.POST("/api/sr/entries/{entry_id}/confirm", {
      params: { path: { entry_id: entry.id } },
      body: { reliability_grade: grade },
    });
    setBusyId(null);
    if (error) {
      toast.error("Confirm failed.");
      return;
    }
    toast.success(`${entry.source_name}: grade ${grade ?? entry.reliability_grade} confirmed.`);
    invalidate();
  }

  const manage = can("manage_sources");

  return (
    <div>
      {reviewQuery.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {reviewQuery.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load.</p>}

      {reviewQuery.data && (
        <>
          <p className="mb-2 font-mono text-xs text-muted-foreground">
            {reviewQuery.data.length} default grade{reviewQuery.data.length !== 1 ? "s" : ""} awaiting review
            (statistics over the last 30 days)
          </p>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Grade</TableHead>
                <TableHead className="whitespace-nowrap">Articles (30 d)</TableHead>
                <TableHead
                  className="whitespace-nowrap"
                  title="Share of the source's items rejected as not cyber-related (marketing, best practice). Measures off-topic content, not inaccuracy."
                >
                  Rejected % <span className="text-muted-foreground">ⓘ</span>
                </TableHead>
                <TableHead className="whitespace-nowrap">Artefact %</TableHead>
                <TableHead title="Multi-source stories this source led / multi-source stories it is in">Leads</TableHead>
                <TableHead className="whitespace-nowrap">IOC FP %</TableHead>
                <TableHead>Suggestion</TableHead>
                {manage && <TableHead />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {reviewQuery.data.length === 0 && (
                <TableRow>
                  <TableCell colSpan={manage ? 10 : 9} className="py-8 text-center text-xs text-muted-foreground">
                    No default grades left to review
                  </TableCell>
                </TableRow>
              )}
              {reviewQuery.data.map((it) => {
                const e = it.entry;
                const busy = busyId === e.id;
                return (
                  <TableRow key={e.id}>
                    <TableCell className="text-xs">{e.source_name}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{e.content_kind ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn("text-xs", GRADE_BADGE_CLASS[e.reliability_grade])}>
                        {e.reliability_grade}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-code text-xs">{it.articles}</TableCell>
                    <TableCell className="font-code text-xs" title={`${it.rejected} rejected`}>
                      {pct(it.rejected_pct)}
                    </TableCell>
                    <TableCell className="font-code text-xs" title={`${it.artefact_articles} with artefacts`}>
                      {pct(it.artefact_pct)}
                    </TableCell>
                    <TableCell className="font-code text-xs">
                      {it.lead_count} / {it.multi_source_stories}
                    </TableCell>
                    <TableCell className="font-code text-xs" title={`${it.ioc_fp} of ${it.ioc_verdicts} IOC verdicts`}>
                      {it.ioc_verdicts ? pct(it.ioc_fp_pct) : "—"}
                    </TableCell>
                    <TableCell className="text-xs">
                      {it.suggested_grade ? (
                        <div className="flex flex-col gap-0.5">
                          <Badge variant="outline" className={cn("w-fit text-xs", GRADE_BADGE_CLASS[it.suggested_grade])}>
                            {it.suggested_grade}
                          </Badge>
                          {it.suggestion_reasons.map((r) => (
                            <span key={r} className="text-muted-foreground">
                              {REASON_TEXT[r] ?? r}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    {manage && (
                      <TableCell>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-1.5 text-xs"
                            disabled={busy}
                            onClick={() => void confirm(e, null)}
                          >
                            Confirm
                          </Button>
                          {it.suggested_grade && (
                            <Button
                              size="sm"
                              className="h-6 whitespace-nowrap px-1.5 text-xs"
                              disabled={busy}
                              onClick={() => void confirm(e, it.suggested_grade)}
                            >
                              Confirm {it.suggested_grade}
                            </Button>
                          )}
                          <Button size="sm" variant="outline" className="h-6 px-1.5 text-xs" onClick={() => setEditEntry(e)}>
                            Edit
                          </Button>
                        </div>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </>
      )}

      <SrEntryDialog
        key={editEntry?.id ?? "none"}
        mode="edit"
        entry={editEntry}
        open={editEntry !== null}
        onClose={() => setEditEntry(null)}
        onSaved={invalidate}
      />
    </div>
  );
}
