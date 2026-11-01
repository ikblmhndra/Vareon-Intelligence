"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { EntityChip } from "@/components/entities/entity-chip";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { SimplePager } from "@/components/pager";
import { D3fendToggle } from "@/components/newsroom/d3fend-toggle";
import type { MitreArticlesResponse } from "@/lib/api/loose-types";

const PAGE_SIZE = 20;

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

interface TtpDrillDialogProps {
  target: TtpDrillTarget | null;
  onClose: () => void;
}

/** Port `openTtpDrill()`/`_loadTtpDrillPage()`/`loadD3fendDrill()`
 * (`ttp.js:4-133`) -- overlay artikel yang match 1 cell heatmap (TTP ×
 * row), plus toggle D3FEND countermeasures buat TTP itu. D3FEND-nya
 * numpang `D3fendToggle` yang UDAH ada dari Grup D (endpoint sama
 * persis, `GET /api/mitre/d3fend/{technique_id}`). */
export function TtpDrillDialog({ target, onClose }: TtpDrillDialogProps) {
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["intelligence", "mitre-ttp-articles", target?.ttpId, target?.row, target?.view, target?.days, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mitre/articles", {
        params: {
          query: {
            ttp_id: target!.ttpId,
            row: target!.row,
            view: target!.view,
            days: target!.days,
            page,
            page_size: PAGE_SIZE,
          },
        },
      });
      if (error) throw error;
      return data as unknown as MitreArticlesResponse;
    },
    enabled: target !== null,
  });

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
          setPage(1);
        }
      }}
    >
      <DialogContent className="max-h-[85vh] w-full max-w-xl overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2 font-mono">
            {target && (
              <EntityChip
                type="attack-pattern"
                name={target.ttpId}
                id={target.ttpEntityId}
                label={target.ttpId}
              />
            )}
            <span>{target?.ttpName}</span>
          </DialogTitle>
          <div className="flex items-center justify-between gap-2">
            <p className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground">
              {target?.view === "ta" ? "Threat Actor" : "Industry"}:
              {target && (
                <EntityChip
                  type={target.view === "ta" ? "intrusion-set" : "identity"}
                  name={target.row}
                  id={target.rowEntityId}
                />
              )}
            </p>
            {target && <D3fendToggle ttpId={target.ttpId} />}
          </div>
        </DialogHeader>

        {query.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
        {query.isError && <p className="py-6 text-center text-xs text-destructive">Failed to load articles.</p>}
        {query.data && query.data.articles.length === 0 && (
          <p className="py-6 text-center text-xs text-muted-foreground">No articles found.</p>
        )}

        <div className="space-y-1">
          {query.data?.articles.map((a) => (
            <a
              key={a._id}
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block rounded-md border-b border-border px-3 py-2.5 hover:bg-muted/50"
            >
              <div className="text-xs leading-snug text-foreground">{a.title}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {a.posted_on} · {a.source}
              </div>
            </a>
          ))}
        </div>

        {query.data && total > 0 && (
          <div className="mt-2 flex items-center justify-between">
            <span className="font-mono text-xs text-muted-foreground">{total.toLocaleString()} article(s)</span>
            <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
