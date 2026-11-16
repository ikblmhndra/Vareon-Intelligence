"use client";

import { useState } from "react";

import type { components } from "@/lib/api/schema";
import { Button } from "@/components/ui/button";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { TweetCard } from "@/components/xintel/tweet-card";
import { TweetDetailDialog } from "@/components/xintel/tweet-detail-dialog";
import { XIntelRail } from "@/components/xintel/xintel-rail";
import { isDefault, type XIntelFilters } from "@/lib/xintel/filters";
import { PAGE_SIZE, useTweetStats, useTweets } from "@/lib/xintel/queries";

type Tweet = components["schemas"]["TweetOut"];

/** Kolom feed + rail. Daftar dan rail memakai param yang sama (`toQuery`), jadi angkanya selalu sepakat. */
export function TweetList({
  filters,
  anchor,
  onSearchHandle,
  onClear,
}: {
  filters: XIntelFilters;
  anchor: number;
  onSearchHandle: (handle: string) => void;
  onClear: () => void;
}) {
  const [page, setPage] = useState(1);
  const [prev, setPrev] = useState({ filters, anchor });
  const [selected, setSelected] = useState<Tweet | null>(null);
  // Filter atau anchor berubah: kembali ke halaman 1 (disetel saat render, tanpa efek tambahan).
  if (prev.filters !== filters || prev.anchor !== anchor) {
    setPrev({ filters, anchor });
    setPage(1);
  }

  const tweets = useTweets(filters, anchor, page);
  const stats = useTweetStats(filters, anchor);
  const total = tweets.data?.total ?? 0;
  const from = (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, total);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_432px]">
      <div>
        {tweets.isPending && (
          <div className="flex flex-col gap-3" role="status" aria-label="Loading posts">
            <Skeleton className="h-36 w-full rounded-2xl" />
            <Skeleton className="h-36 w-full rounded-2xl" />
            <Skeleton className="h-36 w-full rounded-2xl" />
          </div>
        )}
        {tweets.isError && (
          <StatePanel
            variant="error"
            title="Failed to load posts"
            description="The request did not complete. Try again."
            action={
              <Button variant="outline" onClick={() => void tweets.refetch()}>
                Retry
              </Button>
            }
          />
        )}
        {tweets.data && tweets.data.tweets.length === 0 && (
          <StatePanel
            variant="empty"
            title={isDefault(filters) ? "No posts collected yet" : "No posts match these filters"}
            action={
              isDefault(filters) ? undefined : (
                <Button variant="outline" onClick={onClear}>
                  Clear filters
                </Button>
              )
            }
          />
        )}
        {tweets.data && tweets.data.tweets.length > 0 && (
          <>
            <div className="flex flex-col gap-3">
              {tweets.data.tweets.map((t) => (
                <TweetCard key={t.id} tweet={t} onOpen={() => setSelected(t)} />
              ))}
            </div>
            <NumberedPager
              page={page}
              totalPages={Math.ceil(total / PAGE_SIZE)}
              onPageChange={setPage}
              summary={`Showing ${from}-${to} of ${total}`}
            />
          </>
        )}
      </div>

      {stats.isError ? (
        <StatePanel variant="error" title="Failed to load counters" action={<Button variant="outline" onClick={() => void stats.refetch()}>Retry</Button>} />
      ) : (
        <XIntelRail stats={stats.data} filters={filters} onPickAccount={onSearchHandle} />
      )}

      <TweetDetailDialog key={selected?.id} tweet={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}
