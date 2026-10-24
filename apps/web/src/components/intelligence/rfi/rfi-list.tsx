"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";
import { RfiFormDialog } from "@/components/intelligence/rfi/rfi-form-dialog";
import { useCan } from "@/lib/auth/permissions";

type RFIOut = components["schemas"]["RFIOut"];

const FILTERS = [
  { key: "", label: "All" },
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In Progress" },
  { key: "closed", label: "Closed" },
] as const;

const STATUS_CLASS: Record<string, string> = {
  open: "text-warning border-warning/40",
  in_progress: "text-primary border-primary/40",
  closed: "text-muted-foreground border-border",
};
const STATUS_LABEL: Record<string, string> = { open: "OPEN", in_progress: "IN PROGRESS", closed: "CLOSED" };

/** Port kartu RFI + CRUD + filter status (`pir.js:289-453`,
 * `loadRfis`/`rfiSetFilter`/`openRfiModal`/`deleteRfi`). */
export function RfiList() {
  const can = useCan();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  // Naik tiap "+ New" -- form add remount fresh, gak bawa isian
  // submit/cancel sebelumnya (pola sama `addKey` di `sr-table.tsx`).
  const [addKey, setAddKey] = useState(0);
  const [editTarget, setEditTarget] = useState<RFIOut | null>(null);
  const [removeTarget, setRemoveTarget] = useState<RFIOut | null>(null);

  const query = useQuery({
    queryKey: ["intelligence", "rfis", filter],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/rfi", {
        params: { query: { status: filter || undefined, page_size: 100 } },
      });
      if (error) throw error;
      return data;
    },
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "rfis"] });
  }

  async function remove(id: number) {
    const { error } = await api.DELETE("/api/rfi/{rfi_id}", { params: { path: { rfi_id: id } } });
    if (error) {
      toast.error("Error deleting RFI");
      return;
    }
    invalidate();
  }

  const rfis = query.data?.rfis ?? [];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex gap-1.5">
          {FILTERS.map((f) => (
            <Button
              key={f.key}
              size="sm"
              variant={filter === f.key ? "default" : "outline"}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        {can("manage_rfi") && (
          <Button
            size="sm"
            onClick={() => {
              setAddKey((k) => k + 1);
              setFormOpen(true);
            }}
          >
            + New RFI
          </Button>
        )}
      </div>

      <p className="mb-2 font-mono text-xs text-muted-foreground">{query.data?.total ?? 0} RFIs</p>

      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Error loading RFIs.</p>}
      {query.data && rfis.length === 0 && (
        <p className="py-8 text-center text-xs text-muted-foreground">No RFIs found. Click + New RFI to create one.</p>
      )}

      <div className="space-y-3">
        {rfis.map((r) => (
          <div key={r.id} className="flex items-start gap-3 rounded-xl border border-border bg-background p-3">
            <Badge variant="outline" className={cn("w-24 shrink-0 justify-center font-mono text-xs", STATUS_CLASS[r.status])}>
              {STATUS_LABEL[r.status] ?? r.status.toUpperCase()}
            </Badge>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-foreground">{r.question}</div>
              {r.response && (
                <p className="mt-1 text-xs text-muted-foreground italic">
                  {r.response.slice(0, 120)}
                  {r.response.length > 120 ? "…" : ""}
                </p>
              )}
              <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-xs text-muted-foreground">
                <span>From: {r.requester}</span>
                {r.due_date && <span>Due: {r.due_date}</span>}
                {r.created_at && <span>Created: {r.created_at.slice(0, 10)}</span>}
                {r.linked_pir != null && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">PIR #{r.linked_pir}</span>
                )}
              </div>
            </div>
            {can("manage_rfi") && (
              <div className="flex shrink-0 flex-col gap-1">
                <Button size="sm" variant="outline" className="h-6 px-2 text-xs" onClick={() => setEditTarget(r)}>
                  Edit
                </Button>
                <Button size="sm" variant="destructive" className="h-6 px-2 text-xs" onClick={() => setRemoveTarget(r)}>
                  Del
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>

      <RfiFormDialog key={`add-${addKey}`} open={formOpen} onClose={() => setFormOpen(false)} onSaved={invalidate} />
      <RfiFormDialog
        key={editTarget?.id ?? "edit-none"}
        rfi={editTarget}
        open={editTarget !== null}
        onClose={() => setEditTarget(null)}
        onSaved={invalidate}
      />
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title="Delete RFI"
        description="Delete this RFI? This action cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => removeTarget && void remove(removeTarget.id)}
      />
    </div>
  );
}
