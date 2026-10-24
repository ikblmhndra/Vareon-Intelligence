"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { formatWib, relativeTime } from "@/lib/cve/freshness";
import { useScraperHealth } from "@/lib/scrapers/health";

/** Ambang yang sama dengan baris "Newest tweet (X Intel)" di Data health (merah di atas 72 jam). */
const STALE_HOURS = 72;

/**
 * Peringatan di atas daftar tweet bila kolektor X diam: dulu halaman ini menampilkan tweet "21d ago"
 * tanpa penjelasan, padahal Data health sudah merah (audit UI U16). Umur dihitung di `queryFn`, bukan
 * saat render (`Date.now()` tidak murni); status `monitor_x` dari query yang dibagi dengan Scrapers.
 */
export function FeedStatusBanner() {
  const feed = useQuery({
    queryKey: ["xintel", "feed-status"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/data-health");
      if (error) throw error;
      const newest = data.sources.tweets_newest_at ?? null;
      const ms = newest ? Date.parse(newest) : Number.NaN;
      return { newest, ms, stale: Number.isNaN(ms) || Date.now() - ms > STALE_HOURS * 3_600_000 };
    },
  });
  const scrapers = useScraperHealth();
  if (!feed.data?.stale) return null;
  const { newest, ms } = feed.data;

  const monitorX = (scrapers.data?.problems ?? []).find((p) => p.id === "monitor_x");
  return (
    <div role="status" className="mb-4 rounded-md border border-destructive/40 px-3 py-2 text-xs text-destructive-text">
      {Number.isNaN(ms) ? "No tweets have been collected yet." : `No new tweets since ${relativeTime(newest!)} (${formatWib(newest!)}).`}
      {monitorX && ` The X collector is ${monitorX.status.replace("_", " ")}${monitorX.reason ? `: ${monitorX.reason}` : ""}.`}{" "}
      <Link href="/data-health" className="underline underline-offset-2">
        Open Data health
      </Link>
    </div>
  );
}
