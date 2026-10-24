"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { getActiveClientId } from "@/lib/auth/client-id";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";
import { PirFormDialog } from "@/components/intelligence/pir/pir-form-dialog";
import { PirArticlesDialog } from "@/components/intelligence/pir/pir-articles-dialog";
import { useCan } from "@/lib/auth/permissions";

type PIROut = components["schemas"]["PIROut"];

const PRIORITY_CLASS: Record<string, string> = {
  P1: "text-destructive border-destructive/40",
  P2: "text-warning border-warning/40",
  P3: "text-muted-foreground border-border",
};

/** Port kartu PIR + CRUD (`pir.js:124-287`, `loadPirs`/`openPirModal`/
 * `deletePir`). */
export function PirList() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  // Naik tiap "+ New" -- form add remount fresh, gak bawa isian
  // submit/cancel sebelumnya (pola sama `addKey` di `sr-table.tsx`).
  const [addKey, setAddKey] = useState(0);
  const [editTarget, setEditTarget] = useState<PIROut | null>(null);
  const [viewTarget, setViewTarget] = useState<PIROut | null>(null);
  const [removeTarget, setRemoveTarget] = useState<PIROut | null>(null);
  const [exporting, setExporting] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ["intelligence", "pirs"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir");
      if (error) throw error;
      return data;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "pirs"] });
  }

  async function remove(id: number) {
    const { error } = await api.DELETE("/api/pir/{pir_id}", { params: { path: { pir_id: id } } });
    if (error) {
      toast.error("Error deleting PIR");
      return;
    }
    invalidate();
  }

  async function exportDocx(p: PIROut) {
    setExporting(p.id);
    try {
      const clientId = getActiveClientId();
      const resp = await fetch(`/api/proxy/api/pir/${p.id}/export/docx`, clientId ? { headers: { "X-Client-ID": clientId } } : undefined);
      if (resp.status === 501) {
        toast.error("python-docx not installed on server.");
        return;
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `PIR_${p.title.replace(/[^a-zA-Z0-9]/g, "_")}_${new Date().toISOString().slice(0, 10)}.docx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(`Export failed: ${(e as Error).message}`);
    } finally {
      setExporting(null);
    }
  }

  const pirs = query.data ?? [];
  const maxCov = Math.max(...pirs.map((p) => p.coverage_count), 1);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between border-b border-border pb-3">
        <p className="font-mono text-xs text-muted-foreground">{pirs.length} PIR{pirs.length !== 1 ? "s" : ""} defined</p>
        {can("manage_pir") && (
          <Button
            size="sm"
            onClick={() => {
              setAddKey((k) => k + 1);
              setFormOpen(true);
            }}
          >
            + New PIR
          </Button>
        )}
      </div>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Error loading PIRs.</p>}
      {query.data && pirs.length === 0 && (
        <p className="py-8 text-center text-xs text-muted-foreground">No PIRs defined. Click + New PIR to create one.</p>
      )}

      <div className="space-y-3">
        {pirs.map((p) => {
          const c = p.criteria;
          const tags = [
            ...c.threat_actors.map((x) => `TA:${x}`),
            ...c.industries.map((x) => `IND:${x}`),
            ...c.countries.map((x) => `CTY:${x}`),
            ...c.keywords.map((x) => `KW:${x}`),
            ...c.ttps.map((x) => `TTP:${x}`),
            ...c.news_types.map((x) => `TYPE:${x}`),
          ];
          const pct = Math.min(100, Math.round((p.coverage_count / maxCov) * 100));
          return (
            <div key={p.id} className="flex items-start gap-3 rounded-xl border border-border bg-background p-3">
              <Badge variant="outline" className={cn("shrink-0 font-mono text-xs", PRIORITY_CLASS[p.priority])}>
                {p.priority}
              </Badge>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-foreground">{p.title}</span>
                  {p.is_gap && (
                    <Badge
                      variant="destructive"
                      className="text-xs"
                      title="This PIR matched articles historically but has no matches in the last 14 days — active collection gap."
                    >
                      COVERAGE GAP
                    </Badge>
                  )}
                </div>
                {p.description && <p className="mt-0.5 text-xs text-muted-foreground">{p.description}</p>}
                {tags.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {tags.map((t, i) => (
                      <span key={i} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-xs text-muted-foreground">
                  {p.owner && <span>Owner: {p.owner}</span>}
                  {p.start_date && <span>From: {p.start_date}</span>}
                  {p.end_date && <span>Until: {p.end_date}</span>}
                  {p.last_match && <span>Last Hit: {p.last_match}</span>}
                  <span>14d: {p.recent_coverage}</span>
                  <span className={p.status === "active" ? "text-success" : ""}>{p.status.toUpperCase()}</span>
                </div>
              </div>
              <div className="w-24 shrink-0 text-center">
                <div className="font-mono text-lg font-bold text-foreground">{p.coverage_count.toLocaleString()}</div>
                <div className="text-sm font-medium text-muted-foreground">articles</div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                </div>
              </div>
              <div className="flex shrink-0 flex-col gap-1">
                {p.coverage_count > 0 && (
                  <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setViewTarget(p)}>
                    View {p.coverage_count.toLocaleString()}
                  </Button>
                )}
                {can("export_data") && (
                  <Button size="sm" variant="outline" className="h-6 px-2 text-xs" disabled={exporting === p.id} onClick={() => void exportDocx(p)}>
                    {exporting === p.id ? "…" : "Export"}
                  </Button>
                )}
                {can("manage_pir") && (
                  <>
                    <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setEditTarget(p)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="destructive" className="h-6 px-2 text-xs" onClick={() => setRemoveTarget(p)}>
                      Del
                    </Button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <PirFormDialog key={`add-${addKey}`} open={formOpen} onClose={() => setFormOpen(false)} onSaved={invalidate} />
      <PirFormDialog key={editTarget?.id ?? "edit-none"} pir={editTarget} open={editTarget !== null} onClose={() => setEditTarget(null)} onSaved={invalidate} />
      <PirArticlesDialog pir={viewTarget} onClose={() => setViewTarget(null)} />
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Delete PIR"
        description="Delete this PIR? This action cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => removeTarget && void remove(removeTarget.id)}
      />
    </div>
  );
}
