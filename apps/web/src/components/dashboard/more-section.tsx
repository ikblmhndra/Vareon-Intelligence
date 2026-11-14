"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { BreakdownList } from "@/components/dashboard/breakdown-list";
import { HorizontalBarChart, TimelineChart } from "@/components/dashboard/charts";
import { ChartCard, DashboardSectionLabel, MapCard, PanelError } from "@/components/dashboard/stat-box";
import {
  TREND_KINDS,
  useDashboardAttention,
  useDashboardRansomware,
  useDashboardStats,
  useDashboardTrending,
  useNewestCluster,
  useTaStats,
} from "@/components/dashboard/use-dashboard-overview";
import { Disclosure } from "@/components/ui/disclosure";
import { Skeleton } from "@/components/ui/skeleton";
import { useCan } from "@/lib/auth/permissions";
import { periodInfo, type PeriodKey } from "@/lib/dashboard/period";
import { toTitleCase } from "@/lib/exec/format";
import { cn } from "@/lib/utils";

/** Panel "More" (6.7): ditutup saat dimuat; query tambahan (TA, cluster) baru jalan setelah pertama kali dibuka.
 * `opened` tidak pernah di-reset: menutup lalu membuka lagi tidak mengirim apa pun dan data tetap ada. */
export function MoreSection({ period, threatOnly }: { period: PeriodKey; threatOnly: boolean }) {
  const can = useCan();
  const [open, setOpen] = useState(false);
  const [opened, setOpened] = useState(false);
  const days = periodInfo(period).days;

  // Hook query ada di dalam komponen panel yang hanya dipasang saat `opened`, jadi tidak ada request sebelum dibuka.
  return (
    <Disclosure
      title="More"
      headingLevel={2}
      printOpen={opened}
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setOpened(true);
      }}
      className="mt-10"
    >
      {opened && <MoreBody days={days} threatOnly={threatOnly} can={can} />}
    </Disclosure>
  );
}

function PanelSkeleton({ height }: { height: number }) {
  return <Skeleton aria-hidden className="w-full rounded-xl" style={{ height }} />;
}

function MoreBody({
  days,
  threatOnly,
  can,
}: {
  days: number | null;
  threatOnly: boolean;
  can: ReturnType<typeof useCan>;
}) {
  const stats = useDashboardStats(days, threatOnly);
  const ransomware = useDashboardRansomware(days);
  const attention = useDashboardAttention(days);
  const trending = useDashboardTrending(days, TREND_KINDS);
  // Dua query tambahan: hanya bila izinnya ada, dan hanya sejak "More" pernah dibuka (body ini baru terpasang saat itu).
  const ta = useTaStats(can("view_ta"));
  const cluster = useNewestCluster(can("view_intel"));

  const dim = (placeholder: boolean) => cn("transition-opacity", placeholder && "opacity-60");
  const s = stats.data;
  const r = ransomware.data;
  const newActors = trending.data?.items.filter((i) => i.kind === "actor" && i.is_new).length;

  let context: ReactNode;
  if (attention.isPending || stats.isPending) {
    context = <PanelSkeleton height={160} />;
  } else if ((attention.isError && !attention.data) || (stats.isError && !stats.data)) {
    const failed = attention.isError && !attention.data ? attention : stats;
    context = (
      <PanelError title="Could not load your context" error={failed.error} onRetry={() => void failed.refetch()} />
    );
  } else if (attention.data && s) {
    context = (
      <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ContextItem label="Watchlist matches" value={attention.data.watchlist_hits.toLocaleString("en-US")} />
        <ContextItem label="PIRs with new articles" value={attention.data.pir_hits.toLocaleString("en-US")} />
        <ContextItem
          label="Actors in the news"
          value={s.total_threat_actors.toLocaleString("en-US")}
          sub={newActors != null ? `${newActors.toLocaleString("en-US")} new this period` : undefined}
        />
        {can("view_intel") && (
          <ContextItem
            label="Newest campaign cluster"
            value={
              cluster.isPending ? (
                <Skeleton aria-hidden className="mt-1 h-5 w-3/4" />
              ) : cluster.isError && !cluster.data ? (
                <span className="text-sm text-destructive-text">{cluster.error instanceof Error ? cluster.error.message : "Could not load the newest campaign cluster."}</span>
              ) : cluster.data ? (
                <Link
                  href="/intelligence/campaign-clusters"
                  className="text-sm font-normal hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
                >
                  {cluster.data.cluster_name} · {cluster.data.size} articles
                </Link>
              ) : (
                <span className="text-sm font-normal text-muted-foreground">No campaign cluster yet.</span>
              )
            }
          />
        )}
      </dl>
    );
  }

  return (
    <div className="mt-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        {can("view_news") && (
          <>
            <ChartCard
              className={cn("lg:col-span-8", dim(stats.isPlaceholderData))}
              title="Articles over time"
              height={280}
            >
              {stats.isPending ? (
                <PanelSkeleton height={280} />
              ) : stats.isError && !stats.data ? (
                <PanelError
                  title="Could not load articles over time"
                  error={stats.error}
                  onRetry={() => void stats.refetch()}
                />
              ) : s ? (
                <TimelineChart
                  labels={s.timeline.map((x) => x.date)}
                  data={s.timeline.map((x) => x.count)}
                  label="All news"
                  tone="info"
                  secondary={{ label: "Incidents", data: s.timeline.map((x) => x.incidents), tone: "primary" }}
                />
              ) : null}
            </ChartCard>
            <MapCard
              className={cn("lg:col-span-4", dim(ransomware.isPlaceholderData))}
              title="Ransomware victims per week"
              note={r ? `${r.total.toLocaleString("en-US")} victims · ${r.apac.toLocaleString("en-US")} in APAC` : undefined}
            >
              <div className="h-56">
                {ransomware.isPending ? (
                  <PanelSkeleton height={224} />
                ) : ransomware.isError && !ransomware.data ? (
                  <PanelError
                    title="Could not load ransomware victims per week"
                    error={ransomware.error}
                    onRetry={() => void ransomware.refetch()}
                  />
                ) : r ? (
                  <TimelineChart
                    labels={r.weekly.slice(-8).map((w) => w.week_start)}
                    data={r.weekly.slice(-8).map((w) => w.victims)}
                    label="Victims"
                    tone="critical"
                    emphasizeLast
                  />
                ) : null}
              </div>
            </MapCard>
            <MapCard
              flat
              className={cn("lg:col-span-12", dim(attention.isPlaceholderData || stats.isPlaceholderData))}
              title="Your context"
            >
              {context}
            </MapCard>
          </>
        )}
      </div>

      {can("view_ta") && (
        <>
          <DashboardSectionLabel aside="All time. The period filter does not apply here." className="mt-6">
            Threat Actor Room
          </DashboardSectionLabel>
          {ta.isPending ? (
            <div aria-hidden className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              <Skeleton className="h-72 rounded-2xl lg:col-span-4" />
              <Skeleton className="h-72 rounded-2xl lg:col-span-8" />
            </div>
          ) : ta.isError && !ta.data ? (
            <PanelError
              title="Could not load threat actor room"
              error={ta.error}
              onRetry={() => void ta.refetch()}
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              <MapCard flat className="lg:col-span-4" title="APT Groups by Source">
                {ta.data.by_source.length ? (
                  <BreakdownList items={ta.data.by_source.map((x) => ({ label: toTitleCase(x.name), count: x.count }))} />
                ) : (
                  <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
                    No APT group sources yet.
                  </p>
                )}
              </MapCard>
              <ChartCard className="lg:col-span-8" title="Tracked APT Groups in the News" height={260}>
                {ta.data.top_in_news.length ? (
                  <HorizontalBarChart
                    labels={ta.data.top_in_news.map((x) => toTitleCase(x.name))}
                    data={ta.data.top_in_news.map((x) => x.count)}
                    tone="info"
                  />
                ) : (
                  <p className="flex h-full items-center justify-center text-xs text-muted-foreground">
                    No tracked groups mentioned yet.
                  </p>
                )}
              </ChartCard>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ContextItem({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div>
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="mt-1 font-heading text-2xl font-bold text-foreground tabular-nums">{value}</dd>
      {sub && <dd className="text-sm text-muted-foreground">{sub}</dd>}
    </div>
  );
}
