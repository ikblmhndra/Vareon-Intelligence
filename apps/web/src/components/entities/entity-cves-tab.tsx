"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { SubListSection, SUBLIST_PAGE_SIZE } from "@/components/entities/entity-subtab";
import { CveDetailCard } from "@/components/cve/cve-detail-card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { relativeTime } from "@/lib/cve/freshness";
import { severityColorClass } from "@/lib/cve/format";
import { cn } from "@/lib/utils";

type EntityDetail = components["schemas"]["EntityDetail"];
type CveOut = components["schemas"]["CveOut"];

/** CVE yang dilacak untuk entity; baris membuka panel detail CVE di dialog (dicari lewat `/api/cve?search=`, cocokkan `id`). */
export function EntityCvesTab({ entity }: { entity: EntityDetail }) {
  const [page, setPage] = useState(1);
  const [cve, setCve] = useState<CveOut | null>(null);
  const [opening, setOpening] = useState<number | null>(null);

  const list = useQuery({
    queryKey: ["entity-cves", entity.id, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/cves", {
        params: {
          path: { entity_id: entity.id },
          query: { limit: SUBLIST_PAGE_SIZE, offset: (page - 1) * SUBLIST_PAGE_SIZE },
        },
      });
      if (error || !data) throw new Error("cves failed");
      return data;
    },
  });

  async function openCve(row: { id: number; cve_id: string }) {
    setOpening(row.id);
    try {
      const { data, error } = await api.GET("/api/cve", {
        params: { query: { search: row.cve_id, page_size: 20, include_fp: true } },
      });
      const found = data?.cves.find((c) => c.id === row.id) ?? data?.cves.find((c) => c.cve_id === row.cve_id);
      if (error || !found) throw new Error("not found");
      setCve(found);
    } catch {
      toast.error(`Could not open ${row.cve_id}.`);
    } finally {
      setOpening(null);
    }
  }

  return (
    <>
      <SubListSection
        id="entity-cves"
        title="CVEs"
        status={list.status}
        total={list.data?.total ?? 0}
        emptyText="No tracked CVEs for this entity yet."
        page={page}
        onPageChange={setPage}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>CVE</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead>Tech</TableHead>
              <TableHead>Detected</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <button
                    type="button"
                    disabled={opening === c.id}
                    onClick={() => void openCve(c)}
                    className="rounded font-code text-xs text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
                  >
                    {c.cve_id}
                  </button>
                  {c.cisa_kev && (
                    <Badge variant="destructive" className="ml-2">
                      KEV
                    </Badge>
                  )}
                </TableCell>
                <TableCell className={cn("text-xs font-medium", severityColorClass(c.cve_severity ?? ""))}>
                  {c.cve_severity ?? "-"}
                </TableCell>
                <TableCell className="text-right font-code text-xs">{c.cve_score?.toFixed(1) ?? "-"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{c.tech ?? "-"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{relativeTime(c.detected_on)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </SubListSection>
      {/* Panel detail CVE yang sama dengan tab CVEs di CVE Tracker, di dalam dialog. */}
      <Dialog open={cve !== null} onOpenChange={(o) => !o && setCve(null)}>
        <DialogContent showCloseButton className="max-h-[90vh] w-full overflow-y-auto p-0 sm:max-w-2xl">
          <DialogTitle className="sr-only">{cve?.cve_id} details</DialogTitle>
          {cve && <CveDetailCard cve={cve} className="border-0" onLeaveList={() => setCve(null)} />}
        </DialogContent>
      </Dialog>
    </>
  );
}
