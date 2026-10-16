"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { StatusBadge } from "@/components/scrapers/status-badge";

const STATUS_ORDER = ["dead", "degraded", "zero_yield", "stale", "disabled", "ok"];

/** Overview kesehatan fleet -- `GET /api/scraper/health` (Fase 9 H3),
 * SATU query dipakai bareng (bukan digabung) task digest Telegram
 * periodik worker. Problem row diklik -> `onSelectProblem` (buka detail
 * dialog scraper itu langsung dari sini). */
export function HealthSummaryBar({
  onSelectProblem,
}: {
  onSelectProblem: (scraperId: string, status: string) => void;
}) {
  const query = useQuery({
    queryKey: ["scrapers", "health"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/scraper/health");
      if (error) throw error;
      return data;
    },
    refetchInterval: 60_000,
  });

  if (query.isPending) {
    return <div className="mb-4 h-16 animate-pulse rounded-2xl surface-raised" />;
  }
  if (query.isError || !query.data) {
    return (
      <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-xs text-destructive-text">
        Failed to load scraper health.
      </div>
    );
  }

  const { counts, problems, generated_at } = query.data;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="mb-4 rounded-2xl surface-raised p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-muted-foreground">
          Fleet Health — {total} scraper
        </div>
        <div className="font-mono text-xs text-muted-foreground">
          as of {generated_at.replace("T", " ").split(".")[0]} UTC
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUS_ORDER.filter((s) => counts[s]).map((s) => (
          <div key={s} className="flex items-center gap-1.5 rounded-full border border-border bg-background px-2 py-1">
            <StatusBadge status={s} />
            <span className="font-mono text-xs text-foreground">{counts[s]}</span>
          </div>
        ))}
      </div>

      {problems.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="mb-1.5 text-sm font-semibold text-muted-foreground">
            Needs attention ({problems.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {problems.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelectProblem(p.id, p.status)}
                className="flex items-center gap-1.5 rounded-full border border-border bg-background px-2 py-1 text-left transition-colors hover:border-primary/40"
                title={p.last_status ? `last run: ${p.last_status}` : "never run"}
              >
                <StatusBadge status={p.status} />
                <span className="font-mono text-xs text-foreground">{p.id}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
