import Link from "next/link";

import { Chip } from "@/components/ui/chip";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import { MeterBar } from "@/components/ui/meter-bar";
import { entityHref } from "@/lib/entities/types";
import { toTitleCase } from "@/lib/exec/format";
import { fmtShortDate } from "@/lib/format";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";

type Spike = ExecDashboardV2["industry_spikes"][number];

// Chip biasa di atas burgundy tak terbaca di tema terang: pakai token hero (perbaikan 2b).
const HERO_CHIP = "bg-hero-foreground/15 text-hero-foreground";

/** Satu baris per sektor: `industry_spikes` bisa memuat satu sektor di beberapa hari, jadi yang z-nya tertinggi
 * dipertahankan (beserta tanggalnya, R7) dan urutan akhir menurun menurut z. */
function onePerSector(spikes: Spike[]): Spike[] {
  const best = new Map<string, Spike>();
  for (const s of spikes) {
    const cur = best.get(s.entity);
    if (!cur || s.z_score > cur.z_score) best.set(s.entity, s);
  }
  return [...best.values()].sort((a, b) => b.z_score - a.z_score);
}

/** Panel burgundy "Sector spikes" (6.1, C8): jendela spike backend = 7 hari terakhir terhadap baseline, bukan
 * periode filter, makanya subjudulnya menyebut "last 7 days". */
export function SectorSpikesHero({ d }: { d: ExecDashboardV2 }) {
  const rows = onePerSector(d.industry_spikes);
  const maxCount = Math.max(1, ...rows.map((r) => r.count));
  return (
    <HeroPanel
      kicker={
        <span className="inline-flex items-center gap-2">
          Sector spikes
          <Chip kind="flag" value={String(rows.length)} className={HERO_CHIP} />
        </span>
      }
      title="Sectors whose daily reporting is above baseline (z ≥ 1.5), last 7 days"
      footer={
        <Link href="/intelligence/early-warning" className={heroLinkClass}>
          Open Early warning →
        </Link>
      }
    >
      {rows.length === 0 ? (
        <p>No sector above baseline in the last 7 days</p>
      ) : (
        <>
          <ul className="space-y-3">
            {rows.map((r) => {
              const name = toTitleCase(r.entity);
              return (
                <li key={r.entity}>
                  <div className="flex items-center gap-2">
                    <Link
                      href={entityHref({ type: "identity", name: r.entity })}
                      className={`${heroLinkClass} min-w-0 truncate text-sm font-semibold`}
                      title={name}
                    >
                      {name}
                    </Link>
                    <Chip kind="severity" value={r.severity} className={HERO_CHIP}>
                      {r.severity === "high" ? "HIGH" : "MEDIUM"}
                    </Chip>
                    <span className="ml-auto shrink-0 font-code text-xs text-hero-foreground">z {r.z_score}</span>
                  </div>
                  <MeterBar
                    onHero
                    variant="baseline"
                    value={r.count}
                    max={maxCount}
                    baseline={r.baseline_mean}
                    aria-label={`${name}: ${r.count} articles on the spike day, baseline ${r.baseline_mean}`}
                    className="mt-1.5"
                  />
                  <p className="mt-1 text-xs">
                    {r.count} vs {r.baseline_mean} avg · {fmtShortDate(r.date)}
                  </p>
                </li>
              );
            })}
          </ul>
          <p className="mt-3 text-2xs">Bar = articles on the spike day; white tick = baseline mean.</p>
        </>
      )}
    </HeroPanel>
  );
}
