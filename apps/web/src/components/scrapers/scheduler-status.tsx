"use client";

import { useScraperHealth } from "@/lib/scrapers/health";

function formatAge(ageS: number | null): string {
  if (ageS === null) return "never";
  if (ageS < 90) return `${Math.round(ageS)}s ago`;
  const min = Math.round(ageS / 60);
  if (min < 120) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h ${min % 60}m ago`;
  return `${Math.floor(hr / 24)}d ${hr % 24}h ago`;
}

/** Status scheduler (Celery beat) dari heartbeat Redis -- `scheduler` di
 * `GET /api/scraper/health` (QA BUG-D2/D8). Insiden staging 2026-09-26 ->
 * 09-30: beat mati ~97 jam dan halaman ini gak nunjukin apa-apa. Sekarang:
 * heartbeat basi / gak pernah ada = banner merah di atas tabel; sehat = satu
 * baris kecil "last tick". Query-nya SAMA dengan `HealthSummaryBar`
 * (queryKey sama -> TanStack dedupe, bukan fetch dobel). */
export function SchedulerStatus() {
  const query = useScraperHealth();

  const scheduler = query.data?.scheduler;
  if (!scheduler) return null;

  if (scheduler.state === "ok") {
    return (
      <div className="mb-2 flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
        <span className="inline-block size-1.5 rounded-full bg-success" />
        Scheduler alive — last tick {formatAge(scheduler.age_s)}
        {scheduler.started_at && <> · up since {scheduler.started_at.replace("T", " ").split(".")[0]} UTC</>}
      </div>
    );
  }

  const lastTick = scheduler.last_tick_at
    ? `${scheduler.last_tick_at.replace("T", " ").split(".")[0]} UTC (${formatAge(scheduler.age_s)})`
    : "never recorded";
  return (
    <div
      role="alert"
      className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-xs text-destructive-text"
    >
      <div className="font-semibold">
        {scheduler.state === "stale" ? "Scheduler (beat) is DOWN or stuck" : "Scheduler (beat) heartbeat missing"}
      </div>
      <div className="mt-1">
        Scheduled scraper runs and periodic reports are NOT firing. Last heartbeat: {lastTick}; threshold{" "}
        {scheduler.stale_after_s}s. &quot;Next Run&quot; below is the cron schedule, not a guarantee. Manual
        triggers still work.
      </div>
    </div>
  );
}
