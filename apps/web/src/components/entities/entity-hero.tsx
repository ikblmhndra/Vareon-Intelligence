"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityActionsMenu } from "@/components/entities/entity-actions-menu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { relativeTime } from "@/lib/cve/freshness";
import { entityTypeMeta } from "@/lib/entities/types";

type EntityDetail = components["schemas"]["EntityDetail"];

export interface EntityTotals {
  stories?: number;
  indicators?: number;
  cves?: number;
}

const fmtDate = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
    : "n/a";

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl bg-hero-panel px-3 py-2">
      <dt className="text-2xs text-hero-muted">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
    </div>
  );
}

/** Tombol di atas band burgundy: garis dan teks memakai token hero, bukan varian default. */
export const heroButtonClass =
  "border-hero-foreground/40 bg-transparent text-hero-foreground hover:bg-hero-panel hover:text-hero-foreground";

/**
 * Band header entity (mockup C): eyebrow tipe + id eksternal, nama (`<h2>`, `<h1>` milik layout),
 * alias dengan disclosure "+N", sumber, first seen, badge Suppressed, tombol Watch, lima KPI.
 */
export function EntityHero({ entity, totals }: { entity: EntityDetail; totals: EntityTotals }) {
  const can = useCan();
  const qc = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const meta = entityTypeMeta(entity.type, entity.identity_class);
  const aliases = entity.aliases.map((a) => a.alias);
  const shown = showAll ? aliases : aliases.slice(0, 5);
  const hidden = aliases.length - shown.length;
  const sources = [...new Set([entity.source, ...entity.aliases.map((a) => a.source)])].filter(Boolean);

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
    <section aria-label="Entity header" className="rounded-3xl bg-hero p-5 text-hero-foreground sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-xs font-medium tracking-wide text-hero-eyebrow uppercase">
            <meta.Icon aria-hidden className="size-3.5" />
            <span>
              {meta.label} · {entity.type}
            </span>
            {entity.external_id && (
              <span className="font-code tracking-normal normal-case">{entity.external_id}</span>
            )}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h2 className="text-2xl font-semibold break-words">{entity.name}</h2>
            {entity.suppressed && (
              <Badge variant="outline" className="border-hero-foreground/50 text-hero-foreground">
                Suppressed
              </Badge>
            )}
          </div>
          {aliases.length > 0 && (
            <ul aria-label="Aliases" className="mt-2 flex flex-wrap items-center gap-1.5">
              {shown.map((a) => (
                <li key={a} className="rounded-full bg-hero-panel px-2.5 py-0.5 text-xs">
                  {a}
                </li>
              ))}
              {hidden > 0 && (
                <li>
                  <button
                    type="button"
                    onClick={() => setShowAll(true)}
                    aria-label={`Show ${hidden} more aliases`}
                    className="rounded-full border border-dashed border-hero-foreground/40 px-2.5 py-0.5 text-xs outline-none hover:bg-hero-panel focus-visible:ring-3 focus-visible:ring-focus"
                  >
                    +{hidden} aliases
                  </button>
                </li>
              )}
            </ul>
          )}
          <p className="mt-2 text-xs text-hero-muted">
            Sources: {sources.length ? sources.join(", ") : "n/a"} · first seen{" "}
            {fmtDate(entity.first_seen)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {can("manage_pir") && (
            <Button
              variant="outline"
              className={heroButtonClass}
              aria-pressed={entity.watched}
              disabled={watch.isPending}
              onClick={() => watch.mutate()}
            >
              {entity.watched ? <Eye aria-hidden /> : <EyeOff aria-hidden />}
              {entity.watched ? "Watching" : "Watch"}
            </Button>
          )}
          <EntityActionsMenu entity={entity} />
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <Kpi label="Mentions, 30 days" value={entity.mentions_30d} />
        <Kpi label="Stories" value={totals.stories ?? "-"} />
        <Kpi label="Indicators" value={totals.indicators ?? "-"} />
        <Kpi label="CVEs" value={totals.cves ?? "-"} />
        <Kpi label="Last seen" value={entity.last_seen ? relativeTime(entity.last_seen) : "n/a"} />
      </dl>
    </section>
  );
}
