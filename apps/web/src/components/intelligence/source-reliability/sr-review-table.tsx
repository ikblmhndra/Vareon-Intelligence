"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { RowMenu } from "@/components/ui/row-menu";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  gradeChipClass,
  invalidateSr,
  useSrReview,
  type SREntry,
} from "@/components/intelligence/source-reliability/sr-model";
import { SrEntryDialog } from "@/components/intelligence/source-reliability/sr-entry-dialog";
import { useCan } from "@/lib/auth/permissions";

/** Kode alasan saran dari `cti_core.confidence.suggest_grade` -> teks UI (P6 spec 5.3). */
const REASON_TEXT: Record<string, string> = {
  off_topic: "often off-topic (rejected ≥30%) with few artefacts",
  ioc_false_positives: "IOCs often marked false positive",
  reports_first: "often reports first",
};

/** Di atas ini sumber lebih sering salah daripada benar di mata analis: teksnya merah. */
const IOC_FP_ALERT_PCT = 50;

function pct(v: number) {
  return `${Math.round(v)}%`;
}

/** Tampilan "Needs review": baris grade bawaan (`origin='default'`) dengan statistik 30 hari dan saran
 * grade dari data. Konfirmasi mengubah baris jadi milik analis (`origin='analyst'`), jadi baris itu
 * keluar dari antrean ini dan muncul sebagai entri analis di "All sources". */
export function SrReviewTable() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [editEntry, setEditEntry] = useState<SREntry | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const reviewQuery = useSrReview(true);

  async function confirm(entry: SREntry, grade: string | null) {
    setBusyId(entry.id);
    // finally: error jaringan (fetch melempar) tidak boleh membuat baris terkunci "busy" selamanya.
    try {
      const { error } = await api.POST("/api/sr/entries/{entry_id}/confirm", {
        params: { path: { entry_id: entry.id } },
        body: { reliability_grade: grade },
      });
      if (error) {
        toast.error("Confirm failed.");
        return;
      }
    } catch {
      toast.error("Confirm failed.");
      return;
    } finally {
      setBusyId(null);
    }
    toast.success(`${entry.source_name}: grade ${grade ?? entry.reliability_grade} confirmed.`);
    invalidateSr(queryClient);
  }

  const manage = can("manage_sources");
  const items = reviewQuery.data;

  return (
    <Card>
      <div className="px-5">
        <h2 className="font-heading text-base font-semibold">Needs review</h2>
        <p className="text-xs text-muted-foreground">
          {items
            ? `${items.length} auto-graded source${items.length === 1 ? "" : "s"} awaiting review · statistics over the last 30 days`
            : "Auto-graded sources with their last 30 days of statistics"}
        </p>
      </div>
      <div className="px-2">
        {reviewQuery.isPending && <StatePanel variant="loading" title="Loading review queue" className="mx-3" />}
        {reviewQuery.isError && (
          <StatePanel
            variant="error"
            title="Could not load the review queue"
            className="mx-3"
            action={
              <Button variant="outline" size="sm" onClick={() => void reviewQuery.refetch()}>
                Retry
              </Button>
            }
          />
        )}
        {items && items.length === 0 && (
          <StatePanel
            variant="empty"
            title="No default grades left to review"
            description="Every auto-graded source has been confirmed by an analyst."
            className="mx-3"
          />
        )}
        {items && items.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Kind</TableHead>
                <TableHead>Grade</TableHead>
                <TableHead title="Multi-source stories this source led / multi-source stories it is in">Leads</TableHead>
                <TableHead className="whitespace-nowrap">Articles (30 d)</TableHead>
                <TableHead
                  className="whitespace-nowrap"
                  title="Share of the source's items rejected as not cyber-related (marketing, best practice). Measures off-topic content, not inaccuracy."
                >
                  Off-topic
                </TableHead>
                <TableHead className="whitespace-nowrap">Artefact %</TableHead>
                <TableHead className="whitespace-nowrap">IOC FP %</TableHead>
                <TableHead>Why</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it) => {
                const e = it.entry;
                const busy = busyId === e.id;
                const suggested = it.suggested_grade;
                const applyCode = suggested ? `${suggested}${e.credibility_code}` : e.admiralty_code;
                return (
                  <TableRow
                    key={e.id}
                    className={manage ? "cursor-pointer" : undefined}
                    onClick={manage ? () => setEditEntry(e) : undefined}
                  >
                    <TableCell className="min-w-36 px-4 text-xs whitespace-normal">
                      <button
                        type="button"
                        disabled={!manage}
                        className="rounded-sm text-left font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                      >
                        {e.source_name}
                      </button>
                    </TableCell>
                    <TableCell className="px-4">{e.content_kind ? <Chip kind="flag" value={e.content_kind} /> : "—"}</TableCell>
                    <TableCell className="px-4 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 font-code text-xs">
                        <Chip kind="grade" value={e.reliability_grade} className={gradeChipClass(e.reliability_grade)} />
                        {suggested && suggested !== e.reliability_grade && (
                          <>
                            <span aria-hidden="true">→</span>
                            <span className="sr-only">suggested</span>
                            <Chip kind="grade" value={applyCode} className={gradeChipClass(suggested)} />
                          </>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="px-4 font-code text-xs">
                      {it.lead_count} / {it.multi_source_stories}
                    </TableCell>
                    <TableCell className="px-4 font-code text-xs">{it.articles}</TableCell>
                    <TableCell className="px-4 font-code text-xs" title={`${it.rejected} rejected`}>
                      {pct(it.rejected_pct)}
                    </TableCell>
                    <TableCell className="px-4 font-code text-xs" title={`${it.artefact_articles} with artefacts`}>
                      {pct(it.artefact_pct)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        "px-4 font-code text-xs",
                        it.ioc_verdicts > 0 && it.ioc_fp_pct > IOC_FP_ALERT_PCT && "text-destructive-text",
                      )}
                      title={`${it.ioc_fp} of ${it.ioc_verdicts} IOC verdicts`}
                    >
                      {it.ioc_verdicts ? pct(it.ioc_fp_pct) : "—"}
                    </TableCell>
                    {/* Alasan saran panjang: dibungkus supaya tombol aksi tidak terdorong keluar layar. */}
                    <TableCell className="min-w-44 px-4 text-xs whitespace-normal text-muted-foreground">
                      {it.suggestion_reasons.length > 0
                        ? it.suggestion_reasons.map((r) => REASON_TEXT[r] ?? r).join("; ")
                        : "—"}
                    </TableCell>
                    <TableCell className="px-2" onClick={(ev) => ev.stopPropagation()}>
                      {manage && (
                        <div className="flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="whitespace-nowrap"
                            disabled={busy}
                            onClick={() => void confirm(e, suggested)}
                          >
                            {suggested ? "Apply" : "Confirm"} {applyCode}
                          </Button>
                          <RowMenu
                            label={`Actions for ${e.source_name}`}
                            items={[
                              // Tanpa saran, tombol utama sudah "Confirm {kode}"; dengan saran, mempertahankan
                              // grade sekarang tetap tersedia di sini.
                              {
                                label: `Confirm ${e.admiralty_code}`,
                                onSelect: () => void confirm(e, null),
                                hidden: !suggested || suggested === e.reliability_grade || busy,
                              },
                              { label: "Edit", onSelect: () => setEditEntry(e) },
                            ]}
                          />
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      <SrEntryDialog
        key={editEntry?.id ?? "none"}
        mode="edit"
        entry={editEntry}
        open={editEntry !== null}
        onClose={() => setEditEntry(null)}
        onSaved={() => invalidateSr(queryClient)}
      />
    </Card>
  );
}
