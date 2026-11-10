"use client";

import Link from "next/link";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { EntityChip } from "@/components/entities/entity-chip";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { StatePanel } from "@/components/ui/state-panel";
import { api } from "@/lib/api/client";
import type { MitreArticlesResponse } from "@/lib/api/loose-types";
import { fmtShortDate } from "@/lib/format";
import { newsroomHref } from "@/lib/newsroom/links";

const PAGE_SIZE = 10;

export interface TtpDrillTarget {
  ttpId: string;
  ttpName: string;
  /** Id entity teknik dan baris (aktor) dari heatmap; null/absen = resolve by name. */
  ttpEntityId?: number | null;
  row: string;
  rowEntityId?: number | null;
  view: "ta" | "industry";
  days: number;
}

interface D3fendMeasure {
  id: string;
  name: string;
  artifact: string;
  url: string;
}

/** Batas bawah jendela heatmap sebagai "YYYY-MM-DD". Backend (`AsyncMitreHeatmapRepo`) memakai
 * `posted_on >= date.today() - days` dengan `date.today()` di zona proses server (UTC di compose), tanpa cache.
 * Jadi memakai tanggal UTC hari ini dikurangi `days` (inklusif, sama dengan `posted_on_start` Newsroom)
 * membuat jumlah artikel di Newsroom sama dengan jumlah di kartu ini, bukan tergantung zona browser. */
export function windowFrom(days: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Bagian "Countermeasures (D3FEND)": panggilan dan tampilan sama dengan `D3fendToggle` lama
 * (`GET /api/mitre/d3fend/{technique_id}`, query key sama supaya cache dipakai bersama), kini lipat-buka. */
function D3fendSection({ ttpId }: { ttpId: string }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["mitre", "d3fend", ttpId],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/mitre/d3fend/{technique_id}", {
        params: { path: { technique_id: ttpId } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (data as { countermeasures?: D3fendMeasure[] } | undefined)?.countermeasures ?? [];
    },
    enabled: open,
    staleTime: Infinity,
  });
  const Icon = open ? ChevronDownIcon : ChevronRightIcon;

  return (
    <div className="border-t border-border pt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 rounded-sm text-xs font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <Icon aria-hidden className="size-4" />
        Countermeasures (D3FEND)
      </button>
      {open && (
        <div className="mt-2">
          {query.isPending && <p className="text-xs text-muted-foreground">Loading…</p>}
          {query.isError && <p className="text-xs text-destructive-text">Failed to load.</p>}
          {query.data && query.data.length === 0 && (
            <p className="text-xs text-muted-foreground">No D3FEND countermeasures mapped for this technique.</p>
          )}
          {query.data && query.data.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {query.data.map((m) => (
                <li key={m.id}>
                  <a
                    href={m.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={m.artifact}
                    className="inline-block rounded-md border border-border bg-surface px-2 py-0.5 text-xs text-foreground outline-none hover:border-primary focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    {m.name}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Kartu drill sel heatmap (pengganti `TtpDrillDialog`): artikel yang memuat baris DAN TTP itu dalam jendela
 * heatmap, terbaru dulu, plus countermeasures D3FEND. Induk memberi `key` per sel, jadi halaman kembali ke 1
 * tiap sel baru tanpa efek reset. */
export function TtpDrillCard({ target }: { target: TtpDrillTarget }) {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["intelligence", "mitre-ttp-articles", target.ttpId, target.row, target.view, target.days, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mitre/articles", {
        params: {
          query: {
            ttp_id: target.ttpId,
            row: target.row,
            view: target.view,
            days: target.days,
            page,
            page_size: PAGE_SIZE,
          },
        },
      });
      if (error) throw error;
      return data as unknown as MitreArticlesResponse;
    },
  });

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const href = newsroomHref({
    ...(target.view === "ta" ? { actor: target.row } : { industry: target.row }),
    ttp: target.ttpId,
    from: windowFrom(target.days),
  });

  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="font-heading text-base font-semibold">
              {target.row} × <span className="font-code">{target.ttpId}</span> {target.ttpName}
            </h2>
            <p className="text-xs text-muted-foreground">
              {query.data ? `${total.toLocaleString()} articles · newest first` : "Newest first"}
            </p>
          </div>
          <Link
            href={href}
            className="rounded-sm text-xs font-semibold text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Open in Newsroom →
          </Link>
        </div>

        {/* Tautan entity baris dan teknik dipindah ke sini: sel grid dapat dipilih sehingga tak boleh memuat tautan. */}
        <div className="flex flex-wrap gap-1.5">
          <EntityChip
            type={target.view === "ta" ? "intrusion-set" : "identity"}
            name={target.row}
            id={target.rowEntityId}
          />
          <EntityChip type="attack-pattern" name={target.ttpId} id={target.ttpEntityId} label={target.ttpId} />
        </div>

        {query.isPending && <StatePanel variant="loading" title="Loading articles" className="py-8" />}
        {query.isError && <StatePanel variant="error" title="Failed to load articles" className="py-8" />}
        {query.data && query.data.articles.length === 0 && (
          <StatePanel variant="empty" title="No articles found" className="py-8" />
        )}

        {query.data && query.data.articles.length > 0 && (
          <ul className="divide-y divide-border">
            {query.data.articles.map((a) => (
              <li key={a._id} className="flex items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-sm text-xs leading-snug font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    {a.title}
                  </a>
                  <p className="mt-0.5 text-2xs text-muted-foreground">
                    {a.source} · {fmtShortDate(a.posted_on)}
                  </p>
                </div>
                {a.news_type && <Chip kind="flag" value={a.news_type} className="shrink-0" />}
              </li>
            ))}
          </ul>
        )}

        <NumberedPager page={page} totalPages={totalPages} onPageChange={setPage} label="Articles pagination" />
        <D3fendSection ttpId={target.ttpId} />
      </div>
    </Card>
  );
}
