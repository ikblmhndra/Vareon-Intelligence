"use client";

import { CopyIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { PanelError } from "@/components/dashboard/stat-box";
import { useArticleIocs } from "@/components/newsroom/all-articles-queries";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";
import { downloadBlob } from "@/lib/csv";
import { defang } from "@/lib/newsroom/defang";

type Article = components["schemas"]["ArticleOut"];

/** Batas baris dari API (`list_for_article(limit=200)`); dipakai hanya untuk teks "Showing the first". */
const IOC_LIMIT = 200;

/** Urutan kolom sama dengan `exportIocsCsv` di `article-modal.tsx` (disalin, bukan diimpor). */
function exportCsv(a: Article, items: { type: string; value: string }[]) {
  const rows: string[][] = [["type", "value", "article_title", "article_url", "article_source", "article_date"]];
  for (const i of items) rows.push([i.type, i.value, a.title, a.url, a.source, a.posted_on]);
  const csv = rows.map((r) => r.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `iocs_${a.title.slice(0, 40).replace(/[^a-z0-9]/gi, "_")}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function copyText(text: string) {
  try {
    // `navigator.clipboard` tidak ada di origin non-secure (dev http): fallback textarea + execCommand.
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      Object.assign(ta.style, { position: "fixed", top: "0", left: "0", opacity: "0", pointerEvents: "none" });
      document.body.appendChild(ta);
      try {
        ta.focus({ preventScroll: true });
        ta.select();
        if (!document.execCommand("copy")) throw new Error("execCommand failed");
      } finally {
        ta.remove();
      }
    }
    toast.success("Copied to clipboard");
  } catch {
    toast.error("Could not copy to clipboard.");
  }
}

/**
 * Blok IOC pembaca (spec 6.4 blok 8). Tampilan di-defang, tetapi salin dan ekspor selalu memakai nilai
 * asli. Disembunyikan bila artikel tidak punya IOC.
 */
export function ReaderIocs({ article }: { article: Article }) {
  const can = useCan();
  const query = useArticleIocs(article.id);
  const [stixBusy, setStixBusy] = useState(false);

  if (query.isPending) return <Skeleton aria-hidden className="h-24 w-full" />;
  if (query.isError && !query.data) {
    return <PanelError title="Could not load the indicators" error={query.error} onRetry={() => void query.refetch()} />;
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return null;
  const total = query.data?.total ?? items.length;

  async function exportStix() {
    setStixBusy(true);
    try {
      await downloadBlob(`/api/stix/article/${article.id}`, `stix-article-${article.id}.json`);
    } catch {
      toast.error("Export failed.");
    } finally {
      setStixBusy(false);
    }
  }

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="mr-auto text-sm font-semibold text-foreground">
          Indicators of compromise · <span>{total}</span>
        </h3>
        <Button size="xs" variant="outline" onClick={() => void copyText(items.map((i) => i.value).join("\n"))}>
          Copy all
        </Button>
        {can("view_stix") && (
          <Button size="xs" variant="outline" disabled={stixBusy} onClick={() => void exportStix()}>
            Export STIX
          </Button>
        )}
        <Button size="xs" variant="outline" onClick={() => exportCsv(article, items)}>
          Export CSV
        </Button>
      </div>
      <ul className="divide-y divide-border rounded-md border border-border">
        {items.map((i) => (
          <li key={`${i.type}:${i.value}`} className="flex items-start gap-2 px-2 py-1.5 text-xs">
            <span className="w-14 shrink-0 text-2xs font-semibold uppercase text-muted-foreground">{i.type}</span>
            <span className="min-w-0 flex-1 break-all font-code text-foreground">{defang(i.value)}</span>
            {(i.context || i.reputation) && (
              <span className="max-w-[40%] shrink-0 text-muted-foreground">
                {[i.context, i.reputation].filter(Boolean).join(" · ")}
              </span>
            )}
            <Button
              size="icon-xs"
              variant="ghost"
              aria-label={`Copy ${defang(i.value)}`}
              onClick={() => void copyText(i.value)}
            >
              <CopyIcon aria-hidden />
            </Button>
          </li>
        ))}
      </ul>
      {total > items.length && <p className="text-2xs text-muted-foreground">Showing the first {IOC_LIMIT}.</p>}
    </section>
  );
}
