"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  RecapComparison,
  RecapEnvelope,
  RecapHitBucket,
  RecapHitRate,
  RecapScorecard,
  RecapScorecardEvent,
  RecapVerdict,
} from "@/lib/api/loose-types";
import { formatRange } from "@/lib/recap/period";
import {
  VERDICTS,
  VERDICT_LABEL,
  apiErrorMessage,
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
import { ConfidenceBadge, Chips, EmptyNote } from "@/components/recap/recap-parts";

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

const NEW_THIS_WEEK: {
  key: "threat_actors" | "campaigns" | "cves";
  label: string;
  entity?: "intrusion-set" | "vulnerability";
}[] = [
  { key: "threat_actors", label: "Threat actors", entity: "intrusion-set" },
  { key: "campaigns", label: "Campaigns" },
  { key: "cves", label: "CVEs", entity: "vulnerability" },
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
    <div>
      <p className="mb-2 text-xs text-muted-foreground">
        Compared with {formatRange(prev.period_start, prev.period_end)}
      </p>
      <Table className="table-fixed">
        <colgroup>
          <col className="w-[36%]" />
          <col className="w-[16%]" />
          <col className="w-[16%]" />
          <col className="w-[16%]" />
          <col className="w-[16%]" />
        </colgroup>
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
        {NEW_THIS_WEEK.map(({ key, label, entity }) => (
          <div key={key} className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
            <Chips items={fresh[key]} entity={entity} />
          </div>
        ))}
      </div>
    </div>
  );
}

function orderOf(key: string): number {
  const i = Object.keys(COUNT_LABEL).indexOf(key);
  return i === -1 ? Object.keys(COUNT_LABEL).length : i;
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
  const events = scorecard.events ?? [];
  return (
    <div>
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
    </div>
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
          className="block h-full rounded-full bg-primary-text"
          style={{ width: `${Math.min(100, Math.max(0, bucket.rate_pct))}%` }}
        />
      </span>
      <span className="font-code text-primary-text">{bucket.rate_pct}%</span>
    </span>
  );
}

/** Pecahan `hits` (partly = 0,5) tanpa nol berlebih: `3`, `3.5`. */
function hits(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

export function HitRateBlock({ hitRate }: { hitRate: RecapHitRate }) {
  if (hitRate.reviewed_weeks === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">
        No forecast has been reviewed yet: the first scorecard appears with the next weekly recap
        that has a previous week.
      </p>
    );
  }
  return (
    <div>
      <Table className="table-fixed">
        <colgroup>
          <col className="w-[28%]" />
          <col className="w-[26%]" />
          <col className="w-[28%]" />
          <col className="w-[18%]" />
        </colgroup>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={HEAD}>Confidence</TableHead>
            <TableHead className={cn(HEAD, "text-right")}>Hits / judged</TableHead>
            <TableHead className={cn(HEAD, "text-right")}>Hit rate</TableHead>
            <TableHead className={cn(HEAD, "text-right")}>Unclear</TableHead>
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
                <TableCell className={cn(CELL, "text-right font-code")}>
                  {hits(b.hits)} / {b.judged}
                </TableCell>
                <TableCell className={cn(CELL, "text-right")}>
                  <RateCell bucket={b} />
                </TableCell>
                <TableCell className={cn(CELL, "text-right font-code text-muted-foreground")}>
                  {b.unclear}
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
            <TableCell className={cn(CELL, "text-right font-code")}>
              {hits(hitRate.overall.hits)} / {hitRate.overall.judged}
            </TableCell>
            <TableCell className={cn(CELL, "text-right")}>
              <RateCell bucket={hitRate.overall} />
            </TableCell>
            <TableCell className={cn(CELL, "text-right font-code text-muted-foreground")}>
              {hitRate.overall.unclear}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <p className="mt-2 text-2xs text-muted-foreground">
        {hitRate.reviewed_weeks} {hitRate.reviewed_weeks === 1 ? "week" : "weeks"} reviewed. Hit
        rate = hits ÷ judged events. &ldquo;Partly&rdquo; counts as half a hit and
        &ldquo;unclear&rdquo; events are left out of the denominator. An analyst&apos;s verdict
        replaces the model&apos;s. n/a = nothing judged yet.
      </p>
    </div>
  );
}
