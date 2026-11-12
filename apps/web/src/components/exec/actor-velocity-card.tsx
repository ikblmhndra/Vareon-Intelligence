"use client";

import { useState } from "react";

import { EntityChip } from "@/components/entities/entity-chip";
import { ShowAll } from "@/components/exec/show-all";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { toTitleCase, velocityDisplay } from "@/lib/exec/format";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

const VEL_COLLAPSED = 7;
const VEL_MAX = 10;
const CO_COLLAPSED = 3;
const CO_MAX = 15;

/** Kartu "Actor velocity" + "Co-targeted sectors" (6.2, C15). Baris bukan elemen klik; tautan entity dan tombol
 * "Show all" bersaudara. `avg_prev` 0 = aktor baru → chip "NEW" menggantikan persen (persen dari nol tak
 * bermakna); merah hanya di atas +20 (`velocityDisplay`). */
export function ActorVelocityCard({ d, className }: { d: ExecDashboardV2; className?: string }) {
  const [velOpen, setVelOpen] = useState(false);
  const [coOpen, setCoOpen] = useState(false);
  const vel = d.ta_velocity.slice(0, velOpen ? VEL_MAX : VEL_COLLAPSED);
  const velTotal = Math.min(d.ta_velocity.length, VEL_MAX);
  const co = d.sector_cooccurrence.slice(0, coOpen ? CO_MAX : CO_COLLAPSED);
  const coTotal = Math.min(d.sector_cooccurrence.length, CO_MAX);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Actor velocity</CardTitle>
        <CardDescription>Last month vs the average of earlier months</CardDescription>
      </CardHeader>
      <CardContent>
        {d.ta_velocity.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">
            Not enough history yet — needs an earlier month with enough data
          </p>
        ) : (
          <>
            <ol className="divide-y divide-border">
              {vel.map((ta) => {
                const isNew = ta.avg_prev === 0;
                const v = velocityDisplay(ta.velocity_pct);
                return (
                  <li key={ta.actor} className="flex items-center gap-3 py-2">
                    <div className="min-w-0 flex-1">
                      <EntityChip type="intrusion-set" name={ta.actor} label={toTitleCase(ta.actor)} />
                    </div>
                    <span className="shrink-0 font-code text-2xs text-muted-foreground">
                      {ta.last_month} vs {ta.avg_prev} avg
                    </span>
                    <span className={cn("w-14 shrink-0 text-right font-code text-xs", !isNew && v.colorClass)}>
                      {isNew ? <Chip kind="status" value="ok">NEW</Chip> : v.text}
                    </span>
                  </li>
                );
              })}
            </ol>
            <div className="mt-2">
              <ShowAll total={velTotal} shown={VEL_COLLAPSED} expanded={velOpen} onToggle={() => setVelOpen((v) => !v)} />
            </div>
            <p className="mt-2 text-2xs text-muted-foreground">Red = more than 20% above its usual monthly pace.</p>
          </>
        )}

        <h3 className="mt-4 text-2xs font-medium tracking-wide text-muted-foreground uppercase">Co-targeted sectors</h3>
        {d.sector_cooccurrence.length === 0 ? (
          <p className="py-2 text-xs text-muted-foreground">No co-targeting data</p>
        ) : (
          <>
            <ul className="mt-1 divide-y divide-border">
              {co.map((c) => (
                <li key={`${c.sector_a}|${c.sector_b}`} className="flex items-center justify-between gap-3 py-2 text-xs">
                  <span className="min-w-0 truncate">
                    {toTitleCase(c.sector_a)} · {toTitleCase(c.sector_b)}
                  </span>
                  <span className="shrink-0 font-code text-2xs text-muted-foreground">{c.count} articles</span>
                </li>
              ))}
            </ul>
            <div className="mt-2">
              <ShowAll total={coTotal} shown={CO_COLLAPSED} expanded={coOpen} onToggle={() => setCoOpen((v) => !v)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
