"use client";

import { XIcon } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";

import { AllList } from "@/components/newsroom/all-list";
import { useAllArticles, useAllListQuery } from "@/components/newsroom/all-articles-queries";
import { AllRail } from "@/components/newsroom/all-rail";
import { ArticleReader } from "@/components/newsroom/article-reader";
import { Disclosure } from "@/components/ui/disclosure";
import { fmtShortDate, parseLocalDate } from "@/lib/format";
import type { AllPatch, AllState } from "@/lib/newsroom/all-state";

const XL = "(min-width: 1280px)";

/** `matchMedia` lewat useSyncExternalStore: server dan hidrasi pertama = false, jadi rail dipasang
 * satu kali saja (di Disclosure atau di kolom), bukan dua salinan yang disembunyikan CSS. */
function useIsXl(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(XL);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(XL).matches,
    () => false,
  );
}

const CHIP =
  "inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-panel px-2.5 py-1 text-xs text-foreground hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

function LinkChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <button type="button" className={CHIP} onClick={onRemove} aria-label={`Remove filter ${label}`}>
      <span className="truncate">{label}</span>
      <XIcon aria-hidden className="size-3 shrink-0" />
    </button>
  );
}

/** Tampilan All articles (spec 6.1, 6.7): tiga kolom dari 1280 px, rail dilipat di bawah itu,
 * satu kolom di bawah 1024 px dengan pembaca di bawah daftar. Seluruh state ada di URL. */
export function AllArticlesView({
  state,
  onChange,
}: {
  state: AllState;
  onChange: (patch: AllPatch) => void;
}) {
  const isXl = useIsXl();
  const { query } = useAllListQuery(state);
  const list = useAllArticles(query);
  // Query mati (plan bukan objek) = daftar tersembunyi; keepPreviousData masih menahan halaman lama,
  // jadi pembaca tidak boleh melangkah ("{i} of {n}") di daftar basi itu.
  const listArticles = useMemo(
    () => (query === undefined ? [] : (list.data?.pages.flatMap((p) => p.articles) ?? [])),
    [query, list.data],
  );

  const storyLabel =
    state.story === null
      ? null
      : list.isPlaceholderData || list.isPending
        ? `Story ${state.story}`
        : listArticles[0]?.title || `Story ${state.story}`;

  const chips: { key: string; label: string; remove: () => void }[] = [
    // `q` dibawa dari klik Front page (aturan 6) dan `from` dari tautan Intelligence; keduanya harus
    // terlihat dan bisa dilepas. Melepas `from` mengembalikan periode ke nilai `period` di URL.
    ...(state.q !== "" ? [{ key: "q", label: `Search: ${state.q}`, remove: () => onChange({ q: "" }) }] : []),
    ...(state.from !== null
      ? [
          {
            key: "from",
            label: `Since ${fmtShortDate(parseLocalDate(state.from))}`,
            remove: () => onChange({ from: null }),
          },
        ]
      : []),
    ...state.actors.map((a) => ({
      key: `actor:${a}`,
      label: `Actor: ${a}`,
      remove: () => onChange((s) => ({ actors: s.actors.filter((x) => x !== a) })),
    })),
    ...state.ttps.map((t) => ({
      key: `ttp:${t}`,
      label: `Technique: ${t}`,
      remove: () => onChange((s) => ({ ttps: s.ttps.filter((x) => x !== t) })),
    })),
    ...(storyLabel !== null
      ? [{ key: "story", label: `Story: ${storyLabel}`, remove: () => onChange({ story: null }) }]
      : []),
  ];

  const rail = <AllRail state={state} onChange={onChange} />;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(360px,1fr)_minmax(520px,1.4fr)] xl:grid-cols-[236px_minmax(360px,1fr)_minmax(520px,1.4fr)]">
      {isXl ? (
        <div className="min-w-0">{rail}</div>
      ) : (
        <Disclosure title="Filters" className="min-w-0 lg:col-span-2">
          {rail}
        </Disclosure>
      )}
      <div className="min-w-0 space-y-3">
        {chips.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {chips.map((c) => (
              <LinkChip key={c.key} label={c.label} onRemove={c.remove} />
            ))}
          </div>
        )}
        <AllList
          state={state}
          onChange={onChange}
          selected={state.article}
          onSelect={(id) => onChange({ article: id })}
        />
      </div>
      <div className="min-w-0">
        <ArticleReader
          articleId={state.article}
          listArticles={listArticles}
          onStep={(id) => onChange({ article: id })}
        />
      </div>
    </div>
  );
}
