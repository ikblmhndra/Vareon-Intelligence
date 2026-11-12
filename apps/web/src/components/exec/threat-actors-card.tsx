"use client";

import { useState } from "react";
import Link from "next/link";

import { EntityChip } from "@/components/entities/entity-chip";
import { ShowAll } from "@/components/exec/show-all";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { newsroomHref } from "@/lib/newsroom/links";
import { toTitleCase, velocityDisplay } from "@/lib/exec/format";
import { cn } from "@/lib/utils";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

const COLLAPSED = 5;
const FOCUS =
  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

/** Kartu "Threat actors" (6.1). Baris BUKAN elemen klik: nama (tautan entity), hitungan (tautan Newsroom) dan
 * tombol "Show all" bersaudara, jadi tidak ada elemen interaktif bersarang. `from` = awal jendela dashboard,
 * supaya jumlah di sheet Newsroom sama dengan angka di sini (D12). */
export function ThreatActorsCard({ d, from, className }: { d: ExecDashboardV2; from: string; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const rows = d.ta_leaderboard.slice(0, expanded ? 10 : COLLAPSED);
  const total = Math.min(d.ta_leaderboard.length, 10);
  const prevSet = new Set(d.prev_ta_names.map((n) => n.toLowerCase()));
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Threat actors</CardTitle>
        <CardDescription>By article count; velocity = last month vs prior average</CardDescription>
        <CardAction>
          <Link
            href="/intelligence/entities?tab=actors"
            className={cn("rounded-md text-xs font-medium text-primary-text outline-none hover:underline", FOCUS)}
          >
            All →
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent>
        {d.ta_leaderboard.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No threat actors named in this period</p>
        ) : (
          <>
            <ol className="divide-y divide-border">
              {rows.map((ta, i) => {
                // NEW hanya bermakna bila periode sebelumnya cukup data; kalau tidak, semua aktor "NEW" = noise.
                const isNew = d.prev_period_reliable && !prevSet.has(ta.name.toLowerCase());
                const conf = d.ta_confidence[ta.name] ?? d.ta_confidence[ta.name.toLowerCase()] ?? null;
                const vel = velocityDisplay(ta.velocity_pct);
                const name = toTitleCase(ta.name);
                return (
                  <li
                    key={ta.name}
                    className="flex items-center gap-3 py-2"
                    title={conf !== null ? `Signal quality ${conf}%` : undefined}
                  >
                    <span className="w-6 shrink-0 font-code text-xs text-muted-foreground">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <EntityChip type="intrusion-set" name={ta.name} label={name} />
                        {isNew && <Chip kind="status" value="ok">NEW</Chip>}
                      </div>
                      {ta.top_sectors.length > 0 && (
                        <p className="mt-0.5 truncate text-2xs text-muted-foreground">
                          most seen in {ta.top_sectors.map(toTitleCase).join(" · ")}
                        </p>
                      )}
                    </div>
                    <Link
                      href={newsroomHref({ actor: ta.name, from })}
                      aria-label={`${ta.count} articles about ${name} in Newsroom`}
                      className={cn("shrink-0 rounded-md font-heading text-lg font-semibold outline-none hover:underline", FOCUS)}
                    >
                      {ta.count}
                    </Link>
                    <span className={cn("w-12 shrink-0 text-right font-code text-xs", vel.colorClass)}>{vel.text}</span>
                  </li>
                );
              })}
            </ol>
            <div className="mt-2">
              <ShowAll total={total} shown={COLLAPSED} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
