"use client";

import type { ReactNode } from "react";

import {
  useCveExposure,
  useDashboardAttention,
  useDashboardRansomware,
  useDashboardStats,
} from "@/components/dashboard/use-dashboard-overview";
import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { type PeriodKey, periodInfo } from "@/lib/dashboard/period";
import { cn } from "@/lib/utils";

const n = (v: number) => v.toLocaleString("en-US");

/** Delta baris 1-2 (spec 6.4). Periode sebelumnya 0 tidak pernah jadi pembagi: jatuh ke "no prior-period data",
 * jadi tidak ada "Infinity"/"NaN". */
function deltaLine(cur: number, prev: number | null, reliable: boolean, allTime: boolean): ReactNode {
  if (allTime) return "all time";
  if (!reliable || prev == null || prev <= 0) return "no prior-period data";
  if (cur === prev) return "no change vs previous period";
  const up = cur > prev;
  return (
    <>
      <span aria-hidden="true">{up ? "▲" : "▼"}</span>
      <span className="sr-only">{up ? "up" : "down"}</span> {Math.round((Math.abs(cur - prev) * 100) / prev)}% vs
      previous period
    </>
  );
}

interface RowState {
  pending: boolean;
  error: boolean;
  stale: boolean;
  retry: () => void;
}

function Row({
  state,
  value,
  label,
  second,
  graphic,
}: {
  state: RowState;
  value: number | undefined;
  label: string;
  second: ReactNode;
  graphic?: ReactNode;
}) {
  const failed = state.error;
  return (
    <div className={cn("flex items-center justify-between gap-4 py-3", state.stale && "opacity-60")}>
      <div className="flex min-w-0 flex-col">
        {/* order-*: dl menuntut dt sebelum dd di DOM, tapi angka dibaca lebih dulu secara visual. */}
        <dd className="order-1 font-heading text-4xl leading-none font-bold tracking-tight text-foreground tabular-nums">
          {failed ? "–" : state.pending || value == null ? <Skeleton className="h-9 w-20" /> : n(value)}
        </dd>
        <dt className="order-2 mt-1 text-sm font-medium text-muted-foreground">{label}</dt>
        <dd className="order-3 mt-0.5 text-xs text-muted-foreground">
          {failed ? (
            <>
              Could not load{" "}
              <button
                type="button"
                onClick={state.retry}
                className="rounded-sm text-primary underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
              >
                Retry
              </button>
            </>
          ) : state.pending ? (
            <Skeleton aria-hidden="true" className="h-3 w-40" />
          ) : (
            second
          )}
        </dd>
      </div>
      <div className="flex w-24 shrink-0 justify-end">{!failed && !state.pending && graphic}</div>
    </div>
  );
}

const spark = (data: number[]) =>
  data.length > 1 ? <Sparkline data={data} className="h-auto w-24" aria-hidden /> : null;

export function ByTheNumbers({ period, threatOnly }: { period: PeriodKey; threatOnly: boolean }) {
  const { days, words } = periodInfo(period);
  const allTime = days == null;
  const stats = useDashboardStats(days, threatOnly);
  const ransom = useDashboardRansomware(days);
  const cve = useCveExposure(days, 4); // limit sama dengan CVE watchlist: satu request
  const attn = useDashboardAttention(days);

  const st = (q: { data: unknown; isError: boolean; isPlaceholderData: boolean; refetch: () => unknown }): RowState => ({
    pending: q.data == null && !q.isError,
    error: q.isError,
    stale: q.isPlaceholderData,
    retry: () => void q.refetch(),
  });
  const s = stats.data;
  const a = attn.data; // gagal/pending: hanya bagian bersumber attention yang hilang
  const apacLine = ransom.data ? `${n(ransom.data.apac)} in APAC` : "";

  return (
    <section aria-labelledby="by-the-numbers" className="surface-raised rounded-2xl p-5">
      <h2 id="by-the-numbers" className="mb-2 text-2xs font-semibold tracking-wider text-muted-foreground uppercase">
        By the numbers · {words}
        {threatOnly && " · Threat news only"}
      </h2>
      <dl className="divide-y divide-border">
        <Row
          state={st(stats)}
          value={s?.total_articles}
          label="articles collected"
          second={s && deltaLine(s.total_articles, s.prev_total_articles, s.prev_period_reliable, allTime)}
          graphic={s && spark(s.timeline.map((p) => p.count))}
        />
        <Row
          state={st(stats)}
          value={s?.confirmed_incidents}
          label="confirmed incidents"
          second={s && deltaLine(s.confirmed_incidents, s.prev_confirmed_incidents, s.prev_period_reliable, allTime)}
          graphic={s && spark(s.timeline.map((p) => p.incidents))}
        />
        <Row
          state={st(ransom)}
          value={ransom.data?.total}
          label="ransomware victims"
          second={
            <>
              {apacLine}
              {a && a.client_countries.length > 0 && ` · ${n(a.ransomware_in_client_scope)} in your countries`}
            </>
          }
          graphic={
            ransom.data && (
              <span title="Last 8 weeks">{spark(ransom.data.weekly.map((w) => w.victims))}</span>
            )
          }
        />
        <Row
          state={st(cve)}
          value={cve.data?.open_critical}
          label="open critical CVEs"
          second={
            cve.data && (
              <>
                {n(cve.data.open_kev)} open KEV (any severity)
                {a && ` · ${a.kev_without_ticket === 0 ? "all KEV have a ticket" : `${n(a.kev_without_ticket)} KEV without a ticket`}`}
              </>
            )
          }
        />
      </dl>
    </section>
  );
}
