"use client";

import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { formatPostedOn } from "@/lib/newsroom/dates";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { SimplePager } from "@/components/pager";
import { useArticlesQuery } from "@/components/newsroom/use-articles";
import { useRubric, type RubricItem, type RubricKey } from "@/components/newsroom/rubric-queries";

type Article = components["schemas"]["ArticleOut"];

const PAGE_SIZE = 20;

type Source = { rubric: RubricKey } | { actor: string } | { ttp: string };

function Row({ item, onSelect }: { item: RubricItem; onSelect: (a: Article) => void }) {
  const cls =
    "block w-full rounded-md px-2 py-2 text-left hover:bg-muted focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none";
  const body = (
    <>
      <span className="block text-[13.5px] leading-snug font-semibold text-foreground">{item.title}</span>
      <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{item.meta}</span>
    </>
  );
  if (item.article) {
    return (
      <button type="button" className={cls} onClick={() => onSelect(item.article!)}>
        {body}
      </button>
    );
  }
  if (item.href) {
    return (
      <a href={item.href} target="_blank" rel="noopener noreferrer" className={cls}>
        {body}
      </a>
    );
  }
  return <div className={cls}>{body}</div>;
}

/** Hook dipanggil tanpa syarat; hanya satu sumber yang aktif (`enabled`). */
function useSheetList(source: Source, filters: NewsroomFilters, page: number, open: boolean) {
  const rubricKey = "rubric" in source ? source.rubric : null;
  const rubric = useRubric(rubricKey, filters, page, PAGE_SIZE, true);
  const actor = "actor" in source ? source.actor : "";
  const ttp = "ttp" in source ? source.ttp : "";
  // Filter yang sama dengan hitungan kartu topik (periode, negara, pencarian, insiden)
  // supaya "N artikel" di kartu cocok dengan isi daftar.
  const scope = {
    page,
    page_size: PAGE_SIZE,
    sort: "recent" as const,
    posted_on_start: filters.dateStart || undefined,
    country: filters.country ? [filters.country] : undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
  };
  const byActor = useArticlesQuery(
    ["sheet-actor", actor],
    { ...scope, threat_actor: [actor] },
    open && "actor" in source,
    true,
  );
  const byTtp = useArticlesQuery(
    ["sheet-ttp", ttp],
    { ...scope, ttp: [ttp] },
    open && "ttp" in source,
    true,
  );

  if ("rubric" in source) return rubric;
  const q = "actor" in source ? byActor : byTtp;
  const items: RubricItem[] = (q.data?.articles ?? []).map((a) => ({
    id: String(a.id),
    title: a.title,
    meta: `${a.source} · ${formatPostedOn(a.posted_on)}`,
    article: a,
  }));
  return {
    items,
    total: q.data?.total,
    isPending: q.isPending,
    isError: q.isError,
    refetch: () => void q.refetch(),
  };
}

function SheetBody({
  source,
  filters,
  open,
  onSelect,
}: {
  source: Source;
  filters: NewsroomFilters;
  open: boolean;
  onSelect: (a: Article) => void;
}) {
  const [page, setPage] = useState(1);
  const { items, total, isPending, isError } = useSheetList(source, filters, page, open);
  const totalPages = total ? Math.ceil(total / PAGE_SIZE) : 0;

  return (
    <div className="flex flex-col gap-3">
      {isPending && (
        <div className="flex flex-col gap-3" aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      )}
      {isError && <p className="text-xs text-muted-foreground">Gagal memuat daftar artikel.</p>}
      {!isPending && !isError && items.length === 0 && (
        <p className="text-xs text-muted-foreground">Belum ada artikel.</p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col">
          {items.map((item) => (
            <li key={item.id}>
              <Row item={item} onSelect={onSelect} />
            </li>
          ))}
        </ul>
      )}
      <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
}

/** Daftar lengkap satu rubrik / aktor / TTP, 20 per halaman, di panel samping.
 * Isi di-mount hanya saat terbuka sehingga halaman kembali ke 1 tiap dibuka. */
export function ArticleListSheet({
  open,
  onOpenChange,
  title,
  source,
  filters,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  source: Source;
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
}) {
  const key = "rubric" in source ? source.rubric : "actor" in source ? `a:${source.actor}` : `t:${source.ttp}`;
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title={title}>
      {open && <SheetBody key={key} source={source} filters={filters} open={open} onSelect={onSelect} />}
    </Sheet>
  );
}
