"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { errorDetail, invalidateEntity, normAlias } from "@/components/entities/entity-action-utils";
import { EntityAliasesDialog } from "@/components/entities/entity-aliases-dialog";
import { EntityEditDialog } from "@/components/entities/entity-edit-dialog";
import { EntityMergeDialog } from "@/components/entities/entity-merge-dialog";
import { EntitySplitDialog } from "@/components/entities/entity-split-dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type EntityDetail = components["schemas"]["EntityDetail"];

type Dialog =
  | { kind: "edit" | "aliases" | "merge" | "split" | "suppress" }
  | { kind: "undo"; aliasId: number; name: string };

/**
 * Menu Actions di header entity (spec 2b 6.8): edit, alias, merge, split, undo merge per tombstone, suppress.
 * Seluruh menu disembunyikan tanpa `manage_entities`.
 */
export function EntityActionsMenu({ entity }: { entity: EntityDetail }) {
  const can = useCan();
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<Dialog | null>(null);

  const suppress = useMutation({
    mutationFn: async () => {
      const { error } = await api.PATCH("/api/entities/{entity_id}", {
        params: { path: { entity_id: entity.id } },
        body: { suppressed: !entity.suppressed },
      });
      if (error) throw new Error(errorDetail(error, "Could not change the suppression."));
    },
    onSuccess: () => {
      toast.success(entity.suppressed ? "Entity unsuppressed." : "Entity suppressed.");
      invalidateEntity(qc, entity.id);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!can("manage_entities")) return null;

  // Alias nama-sendiri tombstone: sama dengan namanya (atau external_id, mis. teknik) setelah normalisasi.
  const ownAlias = (m: EntityDetail["merged_from"][number]) => {
    const wanted = new Set([normAlias(m.name), ...(m.external_id ? [normAlias(m.external_id)] : [])]);
    return entity.aliases.find((a) => wanted.has(normAlias(a.alias)));
  };
  const close = () => setDialog(null);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={<Button variant="secondary" aria-label="Entity actions" />}
        >
          Actions
          <ChevronDown aria-hidden />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-60">
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={() => setDialog({ kind: "edit" })}>
              Edit name and description
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setDialog({ kind: "aliases" })}>Manage aliases</DropdownMenuItem>
            <DropdownMenuItem onClick={() => setDialog({ kind: "split" })}>Split aliases</DropdownMenuItem>
            <DropdownMenuItem onClick={() => setDialog({ kind: "merge" })}>
              Merge into another entity…
            </DropdownMenuItem>
            {entity.merged_from.map((m) => {
              const own = ownAlias(m);
              return (
                <DropdownMenuItem
                  key={m.id}
                  onClick={() =>
                    setDialog(
                      own ? { kind: "undo", aliasId: own.id, name: m.name } : { kind: "split" },
                    )
                  }
                >
                  {`Undo merge of ${m.name}`}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem variant="destructive" onClick={() => setDialog({ kind: "suppress" })}>
              {entity.suppressed ? "Unsuppress" : "Suppress from feeds"}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      {dialog?.kind === "edit" && <EntityEditDialog entity={entity} onClose={close} />}
      {dialog?.kind === "aliases" && <EntityAliasesDialog entity={entity} onClose={close} />}
      {dialog?.kind === "merge" && <EntityMergeDialog entity={entity} onClose={close} />}
      {dialog?.kind === "split" && <EntitySplitDialog entity={entity} onClose={close} />}
      {dialog?.kind === "undo" && (
        <EntitySplitDialog
          entity={entity}
          onClose={close}
          required={{ aliasId: dialog.aliasId, name: dialog.name }}
        />
      )}
      <ConfirmDialog
        open={dialog?.kind === "suppress"}
        onOpenChange={(o) => !o && close()}
        title={entity.suppressed ? `Unsuppress ${entity.name}?` : `Suppress ${entity.name}?`}
        description={
          entity.suppressed
            ? "The entity will show up in lists and search again."
            : "The entity will be hidden from lists and search. You can unsuppress it later."
        }
        confirmLabel={entity.suppressed ? "Unsuppress" : "Suppress"}
        cancelVariant="ghost"
        onConfirm={() => suppress.mutate()}
      />
    </>
  );
}
