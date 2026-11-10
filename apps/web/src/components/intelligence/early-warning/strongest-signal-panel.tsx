"use client";

import Link from "next/link";

import { BarSeries } from "@/components/ui/bar-series";
import { Chip } from "@/components/ui/chip";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import type { SpikesResponse } from "@/lib/api/loose-types";
import { fmtShortDate } from "@/lib/format";
import { newsroomHref } from "@/lib/newsroom/links";

import { CATEGORY_META, dailySeries, spikeName, type CategorizedSpike } from "./model";

/** Panel "Strongest signal" untuk spike terpilih. Tautan Newsroom memakai `from` = awal jendela spike backend
 * (tanggal sumbu server), supaya sheet Newsroom terbatas tanggal dan jumlahnya cocok dengan angka di sini. */
export function StrongestSignalPanel({ spike, data }: { spike: CategorizedSpike; data: SpikesResponse }) {
  const series = dailySeries(data, spike);
  const dates = data.daily.dates;
  const name = spikeName(spike);
  const high = spike.severity === "high";
  const cat = CATEGORY_META[spike.category];

  // Jendela recent = 8 hari terakhir sumbu (today-7..today, `date >= recent_cutoff` di backend); dihitung dari
  // indeks sumbu server, bukan jam browser, supaya batas tak bergeser di zona waktu lain.
  const recentFrom = dates.length - 8;

  // `period: 7` di Newsroom = 7 hari dari jam browser, sedangkan jendela spike 8 tanggal sumbu server; `from` dari
  // sumbu yang sama menyamakan keduanya. Sumbu terlalu pendek (tak semestinya terjadi): mundur ke `period: 7`.
  const from = dates[recentFrom];
  const range = from ? { from } : { period: 7 as const };
  const newsroom = newsroomHref(
    spike.category === "actor"
      ? { actor: spike.entity, ...range }
      : spike.category === "industry"
        ? { industry: spike.entity, ...range }
        : spike.category === "country"
          ? { country: spike.entity, ...range }
          : range,
  );

  return (
    <HeroPanel
      kicker="Strongest signal"
      title={name}
      footer={
        <>
          <Link href={newsroom} className={heroLinkClass}>
            Open in Newsroom
          </Link>
          {spike.entity_id != null && (
            <Link href={`/intelligence/entities/${spike.entity_id}`} className={heroLinkClass}>
              Entity page
            </Link>
          )}
        </>
      }
    >
      <p>
        {cat.noun} · spike on {fmtShortDate(spike.date)}
      </p>
      <div className="mt-2 flex items-center gap-3">
        <span className="font-heading text-5xl leading-none font-bold text-hero-foreground">{spike.z_score}σ</span>
        <Chip kind="severity" value={high ? "high" : "medium"}>
          {high ? "HIGH" : "MEDIUM"}
        </Chip>
      </div>
      <p className="mt-2">
        {spike.count} articles vs {spike.baseline_mean}/day
      </p>
      {series && (
        <div className="mt-3">
          {/* Kartu terang di dalam panel: warna kanvas Chart.js mengikuti tema, bukan token hero, jadi di atas
              burgundy teks sumbu dan batang netral tak terjamin kontrasnya. */}
          <div className="rounded-md bg-background p-2 text-foreground">
          <BarSeries
            labels={dates.map((d) => fmtShortDate(d))}
            values={series}
            highlight={(i) => i >= recentFrom}
            highlightTone="destructive"
            tone="neutral"
            referenceLine={spike.baseline_mean}
            height={150}
            aria-label={`Daily articles for ${name}, last ${data.parameters.lookback_days} days`}
            formatValue={(v) => `${v} articles`}
          />
          </div>
          <p className="mt-2 text-2xs">Daily articles, last {data.parameters.lookback_days} days</p>
        </div>
      )}
    </HeroPanel>
  );
}
