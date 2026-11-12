"use client";

import { SectionIcon } from "@/components/newsletter/section-icon";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { StatePanel } from "@/components/ui/state-panel";
import { Button } from "@/components/ui/button";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import type { NewsletterSections } from "@/lib/api/loose-types";
import { formatPeriodRange } from "@/lib/newsletter/format";
import { useCan } from "@/lib/auth/permissions";
import { isClientError } from "@/lib/exec/query";

interface Props {
  /** Sheet terbuka; riwayat dimuat hanya saat itu. */
  open: boolean;
  refreshKey: number;
  onPreview: (id: number, label: string) => void;
  onResend: (id: number, label: string) => void;
  resendingId: number | null;
}

/** Isi sheet "Saved newsletters" (port drawer `newsletter.html:418-429`, `loadHistory()`
 * `newsletter.html:835-868`); sheet-nya dipasang `NewsletterView`.
 * "Mind Map" per histori numpang `MindmapWidget` (G5, `featureType=
 * "newsletter"`) -- GANTI modal bespoke `_nlShowMindmapModal()`/
 * `_nlMmEdit()` legacy, konsisten sama pola inline-toggle G6/G7. */
export function NewsletterHistoryPanel({ open, refreshKey, onPreview, onResend, resendingId }: Props) {
  const can = useCan();

  const query = useQuery({
    queryKey: ["newsletter", "history", refreshKey],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/newsletter/history", {
        params: { query: { page: 1, page_size: 20 } },
      });
      if (!response.ok || !data) {
        const detail = error && typeof error === "object" && "detail" in error ? String((error as { detail: unknown }).detail) : `HTTP ${response.status}`;
        throw new Error(detail, { cause: response.status });
      }
      return data;
    },
    retry: (n, e) => n < 2 && !isClientError(e),
    enabled: open,
  });

  const newsletters = query.data?.newsletters ?? [];

  return (
    <div>
      {query.isLoading && <StatePanel variant="loading" title="Loading saved newsletters…" />}
      {query.isError && (
        <StatePanel
          variant="error"
          title="Failed to load history"
          action={
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Retry
            </Button>
          }
        />
      )}
      {query.data && newsletters.length === 0 && <StatePanel variant="empty" title="No saved newsletters yet" />}

      {newsletters.length > 0 && (
        <div className="space-y-2.5">
            {newsletters.map((n) => {
              const sections = n.sections as unknown as NewsletterSections | undefined;
              // Kartu penuh + baris "Also Noted": edisi padat punya sedikit kartu dan banyak baris.
              const apacLen = (sections?.apac?.length ?? 0) + (sections?.apac_compact?.length ?? 0);
              const globalLen = (sections?.global_news?.length ?? 0) + (sections?.global_news_compact?.length ?? 0);
              const indonesiaLen = (sections?.indonesia?.length ?? 0) + (sections?.indonesia_compact?.length ?? 0);
              const highlightTitle = sections?.highlight?.title;
              return (
                <div key={n.id} className="rounded-xl border border-border bg-background p-3">
                  <div className="font-code text-xs text-primary">{n.label}</div>
                  {n.period_start && n.period_end && (
                    <div className="font-code text-xs text-muted-foreground">{formatPeriodRange(n.period_start, n.period_end)}</div>
                  )}
                  <div className="mt-0.5 font-code text-xs text-muted-foreground">
                    {n.generated_at} · by {n.created_by}
                  </div>
                  {highlightTitle && (
                    <div className="mt-1.5 truncate text-xs text-foreground" title={highlightTitle}>
                      <SectionIcon section="highlights" className="mr-1 inline" /> {highlightTitle}
                    </div>
                  )}
                  <div className="mt-1.5 font-code text-xs text-muted-foreground">
                    <span className="mr-3 inline-flex items-center gap-1"><SectionIcon section="apac" /> {apacLen}</span>
                    <span className="mr-3 inline-flex items-center gap-1"><SectionIcon section="global_news" /> {globalLen}</span>
                    <span className="inline-flex items-center gap-1"><SectionIcon section="indonesia" /> {indonesiaLen}</span>
                  </div>
                  <div className="mt-2 flex gap-1.5">
                    <Button variant="outline" size="sm" className="h-6 flex-1 px-2 text-xs" onClick={() => onPreview(n.id, n.label)}>
                      Preview
                    </Button>
                    {can("manage_newsletter") && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 flex-1 px-2 text-xs"
                      disabled={resendingId === n.id}
                      onClick={() => onResend(n.id, n.label)}
                    >
                      {resendingId === n.id ? "…" : "Resend"}
                    </Button>
                    )}
                  </div>
                  <MindmapWidget featureType="newsletter" docId={String(n.id)} title={`Newsletter — ${n.label}`} />
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}
