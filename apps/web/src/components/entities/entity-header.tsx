"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { otherAliases } from "@/components/entities/entity-action-utils";
import { EntityActionsMenu } from "@/components/entities/entity-actions-menu";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { StarToggle } from "@/components/ui/star-toggle";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { entityTypeMeta } from "@/lib/entities/types";
import { fmtShortDate } from "@/lib/format";

type EntityDetail = components["schemas"]["EntityDetail"];

/**
 * Header halaman entity (spec 2b 6.8): menggantikan band burgundy `EntityHero`. Kicker "ENTITIES › TIPE · id"
 * (bagian "Entities" kembali ke tab daftar yang cocok dengan tipe entity ini), `<h1>` milik halaman ini karena
 * header Intelligence tidak dirender di rute detail, bintang watch, alias dengan disclosure "+N", sumber.
 */
export function EntityHeader({ entity, listTabKey }: { entity: EntityDetail; listTabKey: string }) {
  const can = useCan();
  const qc = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const meta = entityTypeMeta(entity.type, entity.identity_class);
  const aliases = otherAliases(
    entity.aliases.map((a) => a.alias),
    entity.name,
    entity.external_id,
  );
  const shown = showAll ? aliases : aliases.slice(0, 5);
  const hidden = aliases.length - shown.length;
  const sources = [...new Set([entity.source, ...entity.aliases.map((a) => a.source)])].filter(Boolean);
  const canWatch = can("manage_pir");

  const watch = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { entity_id: entity.id } } };
      const res = entity.watched
        ? await api.DELETE("/api/entities/{entity_id}/watch", path)
        : await api.PUT("/api/entities/{entity_id}/watch", path);
      if (res.error) throw new Error("watch failed");
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["entity", entity.id] });
      qc.invalidateQueries({ queryKey: ["entities"] });
    },
    onError: () => toast.error("Could not change the watch state."),
  });

  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-1.5 text-2xs font-semibold tracking-wide text-muted-foreground uppercase">
          <Link
            href={`/intelligence/entities?tab=${listTabKey}`}
            className="rounded-sm outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Entities
          </Link>
          <ChevronRight aria-hidden className="size-3" />
          <span>{meta.label}</span>
          {entity.external_id && (
            <>
              <span aria-hidden>·</span>
              <span className="font-code tracking-normal normal-case">{entity.external_id}</span>
            </>
          )}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold break-words">{entity.name}</h1>
          <StarToggle
            on={entity.watched}
            name={entity.name}
            disabled={watch.isPending}
            onToggle={canWatch ? () => watch.mutate() : undefined}
          />
          {entity.suppressed && (
            <Chip kind="flag" value="Suppressed">
              Suppressed
            </Chip>
          )}
        </div>
        {aliases.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            <span>Also known as</span>
            <ul aria-label="Aliases" className="flex flex-wrap items-center gap-1.5">
              {shown.map((a) => (
                <li key={a} className="rounded-full bg-surface px-2.5 py-0.5 text-foreground">
                  {a}
                </li>
              ))}
              {hidden > 0 && (
                <li>
                  <button
                    type="button"
                    onClick={() => setShowAll(true)}
                    aria-label={`Show ${hidden} more aliases`}
                    className="rounded-full border border-dashed border-border px-2.5 py-0.5 outline-none max-sm:min-h-11 hover:bg-surface focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    +{hidden}
                  </button>
                </li>
              )}
            </ul>
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Sources: {sources.length ? sources.join(", ") : "n/a"} · first seen {fmtShortDate(entity.first_seen, { withYear: true })}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {canWatch && (
          <Button
            variant="secondary"
            aria-pressed={entity.watched}
            disabled={watch.isPending}
            onClick={() => watch.mutate()}
          >
            {entity.watched ? "Watching" : "Watch"}
          </Button>
        )}
        <EntityActionsMenu entity={entity} />
      </div>
    </header>
  );
}
