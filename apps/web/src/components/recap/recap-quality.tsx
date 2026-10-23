"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  RecapComparison,
  RecapEnvelope,
  RecapGrounding,
  RecapHitBucket,
  RecapHitRate,
  RecapScorecard,
  RecapScorecardEvent,
  RecapVerdict,
} from "@/lib/api/loose-types";
import { formatRange, sundayOf } from "@/lib/recap/period";
import {
  VERDICTS,
  VERDICT_LABEL,
  apiErrorMessage,
  dropReason,
  effectiveVerdict,
  signed,
} from "@/lib/recap/quality";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfidenceBadge, Chips, EmptyNote, Section } from "@/components/recap/recap-parts";

/**
 * Blok kualitas recap mingguan (#21, PR 4): perbandingan dengan pekan lalu, hasil cek grounding,
 * scorecard forecast pekan lalu (dengan override analis), dan hit rate 8 pekan. Datanya datang
 * dari `RecapDoc.quality` dan `hit_rate` di amplop balasan; recap lama dan pekan pertama tidak
 * membawanya, jadi `RecapView` hanya memasang blok yang datanya ada.
 */

const COUNT_LABEL: Record<string, string> = {
  articles: "Articles",
  tweets: "Tweets",
  iocs: "IOCs",
  cves: "CVEs",
  campaigns: "Campaigns",
  new_threat_actors: "New threat actors",
};

const NEW_THIS_WEEK: { key: "threat_actors" | "campaigns" | "cves"; label: string }[] = [
  { key: "threat_actors", label: "Threat actors" },
  { key: "campaigns", label: "Campaigns" },
  { key: "cves", label: "CVEs" },
];

/** Sel tabel yang lebih rapat dari default `ui/table` (halaman ini padat). Di bawah `sm` lebih
 * rapat lagi dan boleh membungkus: lebar HP (375px) tidak cukup buat lima kolom di ukuran biasa, dan
 * kolom selisih yang terpotong (harus digeser) menggagalkan tujuan tabelnya. */
const CELL = "px-1.5 py-1.5 text-xs whitespace-normal sm:px-2 sm:text-sm sm:whitespace-nowrap";
const HEAD = "h-8 px-1.5 text-2xs tracking-normal sm:px-2 sm:text-xs sm:tracking-wide";

function pct(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}%`;
}

export function ComparisonBlock({ comparison }: { comparison: RecapComparison }) {
  const rows = Object.entries(comparison.counts ?? {}).sort(
    ([a], [b]) => orderOf(a) - orderOf(b),
  );
  const noPct = rows.some(([, c]) => c.delta_pct === null);
  const fresh = comparison.new_this_week ?? {};
  const prev = comparison.previous;

  return (
    <Section title={`Week over Week · vs ${formatRange(prev.period_start, prev.period_end)}`}>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={HEAD}>Metric</TableHead>
            <TableHead className={cn(HEAD, "text-right")}>
              This<span className="hidden sm:inline"> week</span>
              <span className="sm:hidden"> wk</span>
            </TableHead>
            <TableHead className={cn(HEAD, "text-right")}>
              Last<span className="hidden sm:inline"> week</span>
              <span className="sm:hidden"> wk</span>
            </TableHead>
            <TableHead className={cn(HEAD, "text-right")}>Change</TableHead>
            <TableHead className={cn(HEAD, "text-right")}>%</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([key, c]) => (
            <TableRow key={key}>
              <TableCell className={CELL}>{COUNT_LABEL[key] ?? key}</TableCell>
              <TableCell className={cn(CELL, "text-right font-mono")}>{c.current}</TableCell>
              <TableCell className={cn(CELL, "text-right font-mono text-muted-foreground")}>
                {c.previous}
              </TableCell>
              <TableCell
                className={cn(
                  CELL,
                  "text-right font-mono",
                  c.delta === 0 && "text-muted-foreground",
                )}
              >
                {signed(c.delta)}
              </TableCell>
              <TableCell
                className={cn(
                  CELL,
                  "text-right font-mono",
                  (c.delta_pct ?? 0) === 0 && "text-muted-foreground",
                )}
              >
                {c.delta_pct === null ? "—" : pct(c.delta_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {noPct && (
        <p className="mt-1 text-xs text-muted-foreground">
          — = no percentage when last week&apos;s count was 0.
        </p>
      )}

      <div className="mt-3 mb-1.5 text-sm font-semibold text-muted-foreground">New this week</div>
      <div className="space-y-2">
        {NEW_THIS_WEEK.map(({ key, label }) => (
          <div key={key} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
            <Chips items={fresh[key]} />
          </div>
        ))}
      </div>
    </Section>
  );
}

function orderOf(key: string): number {
  const i = Object.keys(COUNT_LABEL).indexOf(key);
  return i === -1 ? Object.keys(COUNT_LABEL).length : i;
}

/**
 * Hasil cek grounding: apa yang dibuang dari keluaran model karena tidak ada di data masukannya.
 * Selalu satu baris yang terlihat (jumlahnya), rinciannya di `<details>`: tidak ada yang dibuang
 * diam-diam, tapi daftarnya tidak memenuhi halaman.
 */
export function GroundingBlock({ grounding }: { grounding: RecapGrounding }) {
  const dropped = grounding.dropped ?? [];
  if (!grounding.count && !dropped.length) {
    return (
      <p className="mt-3 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
        Grounding check: nothing was dropped. Every CVE, actor, campaign, source and story in this
        recap was found in the data given to the model.
      </p>
    );
  }
  const count = grounding.count || dropped.length;
  return (
    <details className="group mt-3 rounded-md border border-warning/40 bg-warning/[0.04] px-3 py-2">
      <summary className="cursor-pointer text-sm font-semibold text-warning">
        Grounding check: {count} {count === 1 ? "item" : "items"} dropped
        <span className="ml-2 text-xs font-normal text-muted-foreground group-open:hidden">
          show details
        </span>
      </summary>
      <p className="mt-2 text-xs text-muted-foreground">
        The model wrote these, but they are not in the data it was given, so they were removed from
        this recap instead of being shown.
      </p>
      <ul className="mt-2 space-y-1.5">
        {dropped.map((d, i) => (
          <li
            key={i}
            className="grid grid-cols-1 gap-x-3 gap-y-0.5 border-t border-border/60 pt-1.5 text-sm first:border-t-0 first:pt-0 sm:grid-cols-[10rem_1fr]"
          >
            <span className="font-mono text-xs text-muted-foreground">{d.field}</span>
            <span className="min-w-0">
              <span className="break-words">{d.value || "(empty)"}</span>
              <span className="ml-2 text-xs text-muted-foreground">· {dropReason(d.reason)}</span>
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

const VERDICT_TONE: Record<RecapVerdict, string> = {
  happened: "bg-success/10 text-success-text",
  partly: "bg-warning/10 text-warning-text",
  not_happened: "bg-destructive/10 text-destructive-text",
  unclear: "bg-muted text-muted-foreground",
};

/**
 * Override verdict: `PATCH /api/recap/{recap.id}/scorecard/{event.id}`. `recap.id` = recap yang
 * MEMUAT scorecard (pekan yang me-review), bukan pekan yang forecast-nya dinilai. Balasannya
 * `{recap, hit_rate}`: recap itu dan hit rate di SEMUA recap mingguan yang ada di cache diganti
 * (hit rate berlaku lintas pekan, jadi pekan lain yang sudah dibuka ikut basi kalau tidak).
 * Recap harian tidak punya hit rate dan dibiarkan.
 */
function useOverrideVerdict(recapId: number, eventId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (verdict: RecapVerdict) => {
      const { data, error, response } = await api.PATCH(
        "/api/recap/{recap_id}/scorecard/{event_id}",
        { params: { path: { recap_id: recapId, event_id: eventId } }, body: { verdict } },
      );
      if (!response.ok || !data) throw new Error(apiErrorMessage(error, response.status));
      return data as unknown as RecapEnvelope;
    },
    onSuccess: ({ recap, hit_rate }) => {
      if (!recap) return;
      queryClient.setQueriesData<RecapEnvelope>({ queryKey: ["recap", "doc"] }, (old) => {
        if (!old?.recap || old.recap.kind !== "weekly") return old;
        return { recap: old.recap.id === recap.id ? recap : old.recap, hit_rate };
      });
    },
  });
}

function ScorecardRow({ recapId, event }: { recapId: number; event: RecapScorecardEvent }) {
  const override = useOverrideVerdict(recapId, event.id);
  const verdict = effectiveVerdict(event);
  const at = event.override ? new Date(event.override.at) : null;

  return (
    <li className="rounded-md border border-border px-3 py-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 text-sm">
          <span className="font-medium">{event.event}</span> <ConfidenceBadge confidence={event.confidence} />
          <div className="mt-1 text-sm text-muted-foreground">
            <span className="font-mono text-xs uppercase">Evidence:</span>{" "}
            {event.evidence || "(none given)"}
          </div>
        </div>
        <Select
          items={VERDICT_LABEL}
          value={verdict}
          disabled={override.isPending}
          onValueChange={(v) => {
            if (v && v !== verdict) override.mutate(v as RecapVerdict);
          }}
        >
          <SelectTrigger
            size="sm"
            aria-label={`Verdict for: ${event.event}`}
            className={cn("w-36 shrink-0 font-mono text-xs", VERDICT_TONE[verdict])}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {VERDICTS.map((v) => (
              <SelectItem key={v} value={v} className="font-mono text-xs">
                {VERDICT_LABEL[v]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {event.override && (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Overridden by <span className="font-medium text-foreground">{event.override.by}</span>
          {at && !Number.isNaN(at.getTime()) ? ` · ${at.toLocaleString()}` : ""} · model said{" "}
          <span className="font-mono">{VERDICT_LABEL[event.verdict] ?? event.verdict}</span>
        </p>
      )}
      {override.isPending && <p className="mt-1.5 text-xs text-muted-foreground">Saving…</p>}
      {override.isError && (
        <p role="alert" className="mt-1.5 text-xs text-destructive">
          Could not save the verdict: {(override.error as Error).message}
        </p>
      )}
    </li>
  );
}

export function ScorecardBlock({
  recapId,
  scorecard,
}: {
  recapId: number;
  scorecard: RecapScorecard;
}) {
  const { reviewed } = scorecard;
  const events = scorecard.events ?? [];
  return (
    <Section
      title={`Forecast Scorecard · how the ${formatRange(reviewed.period_start, reviewed.period_end)} forecast held up`}
    >
      {events.length ? (
        <ul className="space-y-2">
          {events.map((e) => (
            <ScorecardRow key={e.id} recapId={recapId} event={e} />
          ))}
        </ul>
      ) : (
        <EmptyNote />
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">
        Verdicts are the model&apos;s; changing one records who did it and replaces the model&apos;s
        verdict in the hit rate. Confidence is what was stated when the forecast was made.
      </p>
    </Section>
  );
}

const BUCKETS: { key: "high" | "med" | "low"; label: string }[] = [
  { key: "high", label: "high" },
  { key: "med", label: "med" },
  { key: "low", label: "low" },
];

function RateCell({ bucket }: { bucket: RecapHitBucket }) {
  if (bucket.rate_pct === null) {
    return <span className="font-mono text-muted-foreground">n/a</span>;
  }
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span
        aria-hidden
        className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:block"
      >
        <span
          className="block h-full rounded-full bg-primary"
          style={{ width: `${Math.min(100, Math.max(0, bucket.rate_pct))}%` }}
        />
      </span>
      <span className="font-mono">{bucket.rate_pct}%</span>
    </span>
  );
}

/** Pecahan `hits` (partly = 0,5) tanpa nol berlebih: `3`, `3.5`. */
function hits(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function HitRateBlock({ hitRate }: { hitRate: RecapHitRate }) {
  const range =
    hitRate.first_week && hitRate.last_week
      ? ` (${formatRange(hitRate.first_week, sundayOf(hitRate.last_week))})`
      : "";
  return (
    <Section title="Forecast Hit Rate · does the stated confidence hold up?">
      <p className="mb-2 text-xs text-muted-foreground">
        Last {hitRate.weeks} weekly {hitRate.weeks === 1 ? "recap" : "recaps"}
        {range} · {hitRate.reviewed_weeks} with a reviewed forecast. Covers all of them, not only
        the week shown.
      </p>
      {hitRate.reviewed_weeks === 0 ? (
        <p className="text-xs text-muted-foreground italic">
          No forecast has been reviewed yet: the first scorecard appears with the next weekly recap
          that has a previous week.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className={HEAD}>Confidence</TableHead>
              <TableHead className={cn(HEAD, "text-right")}>Hits / judged</TableHead>
              <TableHead className={cn(HEAD, "text-right")}>Unclear</TableHead>
              <TableHead className={cn(HEAD, "text-right")}>Hit rate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {BUCKETS.map(({ key, label }) => {
              const b = hitRate.by_confidence[key];
              return (
                <TableRow key={key}>
                  <TableCell className={CELL}>
                    <ConfidenceBadge confidence={label} />
                  </TableCell>
                  <TableCell className={cn(CELL, "text-right font-mono")}>
                    {hits(b.hits)} / {b.judged}
                  </TableCell>
                  <TableCell className={cn(CELL, "text-right font-mono text-muted-foreground")}>
                    {b.unclear}
                  </TableCell>
                  <TableCell className={cn(CELL, "text-right")}>
                    <RateCell bucket={b} />
                  </TableCell>
                </TableRow>
              );
            })}
            <TableRow className="font-semibold">
              <TableCell className={CELL}>
                <Badge variant="outline" className="font-mono text-xs uppercase">
                  all
                </Badge>
              </TableCell>
              <TableCell className={cn(CELL, "text-right font-mono")}>
                {hits(hitRate.overall.hits)} / {hitRate.overall.judged}
              </TableCell>
              <TableCell className={cn(CELL, "text-right font-mono text-muted-foreground")}>
                {hitRate.overall.unclear}
              </TableCell>
              <TableCell className={cn(CELL, "text-right")}>
                <RateCell bucket={hitRate.overall} />
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">
        Hit rate = hits ÷ judged events. &ldquo;Partly&rdquo; counts as half a hit and
        &ldquo;unclear&rdquo; events are left out of the denominator. An analyst&apos;s verdict
        replaces the model&apos;s. n/a = nothing judged yet.
      </p>
    </Section>
  );
}
