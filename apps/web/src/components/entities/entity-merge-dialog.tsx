"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { errorDetail, invalidateEntity } from "@/components/entities/entity-action-utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { StatePanel } from "@/components/ui/state-panel";

type EntityDetail = components["schemas"]["EntityDetail"];
type Target = { id: number; name: string };

/** Dialog "Merge into another": cari target bertipe sama, lihat pratinjau, lalu gabung. */
export function EntityMergeDialog({ entity, onClose }: { entity: EntityDetail; onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const term = q.trim();

  const results = useQuery({
    queryKey: ["entities", "merge-target", entity.type, term],
    enabled: target == null && term.length >= 2,
    queryFn: async () => {
      const { data, error: err } = await api.GET("/api/entities", {
        params: { query: { type: entity.type, q: term, limit: 8 } },
      });
      if (err || !data) throw new Error("search failed");
      return data.items;
    },
  });
  const items = (results.data ?? []).filter((e) => e.id !== entity.id);

  const preview = useQuery({
    queryKey: ["entity-merge-preview", entity.id, target?.id],
    enabled: target != null,
    queryFn: async () => {
      const { data, error: err } = await api.GET("/api/entities/{entity_id}/merge-preview", {
        params: { path: { entity_id: entity.id }, query: { into_id: target!.id } },
      });
      if (err || !data) throw new Error(errorDetail(err, "Could not load the merge preview."));
      return data;
    },
  });

  async function merge() {
    if (!target) return;
    setSaving(true);
    setError(null);
    try {
      const { error: err } = await api.POST("/api/entities/{entity_id}/merge", {
        params: { path: { entity_id: entity.id } },
        body: { into_id: target.id },
      });
      if (err) {
        setError(errorDetail(err, "Could not merge the entity."));
        return;
      }
      toast.success(`"${entity.name}" merged into "${target.name}".`);
      invalidateEntity(qc, entity.id, target.id);
      onClose();
      router.push(`/intelligence/entities/${target.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const p = preview.data;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Merge {entity.name} into another</DialogTitle>
          <DialogDescription>Merge this entity into another entity of the same type. Review the preview before confirming.</DialogDescription>
        </DialogHeader>
        {target == null ? (
          <div className="space-y-2">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name or alias"
              aria-label="Search target entity"
              className="text-xs max-sm:h-11"
            />
            {term.length >= 2 && results.isError && (
              <p role="alert" className="text-xs text-destructive-text">
                Could not search entities.
              </p>
            )}
            {term.length >= 2 && results.isSuccess && items.length === 0 && (
              <p className="text-xs text-muted-foreground">No entity of the same type matches.</p>
            )}
            {items.length > 0 && (
              <ul className="max-h-48 space-y-1 overflow-y-auto" aria-label="Matching entities">
                {items.map((e) => (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={() => setTarget({ id: e.id, name: e.name })}
                      className="flex min-h-9 w-full items-center rounded-lg px-2 text-left text-xs outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-focus max-sm:min-h-11"
                    >
                      <span className="min-w-0 truncate">{e.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>
                Target: <strong>{target.name}</strong>
              </span>
              <Button type="button" variant="ghost" size="sm" onClick={() => setTarget(null)} className="max-sm:h-11">
                Change
              </Button>
            </div>
            {preview.isPending && <StatePanel variant="loading" title="Loading merge preview" className="py-6" />}
            {preview.isError && (
              <p role="alert" className="text-sm text-destructive-text">
                {(preview.error as Error).message}
              </p>
            )}
            {p && (
              <dl className="grid grid-cols-2 gap-2 text-xs">
                {(
                  [
                    ["Aliases moved", p.moved_aliases],
                    ["Mentions moved", p.moved_mentions],
                    ["Relationships moved", p.moved_relationships],
                    ["Watches moved", p.moved_watches],
                    ["Profile moved", p.moved_profile ? "yes" : "no"],
                  ] as const
                ).map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-muted px-3 py-2">
                    <dt className="text-2xs text-muted-foreground">{label}</dt>
                    <dd className="text-sm font-semibold">{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onClose} className="max-sm:h-11">
            Cancel
          </Button>
          <Button
            type="button"
            loading={saving}
            disabled={target == null || !p}
            onClick={() => void merge()}
            className="max-sm:h-11"
          >
            {saving ? "Merging…" : target ? `Merge into ${target.name}` : "Merge"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
