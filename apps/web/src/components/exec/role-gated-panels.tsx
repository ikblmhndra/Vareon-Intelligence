"use client";

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityChip, EntityChipList } from "@/components/entities/entity-chip";
import { ShowAll } from "@/components/exec/show-all";
import { IocRemoveDialog } from "@/components/intelligence/ioc/ioc-remove-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { cvssColorClass } from "@/lib/exec/format";
import { fmtAgo, fmtCompactAge } from "@/lib/format";
import { defang } from "@/lib/intelligence/defang";
import { nameChips } from "@/lib/entities/name-chips";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2, IocFeedbackResponse } from "@/lib/api/loose-types";

const LINK =
  "rounded-md text-xs font-medium text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

const COLLAPSED = 5;
const MAX = 20;
const CLUSTER_COLLAPSED = 4;
const CLUSTER_MAX = 10;

function invalidateDashboard(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["exec", "dashboard-v2"] });
}

function warnSourceFp(res: IocFeedbackResponse) {
  const w = res.source_fp_warning;
  if (w) {
    toast.warning(
      `Source "${w.source_name}" has a ${(w.fp_rate * 100).toFixed(0)}% false-positive rate (${w.fp_count}/${w.total_iocs} IOCs).`,
    );
  }
}

/** Kartu "Campaign clusters" (D6). Judul = tautan ke klaster; jendela `days=30` sama dengan jendela daftar
 * Exec supaya klaster itu pasti ada di daftar halaman tujuan. Baris bukan elemen klik: tautan judul dan chip
 * aktor bersaudara. */
export function ClusterList({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const all = d.recent_clusters_summary.slice(0, CLUSTER_MAX);
  const rows = expanded ? all : all.slice(0, CLUSTER_COLLAPSED);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Campaign clusters</CardTitle>
        <CardDescription>Most recent clusters, last 30 days</CardDescription>
      </CardHeader>
      <CardContent>
        {all.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No campaign in the last 30 days</p>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {rows.map((c) => (
                <li key={c.cluster_id} className="space-y-1 py-2">
                  <div className="flex items-start gap-2">
                    <Link
                      href={`/intelligence/campaign-clusters?id=${encodeURIComponent(c.cluster_id)}&days=30`}
                      className={cn(LINK, "min-w-0 flex-1 break-words")}
                    >
                      {c.summary_title || "Untitled cluster"}
                    </Link>
                    <span className="shrink-0 text-2xs text-muted-foreground">
                      {c.size} articles · {fmtCompactAge(c.last_seen)}
                    </span>
                  </div>
                  {c.threat_actors.length > 0 && (
                    <EntityChipList items={nameChips("intrusion-set", c.threat_actors.slice(0, 3))} max={3} />
                  )}
                </li>
              ))}
            </ul>
            <div className="mt-2">
              <ShowAll total={all.length} shown={CLUSTER_COLLAPSED} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Kartu "IOC false-positive queue" (F22). Kontrak: `POST /api/iocs/{ioc_id}/feedback`. TP langsung; FP lewat
 * `IocRemoveDialog` yang sama dengan panel detail IOC. Tombol hanya untuk `manage_ioc` (izin backend yang
 * sebenarnya); tanpa itu baris read-only. Baris bukan elemen klik. */
export function FpQueue({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const qc = useQueryClient();
  const can = useCan();
  const manage = can("manage_ioc");
  const [expanded, setExpanded] = useState(false);
  const [voting, setVoting] = useState<number | null>(null);
  // Dialog tetap terpasang (open dipisah dari target) supaya fokus kembali ke tombol "FP: remove" saat ditutup;
  // target terakhir dipertahankan selama animasi tutup.
  const [removeOpen, setRemoveOpen] = useState(false);
  const [removing, setRemoving] = useState<{ id: number; value: string } | null>(null);

  const all = d.pending_fp_queue.slice(0, MAX);
  const rows = expanded ? all : all.slice(0, COLLAPSED);
  const total = Math.max(d.pending_fp_total, d.pending_fp_queue.length);

  async function restore(id: number) {
    setVoting(id);
    try {
      const { error, response } = await api.POST("/api/iocs/{ioc_id}/feedback", {
        params: { path: { ioc_id: id } },
        body: { verdict: "tp" },
      });
      // Body kosong pada 5xx: `error` undefined tetapi `response.ok` false.
      if (error || !response.ok) throw new Error(error ? JSON.stringify(error) : `HTTP ${response.status}`);
      toast.success("Marked as true positive.");
      invalidateDashboard(qc);
    } catch (e) {
      toast.error(`Vote failed: ${(e as Error).message}`);
    } finally {
      setVoting(null);
    }
  }

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>IOC false-positive queue</CardTitle>
        <CardDescription>Analyst view · IOCs waiting for a verdict, top 20</CardDescription>
        <CardAction>
          <Chip kind="flag" value={`${total.toLocaleString()} pending`} />
        </CardAction>
      </CardHeader>
      <CardContent>
        {all.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No pending IOC</p>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {rows.map((ioc) => {
                const shown = ioc.value ? defang(ioc.type, ioc.value) : "—";
                return (
                  <li key={ioc.id} className="flex items-center gap-3 py-2">
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 truncate font-code text-xs" title={shown}>
                          {shown}
                        </span>
                        {ioc.type && <Chip kind="flag" value={ioc.type} className="shrink-0" />}
                      </div>
                      <p className="text-2xs text-muted-foreground">
                        confidence {ioc.confidence_score ?? "—"} · last seen {fmtAgo(ioc.last_seen)}
                      </p>
                    </div>
                    {manage ? (
                      <div className="flex shrink-0 gap-1.5">
                        <Button
                          size="sm"
                          variant="outline"
                          loading={voting === ioc.id}
                          disabled={voting !== null}
                          onClick={() => void restore(ioc.id)}
                        >
                          TP / restore
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={voting !== null}
                          onClick={() => {
                            setRemoving({ id: ioc.id, value: shown });
                            setRemoveOpen(true);
                          }}
                        >
                          FP: remove
                        </Button>
                      </div>
                    ) : (
                      <span className="shrink-0 text-2xs text-muted-foreground">Read-only</span>
                    )}
                  </li>
                );
              })}
            </ul>
            <div className="mt-2 flex items-center justify-between gap-3">
              <ShowAll total={all.length} shown={COLLAPSED} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
              <p className="ml-auto text-2xs text-muted-foreground">
                Showing {rows.length} of {total.toLocaleString()} pending ·{" "}
                <Link href="/intelligence/ioc-management" className={LINK}>
                  Open IOC management
                </Link>
              </p>
            </div>
          </>
        )}
      </CardContent>
      {removing && (
        <IocRemoveDialog
          open={removeOpen}
          onOpenChange={setRemoveOpen}
          ioc={removing}
          onDone={(res) => {
            toast.success("Marked as false positive.");
            warnSourceFp(res);
            invalidateDashboard(qc);
          }}
        />
      )}
    </Card>
  );
}

/** Kartu "Critical CVE feed" (F23). `epss_score`/`first_seen` tidak ada di response (`_get_critical_cves()` hanya
 * memfilter `cisa_kev`). CVE id = `EntityChip` (halaman entity), bukan modal CVE yang butuh row `CveOut`. */
export function CriticalCveFeed({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const all = d.critical_cves.slice(0, MAX);
  const rows = expanded ? all : all.slice(0, COLLAPSED);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Critical CVE feed</CardTitle>
        <CardDescription>KEV CVEs matched to this client&apos;s tech stack · SOC view</CardDescription>
        <CardAction>
          <Link href="/cve" className={LINK}>
            CVE Tracker →
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {all.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No KEV CVE matches this client&apos;s tech stack</p>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {rows.map((c) => (
                <li key={c.cve_id} className="flex items-center gap-3 py-2">
                  <span className={cn("w-8 shrink-0 font-code text-xs", cvssColorClass(c.cve_score))}>
                    {c.cve_score != null ? c.cve_score.toFixed(1) : "—"}
                  </span>
                  <div className="shrink-0">
                    {c.cve_id ? <EntityChip type="vulnerability" name={c.cve_id} /> : "—"}
                  </div>
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={c.tech}>
                    {c.tech || "—"}
                  </span>
                  {c.cisa_kev && <Chip kind="cve" value="kev" className="shrink-0" />}
                </li>
              ))}
            </ul>
            <div className="mt-2">
              <ShowAll total={all.length} shown={COLLAPSED} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Baris antrean: hanya kartu yang gerbangnya (`view_config.sections`) terbuka; satu kartu mengisi satu baris
 * penuh, dua kartu berdampingan di >= 1024 px. `null` bila tak ada kartu. */
export function QueuesRow({ d }: { d: ExecDashboardV2 }) {
  const { fp_feedback_queue: fp, critical_cve_feed: cve } = d.view_config.sections;
  if (!fp && !cve) return null;
  return (
    <div className={cn("mt-4 grid grid-cols-1 gap-4", fp && cve && "lg:grid-cols-2")}>
      {fp && <FpQueue d={d} />}
      {cve && <CriticalCveFeed d={d} />}
    </div>
  );
}
