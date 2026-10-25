"use client";

import { ChevronRightIcon } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api/client";

/**
 * Teknik ATT&CK yang dikenal untuk aktor/malware di artikel (P4). Diambil
 * dari katalog ATT&CK, BUKAN dari teks artikel, jadi dipisah dari tabel TTP
 * dan baru di-fetch saat pertama kali di-expand.
 */
export function InferredTtpsSection({ articleId }: { articleId: number }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["articles", articleId, "inferred-ttps"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/articles/{article_id}/inferred-ttps", {
        params: { path: { article_id: articleId } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return data ?? [];
    },
    enabled: open,
    staleTime: Infinity,
  });

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm font-semibold text-muted-foreground"
      >
        <ChevronRightIcon aria-hidden className={`size-4 transition-transform ${open ? "rotate-90" : ""}`} />
        Known TTPs of related entities
      </button>
      {open && (
        <div className="mt-1.5 space-y-3 rounded-md border border-border bg-muted/30 p-2">
          <p className="text-xs text-muted-foreground">Inferred from ATT&amp;CK, not stated in this article</p>
          {query.isPending && <span className="text-xs text-muted-foreground">Loading…</span>}
          {query.isError && <span className="text-xs text-destructive">Failed to load.</span>}
          {query.data && query.data.length === 0 && (
            <span className="text-xs text-muted-foreground">
              No ATT&amp;CK techniques known for these entities
            </span>
          )}
          {query.data?.map((e) => (
            <div key={`${e.kind}-${e.entity}`}>
              <div className="mb-1 text-xs font-semibold text-foreground">Known TTPs of {e.entity}</div>
              <div className="flex flex-wrap gap-1.5">
                {e.techniques.map((t) => (
                  <Badge key={t.id} variant="outline" className="text-xs">
                    <span className="font-code">{t.id}</span>
                    <span className="ml-1">{t.name}</span>
                  </Badge>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
