"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { errorDetail, invalidateEntity } from "@/components/entities/entity-action-utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

interface Props {
  entity: EntityDetail;
  onClose: () => void;
  /** Alias yang wajib ikut (nama sendiri entity yang dihidupkan lagi) dan nama entity itu. */
  required?: { aliasId: number; name: string } | null;
}

/**
 * Dialog "Split aliases": pilih alias yang dipindah ke entity baru atau yang dihidupkan lagi.
 * `required` (dari "Undo merge of X") sudah tercentang dan diberi label.
 */
export function EntitySplitDialog({ entity, onClose, required = null }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const [picked, setPicked] = useState<Set<number>>(() => new Set(required ? [required.aliasId] : []));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(id: number, on: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function split() {
    setSaving(true);
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/entities/{entity_id}/split", {
        params: { path: { entity_id: entity.id } },
        body: { alias_ids: [...picked] },
      });
      if (err || !data) {
        setError(errorDetail(err, "Could not split the aliases."));
        return;
      }
      toast.success(`Aliases moved to "${data.name}".`);
      invalidateEntity(qc, entity.id, data.id);
      onClose();
      router.push(`/intelligence/entities/${data.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{required ? `Undo merge of ${required.name}` : "Split aliases"}</DialogTitle>
          <DialogDescription>Move the selected aliases into a new entity.</DialogDescription>
        </DialogHeader>
        {entity.aliases.length === 0 ? (
          <p className="text-sm text-muted-foreground">This entity has no aliases to split.</p>
        ) : (
          <ul aria-label="Aliases to move" className="space-y-1">
            {entity.aliases.map((a) => {
              const id = `entity-split-${a.id}`;
              const isRequired = required?.aliasId === a.id;
              return (
                <li key={a.id} className="flex items-center gap-3 rounded-lg bg-muted px-3 py-2 text-xs">
                  <Checkbox
                    id={id}
                    checked={picked.has(a.id)}
                    onCheckedChange={(v) => toggle(a.id, v === true)}
                    aria-label={`Move alias ${a.alias}`}
                  />
                  <label htmlFor={id} className="min-w-0 flex-1 break-words">
                    {a.alias}
                    {isRequired && (
                      <span className="block text-2xs text-primary-text">
                        Required to bring back {required.name}
                      </span>
                    )}
                  </label>
                  <span className="shrink-0 text-2xs text-muted-foreground">{a.source}</span>
                </li>
              );
            })}
          </ul>
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
            disabled={picked.size === 0}
            onClick={() => void split()}
            className="max-sm:h-11"
          >
            {saving ? "Splitting…" : required ? `Bring back ${required.name}` : "Split selected aliases"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
