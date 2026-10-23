"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { CampaignsResponse } from "@/lib/api/loose-types";
import { cn } from "@/lib/utils";
import { MapCard } from "./stat-box";
import { TimelineChart } from "./charts";
import {
  useCveExposure,
  useDashboardAttention,
  useDashboardRansomware,
  useDashboardTrending,
} from "./use-dashboard-overview";

/**
 * Kartu ringkasan dashboard. Tiap kartu punya query, skeleton, dan baris `Gagal memuat ...` sendiri:
 * satu endpoint gagal/lambat tidak boleh mengosongkan kartu lain. Data lama diredupkan saat
 * periode berganti (`isPlaceholderData`), bukan diganti skeleton.
 */

function CardBody({
  title,
  note,
  className,
  pending,
  error,
  stale,
  skeletonHeight = "h-40",
  children,
}: {
  title: string;
  note?: ReactNode;
  className?: string;
  pending: boolean;
  error: boolean;
  stale?: boolean;
  skeletonHeight?: string;
  children: ReactNode;
}) {
  return (
    <MapCard title={title} note={note} className={className}>
      {pending ? (
        <Skeleton aria-hidden className={cn("w-full rounded-xl", skeletonHeight)} />
      ) : error ? (
        <p className="text-sm text-destructive">Gagal memuat {title.toLowerCase()}.</p>
      ) : (
        <div className={cn("transition-opacity", stale && "opacity-60")}>{children}</div>
      )}
    </MapCard>
  );
}

/** Awal periode sebagai `YYYY-MM-DD` untuk `posted_on_start`; dihitung di queryFn (bukan saat render). */
function periodStart(days: number | null): string | undefined {
  if (!days) return undefined;
  const d = new Date(Date.now() - days * 86_400_000);
  return d.toISOString().slice(0, 10);
}

const dateFmt = new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "short" });

export function MustReadCard({ days, className }: { days: number | null; className?: string }) {
  const q = useQuery({
    queryKey: ["dashboard", "must-read", days],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/articles", {
        params: { query: { page: 1, page_size: 4, posted_on_start: periodStart(days) } },
      });
      if (error) throw error;
      return data;
    },
    placeholderData: keepPreviousData,
  });
  const articles = q.data?.articles ?? [];
  return (
    <CardBody
      title="Wajib dibaca"
      className={className}
      pending={q.isPending}
      error={q.isError}
      stale={q.isPlaceholderData}
      skeletonHeight="h-56"
    >
      {articles.length === 0 ? (
        <p className="text-sm text-muted-foreground">Belum ada berita pada periode ini.</p>
      ) : (
        <ol className="flex flex-col divide-y divide-border/70">
          {articles.map((a) => (
            <li key={a.id} className="py-3 first:pt-0 last:pb-0">
              <a
                href={a.url}
                target="_blank"
                rel="noreferrer noopener"
                className="line-clamp-2 text-sm font-medium text-foreground hover:underline"
              >
                {a.title}
              </a>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <span>{a.source}</span>
                <span aria-hidden>·</span>
                <span>{dateFmt.format(new Date(a.posted_on))}</span>
                <Badge variant="secondary">{a.news_type}</Badge>
                {a.threat_actors[0] && <Badge variant="outline">{a.threat_actors[0]}</Badge>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </CardBody>
  );
}

export function TrendingCard({ days, className }: { days: number | null; className?: string }) {
  const q = useDashboardTrending(days);
  const items = (q.data?.items ?? []).slice(0, 4);
  return (
    <CardBody
      title="Sedang naik"
      note={q.data?.window_label}
      className={className}
      pending={q.isPending}
      error={q.isError}
      stale={q.isPlaceholderData}
    >
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Belum ada tren pada periode ini.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((it) => (
            <li key={`${it.kind}:${it.name}`} className="flex items-center gap-3 text-sm">
              <span className="w-12 shrink-0 text-xs text-muted-foreground">
                {it.kind === "actor" ? "Aktor" : "TTP"}
              </span>
              <span className="min-w-0 flex-1 truncate text-foreground">{it.name}</span>
              <span className="font-code text-muted-foreground tabular-nums">{it.count}</span>
              {it.is_new ? (
                <Badge variant="secondary">baru</Badge>
              ) : it.change_pct != null ? (
                <span className="w-14 text-right text-xs font-medium text-destructive-text tabular-nums">
                  +{Math.round(it.change_pct)}%
                </span>
              ) : (
                <span className="w-14" />
              )}
            </li>
          ))}
        </ul>
      )}
    </CardBody>
  );
}

export function RansomwareCard({ days, className }: { days: number | null; className?: string }) {
  const q = useDashboardRansomware(days);
  const weekly = (q.data?.weekly ?? []).slice(-8);
  const groups = (q.data?.top_groups ?? []).slice(0, 3);
  const max = Math.max(1, ...groups.map((g) => g.count));
  return (
    <CardBody
      title="Ransomware"
      note={q.data ? `${q.data.total.toLocaleString()} korban · ${q.data.apac.toLocaleString()} di APAC` : undefined}
      className={className}
      pending={q.isPending}
      error={q.isError}
      stale={q.isPlaceholderData}
      skeletonHeight="h-52"
    >
      <div className="h-24">
        <TimelineChart
          labels={weekly.map((w) => w.week_start)}
          data={weekly.map((w) => w.victims)}
          label="Korban"
          tone="critical"
          emphasizeLast
        />
      </div>
      <ul className="mt-4 flex flex-col gap-2.5">
        {groups.map((g) => (
          <li key={g.name} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-foreground">{g.name}</span>
              <span className="font-code text-muted-foreground tabular-nums">{g.count}</span>
            </div>
            <div className="h-2 rounded-full bg-background">
              <div className="h-2 rounded-full bg-destructive" style={{ width: `${(g.count / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </CardBody>
  );
}

export function CveExposureCard({ days, className }: { days: number | null; className?: string }) {
  const q = useCveExposure(days);
  const items = (q.data?.items ?? []).slice(0, 3);
  return (
    <CardBody
      title="Eksposur CVE"
      className={className}
      pending={q.isPending}
      error={q.isError}
      stale={q.isPlaceholderData}
    >
      {q.data && (
        <>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">Tidak ada CVE terbuka yang perlu perhatian.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border/70">
              {items.map((c) => (
                <li key={c.cve_id}>
                  <Link
                    href={`/cve?search=${encodeURIComponent(c.cve_id)}`}
                    className="flex items-start gap-3 py-2.5 first:pt-0 hover:bg-muted/50"
                  >
                    {c.cisa_kev ? (
                      <Badge variant="destructive">KEV</Badge>
                    ) : (
                      <Badge variant="secondary">{c.cvss != null ? c.cvss.toFixed(1) : "—"}</Badge>
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="font-code block truncate text-sm text-foreground">{c.cve_id}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {c.tech ?? "—"} · CVSS {c.cvss != null ? c.cvss.toFixed(1) : "—"} ·{" "}
                        {c.ticket_id ? `tiket ${c.ticket_age_days ?? 0}h` : "tanpa tiket"}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted-foreground">
            {q.data.closed_in_period} tiket selesai
            {q.data.mean_days_to_close != null && ` · rata-rata ${Math.round(q.data.mean_days_to_close * 10) / 10} hari`}
          </p>
        </>
      )}
    </CardBody>
  );
}

export function ClientContextCard({ days, className }: { days: number | null; className?: string }) {
  const attention = useDashboardAttention(days);
  const cluster = useQuery({
    queryKey: ["dashboard", "newest-cluster"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/clusters/recent", { params: { query: { days: 30 } } });
      if (error) throw error;
      return (data as unknown as CampaignsResponse).campaigns[0] ?? null;
    },
  });
  const c = cluster.data;
  return (
    <CardBody
      title="Konteks klien"
      className={className}
      pending={attention.isPending}
      error={attention.isError}
      stale={attention.isPlaceholderData}
    >
      {attention.data && (
        <>
          <dl className="grid grid-cols-2 gap-3">
            <div>
              <dt className="text-xs text-muted-foreground">Cocok watchlist</dt>
              <dd className="font-heading text-2xl font-bold text-foreground tabular-nums">
                {attention.data.watchlist_hits}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Cocok PIR</dt>
              <dd className="font-heading text-2xl font-bold text-foreground tabular-nums">
                {attention.data.pir_hits}
              </dd>
            </div>
          </dl>
          <div className="mt-4 border-t border-border/70 pt-3 text-sm">
            <div className="text-xs text-muted-foreground">Kampanye terbaru</div>
            {cluster.isPending ? (
              <Skeleton aria-hidden className="mt-1 h-5 w-3/4" />
            ) : cluster.isError ? (
              <p className="mt-1 text-destructive">Gagal memuat kampanye terbaru.</p>
            ) : c ? (
              <Link href="/intelligence/campaign-clusters" className="mt-1 block text-foreground hover:underline">
                {c.cluster_name} · {c.size} artikel
              </Link>
            ) : (
              <p className="mt-1 text-muted-foreground">Belum ada kampanye.</p>
            )}
          </div>
        </>
      )}
    </CardBody>
  );
}
