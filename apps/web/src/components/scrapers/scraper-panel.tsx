"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { RunStatusText, StatusBadge } from "@/components/scrapers/status-badge";
import type { ScraperRow } from "@/components/scrapers/scrapers-table";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { fmtDateTime, fmtShortDate, fmtTime } from "@/lib/format";
import { humanizeCron } from "@/lib/scrapers/cron";
import {
  noClientRetry,
  unwrap,
  useEnableScraper,
  useScraperDetail,
  writeErrorMessage,
} from "@/lib/scrapers/queries";
import { statusSentence } from "@/lib/scrapers/reason";

type HealthEntry = components["schemas"]["ScraperHealthEntryOut"];
type Detail = components["schemas"]["ScraperDetail"];
type Run = components["schemas"]["ScraperRunOut"];

const DAY_MS = 86_400_000;
const LINK_BTN =
  "rounded-md text-xs font-medium text-primary-text underline-offset-4 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none";

interface PanelProps {
  id: string | null;
  row: ScraperRow | undefined;
  entry: HealthEntry | undefined;
  /** Daftar scraper sudah dimuat: `row` kosong berarti id tidak ada di registry. */
  listReady: boolean;
  nowMs: number;
  canManage: boolean;
  onClose: () => void;
  onDisable: (row: ScraperRow) => void;
  onEditConfig: () => void;
  onResetDedup: () => void;
  onOpenHistory: () => void;
}

/** Panel samping Scrapers: ringkasan, 4 run terakhir, config efektif, aksi, dan slot hasil dry-run.
 * Isi panel di-`key` per id, jadi hasil dry-run, label pending, dan mutasi milik id yang dipilih saja dan
 * hilang saat pilihan berganti (hasil yang telat tidak muncul di scraper lain). */
export function ScraperPanel(props: PanelProps) {
  const { id, row, listReady, onClose } = props;
  if (id === null) {
    return (
      <StatePanel
        variant="empty"
        title="Select a scraper"
        description="Its recent runs, config and actions appear here."
      />
    );
  }
  if (!row) {
    return listReady ? (
      <StatePanel
        variant="empty"
        title="Unknown scraper"
        description={`${id} is not in the registry.`}
        action={
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        }
      />
    ) : (
      <Skeleton className="h-96 w-full" />
    );
  }
  return <PanelBody key={id} {...props} id={id} row={row} />;
}

function PanelBody({
  id,
  row,
  entry,
  nowMs,
  canManage,
  onClose,
  onDisable,
  onEditConfig,
  onResetDedup,
  onOpenHistory,
}: PanelProps & { id: string; row: ScraperRow }) {
  const queryClient = useQueryClient();
  const detail = useScraperDetail(id);
  const enable = useEnableScraper();

  const runs = useQuery({
    queryKey: ["scrapers", id, "runs", "recent"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/scraper/{scraper_id}/runs", {
          params: {
            path: { scraper_id: id },
            query: { page: 1, page_size: 4 },
          },
        }),
        "Could not load runs",
      ),
    retry: noClientRetry,
    refetchInterval: 60_000,
  });

  const trigger = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/trigger", {
          params: { path: { scraper_id: id } },
        }),
        "Trigger failed",
      ),
    onSuccess: (data) => {
      toast.success(`Run queued for ${id} · task ${data.celery_task_id.slice(0, 8)}`);
      void queryClient.invalidateQueries({
        queryKey: ["scrapers", id, "runs"],
      });
    },
    onError: (e: Error) => toast.error(`Trigger failed: ${writeErrorMessage(e)}`),
  });

  const dryRun = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/dry-run", {
          params: { path: { scraper_id: id } },
        }),
        "Dry run failed",
      ),
    onError: (e: Error) => toast.error(`Dry run failed for ${id}: ${writeErrorMessage(e)}`),
  });

  const sentence = row.status === "loading" ? null : statusSentence(row.status, entry, row, nowMs);

  return (
    <div className="surface-raised space-y-4 p-4">
      <div>
        <div className="flex items-start justify-between gap-2">
          <h2 className="min-w-0 font-heading text-base font-semibold text-foreground">{row.source}</h2>
          <Button variant="ghost" size="icon-sm" aria-label="Close panel" onClick={onClose}>
            ✕
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          <span className="font-code">{id}</span>
          {" · queue "}
          <span className="font-code">{row.queue}</span>
          {" · "}
          {humanizeCron(row.schedule)}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {row.status === "loading" ? (
            <Skeleton className="h-5 w-14 rounded-full" aria-label="Loading status" />
          ) : (
            <StatusBadge status={row.status} />
          )}
          {sentence && <p className="min-w-0 text-xs text-muted-foreground">{sentence}</p>}
        </div>
      </div>

      {canManage && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => trigger.mutate()} loading={trigger.isPending}>
              {trigger.isPending ? "Queuing…" : "Run now"}
            </Button>
            <Button size="sm" variant="outline" onClick={() => dryRun.mutate()} loading={dryRun.isPending}>
              {dryRun.isPending ? "Running…" : "Dry run"}
            </Button>
            {row.enabled ? (
              <Button size="sm" variant="outline" onClick={() => onDisable(row)}>
                Disable
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => enable.mutate(id)}
                loading={enable.isPending}
              >
                {enable.isPending ? "Enabling…" : "Enable"}
              </Button>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={onEditConfig}>
              Edit config…
            </Button>
            <Button size="sm" variant="ghost" onClick={onResetDedup}>
              Reset dedup…
            </Button>
          </div>
          <DryRunSlot mutation={dryRun} />
        </div>
      )}

      <section aria-labelledby="panel-runs">
        <h3 id="panel-runs" className="mb-1.5 text-2xs font-semibold tracking-wide text-muted-foreground">
          RECENT RUNS
        </h3>
        {runs.isPending ? (
          <Skeleton className="h-20 w-full" />
        ) : runs.isError && !runs.data ? (
          <p className="text-xs text-destructive-text">Could not load runs.</p>
        ) : runs.data && runs.data.runs.length === 0 ? (
          <p className="text-xs text-muted-foreground">No runs yet</p>
        ) : (
          <ul className="divide-y divide-border">
            {runs.data?.runs.map((r) => (
              <RunLine key={r.run_id} run={r} nowMs={nowMs} />
            ))}
          </ul>
        )}
        <button type="button" onClick={onOpenHistory} className={`mt-2 ${LINK_BTN}`}>
          All runs and items
        </button>
      </section>

      <section aria-labelledby="panel-config">
        <h3 id="panel-config" className="mb-1.5 text-2xs font-semibold tracking-wide text-muted-foreground">
          CONFIG
        </h3>
        {detail.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : detail.isError ? (
          <StatePanel
            variant="error"
            title="Could not load the scraper config"
            className="py-6"
            action={
              <Button variant="outline" size="sm" onClick={() => void detail.refetch()}>
                Retry
              </Button>
            }
          />
        ) : (
          <ConfigSummary d={detail.data} />
        )}
      </section>
    </div>
  );
}

function RunLine({ run, nowMs }: { run: Run; nowMs: number }) {
  const startedMs = Date.parse(run.started_at);
  const when = nowMs - startedMs < DAY_MS ? fmtTime(run.started_at) : fmtShortDate(run.started_at);
  const message = typeof run.errors[0]?.message === "string" ? run.errors[0].message : null;
  const tail = message ?? `${run.items_new} new`;
  return (
    <li className="flex items-baseline gap-2 py-1.5 text-xs">
      <span className="w-14 shrink-0 text-muted-foreground" title={fmtDateTime(run.started_at)}>
        {when}
      </span>
      <RunStatusText status={run.status} />
      <span className="min-w-0 flex-1 truncate text-muted-foreground" title={message ?? undefined}>
        {run.items_found} found · {tail}
      </span>
    </li>
  );
}

function ConfigSummary({ d }: { d: Detail }) {
  const c = d.config;
  const overridden = [
    c.schedule !== null && "schedule",
    c.rate_limit !== null && "rate limit",
    c.max_items !== null && "max items",
    c.paused_reason !== null && "paused reason",
    c.options && Object.keys(c.options).length > 0 && "options",
  ].filter((x): x is string => typeof x === "string");
  const who = [c.updated_by, c.updated_at ? fmtDateTime(c.updated_at) : null].filter(Boolean);
  const rows: [string, React.ReactNode][] = [
    [
      "Schedule",
      <span key="s" className="font-code">
        {c.schedule ?? d.default_schedule}
      </span>,
    ],
    ["Max items", c.max_items ?? d.default_max_items],
    ["Rate limit", c.rate_limit ?? d.default_rate_limit],
    ...d.options.map((o): [string, React.ReactNode] => [
      o.label,
      o.choices.find((ch) => ch.value === o.value)?.label ?? o.value,
    ]),
    ["Override", overridden.length ? [overridden.join(", "), ...who].join(" · ") : "none"],
  ];
  return (
    <>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-words text-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      <Disclosure title="Defaults and metadata" className="mt-2">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 pb-1 text-xs">
          {(
            [
              ["Runtime", d.runtime],
              ["Default schedule", d.default_schedule],
              ["Default rate limit", d.default_rate_limit],
              ["Default max items", d.default_max_items],
              ["Credential", d.credential ?? "none"],
              ["Tags", d.tags.length ? d.tags.join(", ") : "none"],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="min-w-0 break-words font-code text-foreground">{v}</dd>
            </div>
          ))}
        </dl>
      </Disclosure>
    </>
  );
}

function DryRunSlot({
  mutation,
}: {
  mutation: {
    isPending: boolean;
    isError: boolean;
    error: Error | null;
    data?: components["schemas"]["ScraperDryRunResult"];
  };
}) {
  if (mutation.isPending) {
    return (
      <Notice busy title="Dry run in progress">
        This reads the real source and writes nothing.
      </Notice>
    );
  }
  if (mutation.isError) {
    return (
      <Notice tone="destructive" title="Dry run failed">
        {writeErrorMessage(mutation.error)}
      </Notice>
    );
  }
  const r = mutation.data;
  if (!r) return null;
  return (
    <Notice
      tone={r.errors.length ? "warning" : "neutral"}
      title={`Dry run: ${r.status} · ${r.items_found} items found · ${r.duration_ms} ms`}
    >
      {r.errors.length > 0 &&
        r.errors.map((e, i) => (
          <p key={i}>{typeof e.message === "string" ? e.message : JSON.stringify(e)}</p>
        ))}
    </Notice>
  );
}
