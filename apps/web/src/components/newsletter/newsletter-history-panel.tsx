"use client";

import { SectionIcon } from "@/components/newsletter/section-icon";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { MindmapWidget } from "@/components/mindmap/mindmap-widget";
import type { NewsletterSections } from "@/lib/api/loose-types";
import { formatPeriodRange } from "@/lib/newsletter/format";
import { useCan } from "@/lib/auth/permissions";

interface Props {
  refreshKey: number;
  onPreview: (id: number, label: string) => void;
  onResend: (id: number, label: string) => void;
  resendingId: number | null;
}

/** Port bottom "Saved Newsletters" drawer (`newsletter.html:418-429`,
 * `loadHistory()` `newsletter.html:835-868`) -- di sini kolaps jadi
 * panel biasa (bukan `position:fixed` drawer nempel viewport, sama
 * simplifikasi kayak `GeopoliticalPanel` G7) karena `/newsletter`
 * halaman biasa dalam App Router, bukan Jinja standalone page lagi.
 * "Mind Map" per histori numpang `MindmapWidget` (G5, `featureType=
 * "newsletter"`) -- GANTI modal bespoke `_nlShowMindmapModal()`/
 * `_nlMmEdit()` legacy, konsisten sama pola inline-toggle G6/G7. */
export function NewsletterHistoryPanel({ refreshKey, onPreview, onResend, resendingId }: Props) {
  const can = useCan();
  const [open, setOpen] = useState(false);

  const query = useQuery({
    queryKey: ["newsletter", "history", refreshKey],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/newsletter/history", {
        params: { query: { page: 1, page_size: 20 } },
      });
      if (error) throw error;
      return data;
    },
    enabled: open,
  });

  const newsletters = query.data?.newsletters ?? [];

  return (
    <div className="mt-6 border-t border-border pt-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-sm font-semibold text-muted-foreground"
      >
        <span className={open ? "rotate-180 transition-transform" : "transition-transform"}>▲</span>
        Saved Newsletters
        {query.data && (
          <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-xs text-primary-text">{query.data.total}</span>
        )}
        <span className="ml-auto text-xs text-muted-foreground">{open ? "▼ collapse" : "▶ expand"}</span>
      </button>

      {open && (
        <div className="mt-3">
          {query.isLoading && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
          {query.isError && <p className="py-6 text-center text-xs text-destructive">Failed to load history.</p>}
          {query.data && newsletters.length === 0 && (
            <p className="py-6 text-center text-xs text-muted-foreground">No saved newsletters yet.</p>
          )}

          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {newsletters.map((n) => {
              const sections = n.sections as unknown as NewsletterSections | undefined;
              // Kartu penuh + baris "Also Noted": edisi padat punya sedikit kartu dan banyak baris.
              const apacLen = (sections?.apac?.length ?? 0) + (sections?.apac_compact?.length ?? 0);
              const globalLen = (sections?.global_news?.length ?? 0) + (sections?.global_news_compact?.length ?? 0);
              const indonesiaLen = (sections?.indonesia?.length ?? 0) + (sections?.indonesia_compact?.length ?? 0);
              const highlightTitle = sections?.highlight?.title;
              return (
                <div key={n.id} className="rounded-xl border border-border bg-background p-3">
                  <div className="font-mono text-xs text-primary">{n.label}</div>
                  {n.period_start && n.period_end && (
                    <div className="font-mono text-xs text-muted-foreground">{formatPeriodRange(n.period_start, n.period_end)}</div>
                  )}
                  <div className="mt-0.5 font-mono text-xs text-muted-foreground">
                    {n.generated_at} · by {n.created_by}
                  </div>
                  {highlightTitle && (
                    <div className="mt-1.5 truncate text-xs text-foreground" title={highlightTitle}>
                      <SectionIcon section="highlights" className="mr-1 inline" /> {highlightTitle}
                    </div>
                  )}
                  <div className="mt-1.5 font-mono text-xs text-muted-foreground">
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
        </div>
      )}
    </div>
  );
}
