"use client";

import { useState } from "react";

import { EntityChip } from "@/components/entities/entity-chip";
import { ShowAll } from "@/components/exec/show-all";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MeterBar } from "@/components/ui/meter-bar";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

const COLLAPSED = 6;

/** Kartu "Top techniques" (6.1). `top_ttps` di-group `(id, name)` oleh repo, jadi id yang sama bisa muncul dua
 * kali dengan nama beda (varian enrichment): key menggabung id + nama + indeks. Nama teknik tampil sebagai teks
 * di samping chip id, bukan di dalamnya, supaya id (font-code) tetap rapi dan nama bisa terpotong. */
export function TopTechniquesCard({ d, days, className }: { d: ExecDashboardV2; days: number; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const all = d.top_ttps.slice(0, 15);
  const rows = expanded ? all : all.slice(0, COLLAPSED);
  const max = Math.max(1, ...all.map((t) => t.count));
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Top techniques</CardTitle>
        <CardDescription>ATT&amp;CK techniques by article count, {days} d</CardDescription>
      </CardHeader>
      <CardContent>
        {all.length === 0 ? (
          <p className="py-4 text-xs text-muted-foreground">No TTP data for this period</p>
        ) : (
          <>
            <ul className="space-y-2">
              {rows.map((t, i) => (
                <li key={`${t.id}::${t.name}::${i}`}>
                  <div className="flex items-center gap-2">
                    <EntityChip type="attack-pattern" name={t.id} className="shrink-0" />
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={t.name}>
                      {t.name}
                    </span>
                    <span className="shrink-0 font-code text-xs">{t.count}</span>
                  </div>
                  <MeterBar value={t.count} max={max} aria-label={`${t.id} ${t.name}: ${t.count} articles`} className="mt-1" />
                </li>
              ))}
            </ul>
            <div className="mt-3">
              <ShowAll total={all.length} shown={COLLAPSED} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
