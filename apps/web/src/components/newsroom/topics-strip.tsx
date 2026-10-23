"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { NewsroomFilters } from "@/lib/newsroom/filters";
import { Skeleton } from "@/components/ui/skeleton";

type Topic = components["schemas"]["TopicOut"];

function MiniBars({ daily }: { daily: number[] }) {
  const bars = daily.slice(-7);
  const max = Math.max(1, ...bars);
  return (
    <div className="flex h-8 items-end gap-0.5" aria-hidden="true">
      {bars.map((v, i) => (
        <span
          key={i}
          className="flex-1 rounded-sm bg-primary/75"
          style={{ height: `${Math.max(v > 0 ? 8 : 2, (v / max) * 100)}%` }}
        />
      ))}
    </div>
  );
}

/** Topik aktif (aktor/TTP yang sedang naik). Bagian ini selalu tampil: skeleton saat memuat,
 * pesan saat gagal atau kosong (spec bagian 6), supaya analis tahu "tidak ada yang naik"
 * berbeda dengan "belum dimuat". */
export function TopicsStrip({
  filters,
  onOpen,
}: {
  filters: NewsroomFilters;
  onOpen: (t: { actor: string } | { ttp: string }, title: string) => void;
}) {
  const params = {
    posted_on_start: filters.dateStart || undefined,
    country: filters.country ? [filters.country] : undefined,
    search: filters.search || undefined,
    confirmed_only: filters.incidentOnly || undefined,
    limit: 4,
  };
  const { data, isPending, isError } = useQuery({
    queryKey: ["newsroom", "topics", params],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/newsroom/topics", { params: { query: params } });
      if (error) throw error;
      return data;
    },
  });

  function open(t: Topic) {
    if (t.kind === "ttp") onOpen({ ttp: t.ttp_id ?? t.name }, [t.ttp_id, t.name].filter(Boolean).join(" "));
    else onOpen({ actor: t.name }, t.name);
  }

  return (
    <section aria-label="Topik aktif" className="mb-8">
      <h2 className="mb-3 text-xs tracking-widest text-primary-text uppercase">
        Topik aktif
        {data && <span className="ml-2 text-muted-foreground normal-case">{data.window_label}</span>}
      </h2>
      {isPending && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(230px,1fr))] gap-3" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-lg" />
          ))}
        </div>
      )}
      {isError && <p className="text-sm text-muted-foreground">Gagal memuat topik aktif.</p>}
      {data && data.items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Belum ada aktor atau TTP yang naik di atas ambang pada periode ini.
        </p>
      )}
      {data && data.items.length > 0 && (
        <ul className="grid grid-cols-[repeat(auto-fit,minmax(230px,1fr))] gap-3">
          {data.items.map((t) => (
            <li key={`${t.kind}-${t.ttp_id ?? t.name}`}>
              <button
                type="button"
                onClick={() => open(t)}
                className="flex h-full w-full flex-col gap-2 rounded-lg border border-border bg-card p-3 text-left hover:bg-muted focus-visible:ring-3 focus-visible:ring-focus focus-visible:outline-none"
              >
                <span className="flex items-center justify-between text-[11px] text-muted-foreground">
                  <span>{t.kind === "ttp" ? "TTP" : "Threat actor"}</span>
                  <span className="font-semibold text-primary-text">
                    {t.is_new ? "baru" : t.change_pct != null ? `+${t.change_pct}%` : ""}
                  </span>
                </span>
                <span className="text-[15px] leading-snug font-semibold">
                  {t.kind === "ttp" ? (
                    <>
                      <span className="font-code">{t.ttp_id}</span> {t.name}
                    </>
                  ) : (
                    t.name
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  {t.count} artikel{t.top_countries.length > 0 && ` · ${t.top_countries.join(", ")}`}
                </span>
                <MiniBars daily={t.daily} />
                {t.latest_article && (
                  <span className="line-clamp-2 text-xs text-foreground">{t.latest_article.title}</span>
                )}
                <span className="mt-auto text-xs font-medium text-primary-text">{t.count} artikel →</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
