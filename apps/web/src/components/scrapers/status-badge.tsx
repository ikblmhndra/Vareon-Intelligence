const STATUS_STYLE: Record<string, string> = {
  ok: "bg-success/12 border-success/40 text-success-text",
  disabled: "bg-muted-foreground/12 border-muted-foreground/35 text-muted-foreground",
  stale: "bg-severity-medium/12 border-severity-medium/40 text-severity-medium-text",
  dead: "bg-destructive/18 border-destructive/50 text-destructive-text",
  degraded: "bg-warning/15 border-warning/45 text-warning-text",
  zero_yield: "bg-severity-medium/12 border-severity-medium/40 text-severity-medium-text",
};

/** Pill status kesehatan scraper -- `cti_scraper.health.HealthStatus`
 * (Fase 9 H3): ok/disabled/stale/dead/degraded/zero_yield. */
export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLE[status] ?? STATUS_STYLE.stale;
  return (
    <span className={`inline-block rounded-full border px-1.5 py-0.5 font-mono text-xs font-bold uppercase ${cls}`}>
      {status.replace("_", " ")}
    </span>
  );
}

const RUN_STATUS_STYLE: Record<string, string> = {
  ok: "text-success",
  empty: "text-muted-foreground",
  partial: "text-warning",
  fetch_error: "text-destructive",
  parse_error: "text-destructive",
  rate_limited: "text-warning",
  timeout: "text-destructive",
  backpressure: "text-warning",
  disabled: "text-muted-foreground",
  running: "text-severity-medium",
};

/** Warna teks status run (`ScraperRun.status`) -- BUKAN pill kayak
 * `StatusBadge`, dipakai inline di tabel runs (lebih banyak baris, pill
 * penuh kebesaran). */
export function RunStatusText({ status }: { status: string }) {
  return <span className={`font-mono text-xs ${RUN_STATUS_STYLE[status] ?? ""}`}>{status}</span>;
}
