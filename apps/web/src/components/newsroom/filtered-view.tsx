"use client";

import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useDebounced } from "@/lib/cve/catalog";
import { errorMessage } from "@/lib/newsletter/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { PanelEmpty, PanelError, PanelLoading, PanelShell } from "@/components/newsroom/panel-shell";
import { useCan } from "@/lib/auth/permissions";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

const PAGE_SIZE = 20;
const QUERY_KEY = ["newsroom", "filtered"] as const;

type Kind = "unrelated" | "queue";

const KIND_TABS = [
  { value: "unrelated", label: "Not cyber-related" },
  { value: "queue", label: "Enrichment queue" },
] as const;

const HINT: Record<Kind, string> = {
  unrelated:
    "Articles the LLM classified as not cyber-related. Restore adds one to the news feed without enrichment (no countries, actors or TTPs).",
  queue:
    "Articles waiting for the LLM to classify them, so they are not in the news feed yet. Pending jobs are retried automatically once the model works; failed jobs need a Retry. Accept adds the article to the feed, Reject drops it.",
};

/** Umur ringkas ("5m", "3h", "2d") dari ISO; "—" kalau kosong/tidak valid. `nowMs` dibaca di dalam
 * queryFn (bukan saat render) supaya render tetap murni. */
function age(iso: string | null | undefined, nowMs: number): string {
  const ms = iso ? Date.parse(iso) : Number.NaN;
  if (Number.isNaN(ms)) return "—";
  const m = Math.max(0, Math.floor((nowMs - ms) / 60_000));
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.floor(m / 60)}h` : `${Math.floor(m / 1440)}d`;
}

const LINK =
  "rounded-sm text-sm text-foreground no-underline hover:text-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background outline-none";
const ROW = "rounded-xl border border-border bg-background p-2.5";
const CHIP = "rounded-full border px-2 text-2xs";

/** Sub-view "Filtered": dua jenis baris -- ditolak klasifikasi LLM (`rejected_articles`, bisa Restore)
 * dan antrean enrichment (`enrich_jobs` kind classify: artikel yang menunggu LLM, P7g). Terlihat untuk
 * setiap pemakai `view_news` (D18); tiap tombol dijaga izinnya sendiri: Restore/Accept/Reject
 * `manage_sources`, Retry `manage_scraper`. Tanpa izin, daftar read-only. */
export function FilteredView() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<Kind>("unrelated");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounced(search);
  const [page, setPage] = usePageResetOn(`${kind}|${debouncedSearch}`);
  const can = useCan();

  const unrelated = useQuery({
    queryKey: [...QUERY_KEY, "unrelated", debouncedSearch, page],
    enabled: kind === "unrelated",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/filtered-articles", {
          params: { query: { page, page_size: PAGE_SIZE, search: debouncedSearch || undefined, kind: "unrelated" } },
        }),
        "The request failed.",
      ),
    placeholderData: keepPreviousData,
    retry: noClientRetry,
  });

  const jobs = useQuery({
    queryKey: [...QUERY_KEY, "queue", debouncedSearch, page],
    enabled: kind === "queue",
    queryFn: async () => ({
      ...unwrap(
        await api.GET("/api/enrich-jobs", {
          params: { query: { kind: "classify", page, page_size: PAGE_SIZE, search: debouncedSearch || undefined } },
        }),
        "The request failed.",
      ),
      nowMs: Date.now(),
    }),
    placeholderData: keepPreviousData,
    retry: noClientRetry,
  });

  const restoreMutation = useMutation({
    mutationFn: async (id: number) => {
      const { error, response } = await api.POST("/api/filtered-articles/{article_id}/restore", {
        params: { path: { article_id: id } },
      });
      if (!response.ok) throw new Error(errorMessage(error));
    },
    onSuccess: () => {
      toast.success("Restored to the news feed");
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e: Error) => toast.error(`Restore failed: ${e.message}`),
  });

  const jobMutation = useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "accept" | "reject" | "retry" }) => {
      const path = { params: { path: { job_id: id } } };
      const { error, response } =
        action === "accept"
          ? await api.POST("/api/enrich-jobs/{job_id}/accept", path)
          : action === "reject"
            ? await api.POST("/api/enrich-jobs/{job_id}/reject", path)
            : await api.POST("/api/enrich-jobs/{job_id}/retry", path);
      if (!response.ok) throw new Error(errorMessage(error));
    },
    onSuccess: (_d, { action }) => {
      toast.success(
        action === "accept" ? "Accepted. The article is processed into the news feed." : action === "reject" ? "Rejected" : "Retry queued",
      );
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (e: Error, { action }) => toast.error(`${action[0].toUpperCase()}${action.slice(1)} failed: ${e.message}`),
  });

  const active = kind === "queue" ? jobs : unrelated;
  const total = active.data?.total;
  const totalPages = total !== undefined ? Math.ceil(total / PAGE_SIZE) : 0;
  const canRestore = can("manage_sources");
  const canDecide = can("manage_sources");
  const canRetry = can("manage_scraper");
  const busy = (id: number, action: string) =>
    jobMutation.isPending && jobMutation.variables?.id === id && jobMutation.variables.action === action;
  const dim = active.isPlaceholderData ? "opacity-60" : undefined;

  return (
    <div className="mx-auto max-w-3xl">
      {/* Masthead (h1 "Newsroom") tidak tampil di tab ini; halaman tetap butuh satu h1. */}
      <h1 className="sr-only">Filtered Articles</h1>
      <SegmentedControl aria-label="Filtered articles" className="mb-3" options={KIND_TABS} value={kind} onChange={setKind} />
      <PanelShell
        title={kind === "queue" ? "Enrichment queue" : "Not cyber-related"}
        count={total}
        onRefresh={() => active.refetch()}
        isRefreshing={active.isFetching}
        footer={<SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />}
      >
        <div className="mb-2 flex items-center gap-2">
          <Input
            aria-label="Search title or source"
            placeholder="Search title or source…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-52 font-code text-xs"
          />
        </div>
        <p className="mb-2 border-b border-border pb-2 text-xs text-muted-foreground">{HINT[kind]}</p>

        {active.isPending && <PanelLoading />}
        {active.isError && !active.data && (
          <PanelError
            message={active.error instanceof Error && active.error.message ? active.error.message : "The request failed."}
            onRetry={() => active.refetch()}
          />
        )}
        {active.data && active.data.items.length === 0 && (
          <PanelEmpty message={kind === "queue" ? "The enrichment queue is empty" : "No filtered articles"} />
        )}
        {kind === "unrelated" && unrelated.data && unrelated.data.items.length > 0 && (
          <div className={cn("flex flex-col gap-1.5", dim)}>
            {unrelated.data.items.map((a) => (
              <div key={a.id} className={cn("flex items-start gap-2.5", ROW)}>
                <div className="min-w-0 flex-1">
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className={LINK}>
                    {a.title}
                  </a>
                  <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-code text-xs text-muted-foreground">
                    {[(a.rejected_at ?? "").slice(0, 10), a.source, a.posted_on && `posted ${a.posted_on}`]
                      .filter(Boolean)
                      .map((t, i) => (
                        <span key={i}>{i > 0 && "· "}{t}</span>
                      ))}
                    {a.failure_kind && (
                      <span className={cn(CHIP, "border-warning/30 bg-warning/10 text-warning-text")}>{a.failure_kind}</span>
                    )}
                  </div>
                  {a.reason && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{a.reason}</p>}
                </div>
                {canRestore && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    aria-label={`Restore ${a.title}`}
                    disabled={restoreMutation.isPending && restoreMutation.variables === a.id}
                    onClick={() => restoreMutation.mutate(a.id)}
                  >
                    ↺ Restore
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
        {kind === "queue" && jobs.data && jobs.data.items.length > 0 && (
          <div className={cn("flex flex-col gap-1.5", dim)}>
            {jobs.data.items.map((j) => (
              <div key={j.id} className={cn("flex flex-wrap items-start gap-2.5", ROW)}>
                <div className="min-w-0 flex-1 basis-60">
                  <a href={j.url} target="_blank" rel="noopener noreferrer" className={LINK}>
                    {j.title}
                  </a>
                  <div className="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 font-code text-xs text-muted-foreground">
                    <span
                      className={cn(
                        CHIP,
                        j.state === "failed"
                          ? "border-destructive/30 bg-destructive/10 text-destructive-text"
                          : "border-warning/30 bg-warning/10 text-warning-text",
                      )}
                    >
                      {j.state}
                    </span>
                    {[
                      j.source,
                      `${j.attempts} ${j.attempts === 1 ? "attempt" : "attempts"}`,
                      `${age(j.created_at, jobs.data.nowMs)} old`,
                      j.p_threat_news != null && `p ${j.p_threat_news.toFixed(2)}`,
                      j.posted_on && `posted ${j.posted_on}`,
                    ]
                      .filter(Boolean)
                      .map((t, i) => (
                        <span key={i}>{i > 0 && "· "}{t}</span>
                      ))}
                  </div>
                  {j.last_error && (
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={j.last_error}>
                      {j.last_error}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 gap-1.5">
                  {canDecide && (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`Accept ${j.title}`}
                        disabled={jobMutation.isPending}
                        onClick={() => jobMutation.mutate({ id: j.id, action: "accept" })}
                      >
                        {busy(j.id, "accept") ? "Accepting…" : "Accept"}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`Reject ${j.title}`}
                        disabled={jobMutation.isPending}
                        onClick={() => jobMutation.mutate({ id: j.id, action: "reject" })}
                      >
                        {busy(j.id, "reject") ? "Rejecting…" : "Reject"}
                      </Button>
                    </>
                  )}
                  {canRetry && j.state === "failed" && (
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Retry ${j.title}`}
                      disabled={jobMutation.isPending}
                      onClick={() => jobMutation.mutate({ id: j.id, action: "retry" })}
                    >
                      {busy(j.id, "retry") ? "Retrying…" : "↻ Retry"}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </PanelShell>
    </div>
  );
}
