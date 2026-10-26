"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { formatPostedOn } from "@/lib/newsroom/dates";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { SimplePager } from "@/components/pager";
import { GradeChip } from "@/components/newsroom/grade-chip";
import { useArticlesQuery } from "@/components/newsroom/use-articles";
import {
  useRubric,
  type RubricItem,
  type RubricKey,
  type VictimFilter,
} from "@/components/newsroom/rubric-queries";

type Article = components["schemas"]["ArticleOut"];

const PAGE_SIZE = 20;
const RELATED_PAGE_SIZE = 8;
const ALL = "__all__";

type Source = { rubric: RubricKey } | { actor: string } | { ttp: string } | { story: number };

function Row({ item, onSelect }: { item: RubricItem; onSelect: (a: Article) => void }) {
  const cls =
    "block w-full rounded-md px-2 py-2 text-left hover:bg-muted focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none";
  const body = (
    <>
      <span className="block text-[13.5px] leading-snug font-semibold text-foreground">{item.title}</span>
      <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted-foreground">
        {item.meta}
        {item.article && <GradeChip a={item.article} />}
      </span>
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
function useSheetList(
  source: Source,
  filters: NewsroomFilters,
  page: number,
  open: boolean,
  victimFilter: VictimFilter,
) {
  const rubricKey = "rubric" in source ? source.rubric : null;
  const rubric = useRubric(rubricKey, filters, page, PAGE_SIZE, true, victimFilter);
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
  // Satu cerita: semua anggotanya, tanpa filter periode/negara/pencarian (anggota bisa di luar periode).
  const story = "story" in source ? source.story : 0;
  const byStory = useArticlesQuery(
    ["sheet-story", story],
    { page, page_size: PAGE_SIZE, sort: "recent" as const, story_id: story },
    open && "story" in source,
    true,
  );

  if ("rubric" in source) return rubric;
  const q = "actor" in source ? byActor : "story" in source ? byStory : byTtp;
  const items: RubricItem[] = (q.data?.articles ?? []).map(articleRow);
  return {
    items,
    total: q.data?.total,
    isPending: q.isPending,
    isError: q.isError,
    refetch: () => void q.refetch(),
  };
}

function articleRow(a: Article): RubricItem {
  return { id: String(a.id), title: a.title, meta: `${a.source} · ${formatPostedOn(a.posted_on)}`, article: a };
}

function ListState({
  isPending,
  isError,
  empty,
  emptyText,
  errorText = "Gagal memuat daftar artikel.",
}: {
  isPending: boolean;
  isError: boolean;
  empty: boolean;
  emptyText: string;
  errorText?: string;
}) {
  if (isPending) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (isError) return <p className="text-xs text-muted-foreground">{errorText}</p>;
  if (empty) return <p className="text-xs text-muted-foreground">{emptyText}</p>;
  return null;
}

/** Pilihan group/industri korban dari `/api/ransomware/victims/filters` (port mini-filter panel
 * Ransomware lama; dulu input teks bebas, sekarang daftar nilai yang memang ada). */
function VictimFilterBar({ value, onChange }: { value: VictimFilter; onChange: (v: VictimFilter) => void }) {
  const options = useQuery({
    queryKey: ["ransomware", "victim-filters"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/victims/filters");
      if (error) throw error;
      return data as unknown as { groups: string[]; industries: string[] };
    },
    staleTime: 5 * 60_000,
  });
  const fields = [
    { key: "group" as const, label: "Group", all: "Semua group", values: options.data?.groups ?? [] },
    { key: "industry" as const, label: "Industri", all: "Semua industri", values: options.data?.industries ?? [] },
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {fields.map((f) => (
        <Select
          key={f.key}
          items={{ [ALL]: f.all, ...Object.fromEntries(f.values.map((v) => [v, v])) }}
          value={value[f.key] || ALL}
          onValueChange={(v) => onChange({ ...value, [f.key]: !v || v === ALL ? "" : v })}
        >
          <SelectTrigger aria-label={`Filter korban per ${f.label.toLowerCase()}`} className="w-44 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL} className="text-xs">
              {f.all}
            </SelectItem>
            {f.values.map((v) => (
              <SelectItem key={v} value={v} className="text-xs">
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}
    </div>
  );
}

/** "Related Articles" panel Ransomware lama: `/api/ransomware/related-articles` tanpa filter apa
 * pun (port apa adanya, sama seperti panel lama), dengan pager sendiri. */
function RelatedArticles({ onSelect }: { onSelect: (a: Article) => void }) {
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["ransomware", "articles", page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ransomware/related-articles", {
        params: { query: { page, page_size: RELATED_PAGE_SIZE } },
      });
      if (error) throw error;
      return data as unknown as { articles: Article[]; total: number };
    },
  });
  const items = (q.data?.articles ?? []).map(articleRow);
  const totalPages = q.data ? Math.ceil(q.data.total / RELATED_PAGE_SIZE) : 0;
  return (
    <section aria-labelledby="rw-related" className="flex flex-col gap-3 border-t border-border pt-4">
      <h3 id="rw-related" className="text-sm font-semibold">
        Artikel terkait
      </h3>
      <ListState
        isPending={q.isPending}
        isError={q.isError}
        empty={items.length === 0}
        emptyText="Belum ada artikel ransomware terkait."
      />
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
    </section>
  );
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
  const [victimFilter, setVictimFilter] = useState<VictimFilter>({ group: "", industry: "" });
  const { items, total, isPending, isError } = useSheetList(source, filters, page, open, victimFilter);
  const totalPages = total ? Math.ceil(total / PAGE_SIZE) : 0;
  const isRansomware = "rubric" in source && source.rubric === "ransomware";

  return (
    <div className="flex flex-col gap-3">
      {isRansomware && (
        <VictimFilterBar
          value={victimFilter}
          onChange={(v) => {
            setVictimFilter(v);
            setPage(1);
          }}
        />
      )}
      <ListState
        isPending={isPending}
        isError={isError}
        empty={items.length === 0}
        emptyText={isRansomware ? "Belum ada korban." : "Belum ada artikel."}
        errorText={isRansomware ? "Gagal memuat daftar korban." : undefined}
      />
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
      {isRansomware && <RelatedArticles onSelect={onSelect} />}
    </div>
  );
}

/** Daftar lengkap satu rubrik / aktor / TTP / cerita, 20 per halaman, di panel samping.
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
  const key =
    "rubric" in source
      ? source.rubric
      : "actor" in source
        ? `a:${source.actor}`
        : "story" in source
          ? `s:${source.story}`
          : `t:${source.ttp}`;
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title={title}>
      {open && <SheetBody key={key} source={source} filters={filters} open={open} onSelect={onSelect} />}
    </Sheet>
  );
}
