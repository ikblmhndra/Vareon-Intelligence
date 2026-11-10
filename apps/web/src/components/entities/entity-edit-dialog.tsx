"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorDetail, invalidateEntity } from "@/components/entities/entity-action-utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** Dialog "Edit name and description" (`manage_entities`); dipasang hanya saat terbuka, jadi state selalu segar. */
export function EntityEditDialog({ entity, onClose }: { entity: EntityDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState(entity.name);
  const [description, setDescription] = useState(entity.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const { error: err } = await api.PATCH("/api/entities/{entity_id}", {
        params: { path: { entity_id: entity.id } },
        body: { name: name.trim(), description: description.trim() || null },
      });
      if (err) {
        setError(errorDetail(err, "Could not save the entity."));
        return;
      }
      toast.success("Entity updated.");
      invalidateEntity(qc, entity.id);
      onClose();
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
          <DialogTitle>Edit name and description</DialogTitle>
          <DialogDescription>Change the display name and description of this entity.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-edit-name" className="text-sm font-medium text-muted-foreground">
              Name
            </Label>
            <Input
              id="entity-edit-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="text-xs max-sm:h-11"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-edit-desc" className="text-sm font-medium text-muted-foreground">
              Description
            </Label>
            <Textarea
              id="entity-edit-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              className="text-xs"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive-text">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose} className="max-sm:h-11">
              Cancel
            </Button>
            <Button type="submit" loading={saving} className="max-sm:h-11">
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
