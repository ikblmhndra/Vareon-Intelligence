import { Chip } from "@/components/ui/chip";

export type ScraperTone = "ok" | "warn" | "bad" | "unknown";

/** Status kesehatan scraper (`cti_scraper.health.HealthStatus`) ke nada tunggal untuk chip, tile,
 * tabel, panel, dan Needs attention. */
export function statusTone(status: string): ScraperTone {
  switch (status) {
    case "ok":
      return "ok";
    case "degraded":
    case "stale":
    case "zero_yield":
      return "warn";
    case "dead":
      return "bad";
    default:
      return "unknown";
  }
}

/** Chip status kesehatan scraper; teks = status dengan "_" jadi spasi. `loading` ditangani pemanggil. */
export function StatusBadge({ status }: { status: string }) {
  const text = status.replaceAll("_", " ");
  switch (statusTone(status)) {
    case "ok":
      return <Chip kind="status" value="ok">{text}</Chip>;
    case "warn":
      return <Chip kind="status" value="watch">{text}</Chip>;
    case "bad":
      return <Chip kind="status" value="action">{text}</Chip>;
    default:
      return <Chip kind="flag" value={text} />;
  }
}

const TILE_TONE = { ok: "success", warn: "warning", bad: "destructive", unknown: "neutral" } as const;

export function statusTileTone(status: string): "success" | "warning" | "destructive" | "neutral" {
  return TILE_TONE[statusTone(status)];
}

const RUN_STATUS_STYLE: Record<string, string> = {
  ok: "text-success-text",
  empty: "text-muted-foreground",
  partial: "text-warning-text",
  fetch_error: "text-destructive-text",
  parse_error: "text-destructive-text",
  rate_limited: "text-warning-text",
  timeout: "text-destructive-text",
  backpressure: "text-warning-text",
  disabled: "text-muted-foreground",
  overlap: "text-muted-foreground",
  running: "text-severity-medium-text",
};

/** Warna teks status run (`ScraperRun.status`), inline di tabel runs. */
export function RunStatusText({ status }: { status: string }) {
  return <span className={`font-code text-xs ${RUN_STATUS_STYLE[status] ?? ""}`}>{status}</span>;
}
