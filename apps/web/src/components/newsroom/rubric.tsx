"use client";

import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { Skeleton } from "@/components/ui/skeleton";
import { GradeChip } from "@/components/newsroom/grade-chip";
import { useRubric, type RubricItem, type RubricKey } from "@/components/newsroom/rubric-queries";

type Article = components["schemas"]["ArticleOut"];

const ITEM_BUTTON =
  "block w-full rounded-md px-1 py-1.5 text-left focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none hover:bg-muted";

function ItemBody({ item }: { item: RubricItem }) {
  return (
    <>
      <span className="block text-[13.5px] leading-snug font-semibold text-foreground">{item.title}</span>
      <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted-foreground">
        {item.meta}
        {item.article && <GradeChip a={item.article} />}
      </span>
    </>
  );
}

/** Rubrik ringkas (3 item teratas) + tombol "Lihat semua". Korban ransomware
 * membuka `post_url` di tab baru, persis seperti panel lama. */
export function Rubric({
  rubric,
  title,
  filters,
  onSelect,
  onSeeAll,
  hideWhenEmpty,
}: {
  rubric: RubricKey;
  title: string;
  filters: NewsroomFilters;
  onSelect: (a: Article) => void;
  onSeeAll: () => void;
  hideWhenEmpty?: boolean;
}) {
  const { items, total, isPending, isError } = useRubric(rubric, filters, 1, 3);

  if (hideWhenEmpty && !isPending && !isError && items.length === 0) return null;

  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="text-xs tracking-widest text-primary-text uppercase">
        {title}
        {total !== undefined && <span className="ml-2 text-muted-foreground">{total.toLocaleString()}</span>}
      </h2>
      {isPending && (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      )}
      {isError && <p className="text-xs text-muted-foreground">Gagal memuat {title}.</p>}
      {!isPending && !isError && items.length === 0 && (
        <p className="text-xs text-muted-foreground">Belum ada artikel.</p>
      )}
      {items.length > 0 && (
        <ul className="flex flex-col">
          {items.slice(0, 3).map((item) => (
            <li key={item.id}>
              {item.article ? (
                <button type="button" className={ITEM_BUTTON} onClick={() => onSelect(item.article!)}>
                  <ItemBody item={item} />
                </button>
              ) : item.href ? (
                <a href={item.href} target="_blank" rel="noopener noreferrer" className={ITEM_BUTTON}>
                  <ItemBody item={item} />
                </a>
              ) : (
                <div className={ITEM_BUTTON}>
                  <ItemBody item={item} />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        onClick={onSeeAll}
        className="self-start rounded-md px-1 text-xs font-medium text-primary-text focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none hover:underline"
      >
        Lihat semua →
      </button>
    </section>
  );
}
