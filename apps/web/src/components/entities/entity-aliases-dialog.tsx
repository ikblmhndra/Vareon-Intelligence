"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorDetail, invalidateEntity } from "@/components/entities/entity-action-utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** Dialog "Manage aliases": tambah (409 kalau alias milik entity lain) dan hapus alias. */
export function EntityAliasesDialog({ entity, onClose }: { entity: EntityDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [alias, setAlias] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function add() {
    const value = alias.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await api.POST("/api/entities/{entity_id}/aliases", {
        params: { path: { entity_id: entity.id } },
        body: { alias: value },
      });
      if (err) {
        setError(errorDetail(err, "Could not add the alias."));
        return;
      }
      setAlias("");
      toast.success(`Alias "${value}" added.`);
      invalidateEntity(qc, entity.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(aliasId: number, text: string) {
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await api.DELETE("/api/entities/{entity_id}/aliases/{alias_id}", {
        params: { path: { entity_id: entity.id, alias_id: aliasId } },
      });
      if (err) {
        setError(errorDetail(err, "Could not remove the alias."));
        return;
      }
      toast.success(`Alias "${text}" removed.`);
      invalidateEntity(qc, entity.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Manage aliases</DialogTitle>
        </DialogHeader>
        {entity.aliases.length === 0 ? (
          <p className="text-sm text-muted-foreground">No aliases yet.</p>
        ) : (
          <ul aria-label="Aliases" className="space-y-1">
            {entity.aliases.map((a) => (
              <li key={a.id} className="flex items-center gap-2 rounded-lg bg-muted px-3 py-1.5 text-xs">
                <span className="min-w-0 flex-1 break-words">{a.alias}</span>
                <span className="shrink-0 text-2xs text-muted-foreground">{a.source}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={busy}
                  aria-label={`Remove alias ${a.alias}`}
                  onClick={() => void remove(a.id, a.alias)}
                  className="size-7 max-sm:size-11"
                >
                  <X aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex flex-col gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            void add();
          }}
        >
          <Label htmlFor="entity-alias-new" className="text-sm font-medium text-muted-foreground">
            New alias
          </Label>
          <div className="flex gap-2">
            <Input
              id="entity-alias-new"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              className="text-xs max-sm:h-11"
            />
            <Button type="submit" disabled={busy || !alias.trim()} className="max-sm:h-11">
              Add
            </Button>
          </div>
        </form>
        {error && (
          <p role="alert" className="text-sm text-destructive-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose} className="max-sm:h-11">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
