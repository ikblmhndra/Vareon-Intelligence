"use client";

import { Chip } from "@/components/ui/chip";
import { Notice } from "@/components/ui/notice";
import { fmtDateTime } from "@/lib/format";
import { tickAge, useScraperHealth } from "@/lib/scrapers/health";

/** "12 min ago" atau "never" (heartbeat belum pernah tercatat). */
function ago(ageS: number | null): string {
  return ageS === null ? "never" : `${tickAge(ageS)} ago`;
}

/** Status scheduler (Celery beat) dari heartbeat Redis (`scheduler` di `GET /api/scraper/health`), satu chip
 * di header halaman. Insiden staging 2026-09-26: beat mati ~97 jam dan halaman ini tidak menunjukkan apa-apa.
 * Query-nya SAMA dengan tile dan tabel (queryKey sama, TanStack men-dedupe). */
export function SchedulerChip() {
  const scheduler = useScraperHealth().data?.scheduler;
  if (!scheduler) return null;

  if (scheduler.state === "ok") {
    return (
      <span title={scheduler.started_at ? `Up since ${fmtDateTime(scheduler.started_at)}` : undefined}>
        <Chip kind="status" value="ok">
          Scheduler alive · tick {ago(scheduler.age_s)}
        </Chip>
      </span>
    );
  }
  return (
    <Chip kind="status" value="action">
      {scheduler.state === "stale"
        ? `Scheduler down · last tick ${ago(scheduler.age_s)}`
        : "Scheduler heartbeat missing"}
    </Chip>
  );
}

/** Banner merah di bawah header saat heartbeat basi atau tidak ada (sebelumnya satu-satunya petunjuk
 * bahwa kolom NEXT hanya jadwal cron, bukan jaminan). */
export function SchedulerNotice() {
  const scheduler = useScraperHealth().data?.scheduler;
  if (!scheduler || scheduler.state === "ok") return null;

  const lastTick = scheduler.last_tick_at
    ? `${fmtDateTime(scheduler.last_tick_at)} (${ago(scheduler.age_s)})`
    : "never recorded";
  return (
    <div role="alert" className="mb-4">
      <Notice
        tone="destructive"
        title={
          scheduler.state === "stale"
            ? "Scheduler (beat) is down or stuck"
            : "Scheduler (beat) heartbeat missing"
        }
      >
        Scheduled scraper runs and periodic reports are not firing. Last heartbeat: {lastTick}; threshold{" "}
        {scheduler.stale_after_s} s. NEXT below is the cron schedule, not a guarantee. Manual runs still work.
      </Notice>
    </div>
  );
}
