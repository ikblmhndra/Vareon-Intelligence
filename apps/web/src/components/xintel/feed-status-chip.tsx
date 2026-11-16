"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { Chip } from "@/components/ui/chip";
import { api } from "@/lib/api/client";
import { isClientError } from "@/lib/exec/query";
import { fmtAgo } from "@/lib/format";
import { useScraperHealth } from "@/lib/scrapers/health";

/** Ambang kesegaran tweet (D19): peringatan di atas 24 jam, merah di atas 72 jam. */
const WARN_HOURS = 24;
const STALL_HOURS = 72;
const HOUR_MS = 3_600_000;

/**
 * Chip kesehatan feed di header X Intel (menggantikan banner). Umur dihitung di `queryFn` (`Date.now()`
 * tidak murni di render). 403 (tanpa `view_ops`) = chip hilang tanpa retry; bukan galat untuk pengguna.
 */
export function FeedStatusChip() {
  const feed = useQuery({
    queryKey: ["xintel", "feed-status"],
    retry: (n, e) => n < 2 && !isClientError(e),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/data-health");
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      const newest = data?.sources.tweets_newest_at ?? null;
      return { newest, nowMs: Date.now() };
    },
  });
  const scrapers = useScraperHealth();
  if (!feed.data) return null;

  const { newest, nowMs } = feed.data;
  const ms = newest ? Date.parse(newest) : Number.NaN;
  const ageH = Number.isNaN(ms) ? Number.POSITIVE_INFINITY : (nowMs - ms) / HOUR_MS;
  if (ageH <= WARN_HOURS) return null;

  const stalled = ageH > STALL_HOURS;
  const monitorX = (scrapers.data?.problems ?? []).find((p) => p.id === "monitor_x");
  const label = Number.isNaN(ms)
    ? "No posts collected yet"
    : `${stalled ? "Feed stalled" : "Feed delayed"} · newest post ${fmtAgo(newest, nowMs)}`;

  return (
    <div className="flex flex-col items-start gap-1 lg:items-end">
      <Chip kind="status" value={stalled ? "action" : "watch"}>
        {label}
      </Chip>
      <p className="text-2xs text-muted-foreground">
        {monitorX && `X collector ${monitorX.status.replace("_", " ")}${monitorX.reason ? `: ${monitorX.reason}` : ""}. `}
        <Link href="/data-health" className="underline underline-offset-2">
          Open Data health
        </Link>
      </p>
    </div>
  );
}
