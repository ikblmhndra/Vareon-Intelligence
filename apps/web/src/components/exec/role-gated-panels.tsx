"use client";

import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useCan } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";
import { cvssColorClass } from "@/lib/exec/format";
import { defang } from "@/lib/intelligence/defang";
import type { ExecDashboardV2, IocFeedbackResponse } from "@/lib/api/loose-types";

function EmptyNote() {
  return <p className="py-3 font-mono text-xs text-muted-foreground">Nothing to show right now.</p>;
}

/** Port Cluster List role-gated (`exec.js:494-509`). Klik summary title
 * legacy pindah ke tab Intelligence (`switchTab('intelligence',null)`)
 * -- rute itu belum ada di Next.js (Grup G7, belum dibangun), jadi
 * baris di sini TANPA link, bukan link mati ke 404. */
export function ClusterList({ d }: { d: ExecDashboardV2 }) {
  if (d.recent_clusters_summary.length === 0) return <EmptyNote />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Summary</TableHead>
          <TableHead>Size</TableHead>
          <TableHead>Actors</TableHead>
          <TableHead>Last Seen</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {d.recent_clusters_summary.map((c) => (
          <TableRow key={c.cluster_id}>
            <TableCell className="text-xs text-primary">{c.summary_title || "—"}</TableCell>
            <TableCell className="font-mono text-xs">{c.size || "—"}</TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">
              {c.threat_actors.slice(0, 3).join(", ") || "—"}
            </TableCell>
            <TableCell className="font-mono text-xs">{c.last_seen || "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Port FP Feedback Queue + `execFpVote()` (`exec.js:511-534,566-575`).
 * Kontrak DIGANTI ke yang beneran (`POST /api/iocs/{ioc_id}/feedback`,
 * body `{verdict,note}`) -- kontrak lama (`POST /api/iocs/feedback`,
 * `{ioc_type,value,is_true_positive}`) udah gak ada di backend (gap #7).
 * `id` per row sekarang ke-serialize (fix backend Fase 8 Grup F, lihat
 * `services/exec_dashboard.py::_get_pending_fp_queue()`). */
export function FpQueue({ d }: { d: ExecDashboardV2 }) {
  const queryClient = useQueryClient();
  const can = useCan();
  const [voting, setVoting] = useState<number | null>(null);

  async function vote(iocId: number, verdict: "tp" | "fp") {
    setVoting(iocId);
    try {
      const { data, error } = await api.POST("/api/iocs/{ioc_id}/feedback", {
        params: { path: { ioc_id: iocId } },
        body: { verdict },
      });
      if (error) throw new Error(JSON.stringify(error));
      const result = data as unknown as IocFeedbackResponse;
      toast.success(verdict === "tp" ? "Marked as true positive." : "Marked as false positive.");
      if (result.source_fp_warning) {
        const w = result.source_fp_warning;
        toast.warning(
          `Source "${w.source_name}" has a ${(w.fp_rate * 100).toFixed(0)}% false-positive rate (${w.fp_count}/${w.total_iocs} IOCs).`,
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["exec", "dashboard-v2"] });
    } catch (e) {
      toast.error(`Vote failed: ${(e as Error).message}`);
    } finally {
      setVoting(null);
    }
  }

  if (d.pending_fp_queue.length === 0) return <EmptyNote />;

  return (
    <>
      <p className="mb-2 font-mono text-xs text-muted-foreground">
        Showing {d.pending_fp_queue.length} of {Math.max(d.pending_fp_total, d.pending_fp_queue.length).toLocaleString()}{" "}
        pending (latest first)
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>IOC</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Last Seen</TableHead>
            <TableHead>Confidence</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {d.pending_fp_queue.map((ioc) => {
            const conf = ioc.confidence_score || 0;
            const confColor = conf >= 70 ? "text-primary" : conf >= 50 ? "text-foreground" : "text-destructive";
            return (
              <TableRow key={ioc.id}>
                <TableCell className="font-code text-xs text-primary">{ioc.value ? defang(ioc.type, ioc.value) : "—"}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{ioc.type || "—"}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{ioc.last_seen || "—"}</TableCell>
                <TableCell className={cn("font-mono text-xs", confColor)}>{conf}%</TableCell>
                <TableCell>
                  {can("manage_ioc") && (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-6 px-1.5 text-xs"
                        disabled={voting === ioc.id}
                        title="TP / restore"
                        aria-label="TP / restore"
                        onClick={() => void vote(ioc.id, "tp")}
                      >
                        <ThumbsUpIcon aria-hidden />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-6 px-1.5 text-xs"
                        disabled={voting === ioc.id}
                        title="FP: remove from feeds"
                        aria-label="FP: remove from feeds"
                        onClick={() => void vote(ioc.id, "fp")}
                      >
                        <ThumbsDownIcon aria-hidden />
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </>
  );
}

/** Port Critical CVE Feed role-gated (`exec.js:536-559`). `epss_score`/
 * `first_seen` DIHAPUS -- gak ada di response (`_get_critical_cves()`
 * cuma filter `cisa_kev`, kolom `epss_score` gak ada di `CveTracker`,
 * lihat docstring `exec_dashboard.py`). Klik CVE ID -> `/cve` (link
 * polos, BUKAN auto-buka modal -- butuh row `CveOut` lengkap yang cuma
 * ada di query list `/cve`, sama pola defer kayak Grup E). */
export function CriticalCveFeed({ d }: { d: ExecDashboardV2 }) {
  if (d.critical_cves.length === 0) return <EmptyNote />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>CVE</TableHead>
          <TableHead>Tech</TableHead>
          <TableHead>CVSS</TableHead>
          <TableHead>KEV</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {d.critical_cves.map((c) => (
          <TableRow key={c.cve_id}>
            <TableCell className="font-mono text-xs text-primary">
              <Link href="/cve" className="hover:underline">
                {c.cve_id || "—"}
              </Link>
            </TableCell>
            <TableCell className="text-xs">{c.tech || "—"}</TableCell>
            <TableCell className={cn("font-mono text-xs", cvssColorClass(c.cve_score))}>
              {c.cve_score != null ? c.cve_score.toFixed(1) : "—"}
            </TableCell>
            <TableCell>{c.cisa_kev ? <span className="font-mono text-xs text-destructive">KEV</span> : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
