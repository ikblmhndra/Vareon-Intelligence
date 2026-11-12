"use client";

import { Suspense, useCallback, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { MonitoredAccounts } from "@/components/xintel/monitored-accounts";
import { TweetList } from "@/components/xintel/tweet-list";
import { XIntelPageHeader, type XIntelTab } from "@/components/xintel/xintel-page-header";
import { XIntelToolbar } from "@/components/xintel/xintel-toolbar";
import { usePageTitle } from "@/lib/use-page-title";
import { DEFAULT_FILTERS, type XIntelFilters } from "@/lib/xintel/filters";
import { useTweetStats } from "@/lib/xintel/queries";

/**
 * Port `tab_xintel.html` + `xintel.js`. 𝕏 API balance chip (`GET /api/tweets/balance`) SENGAJA gak
 * diport -- backend-nya juga gak ada (keputusan Fase 7.3). Tab ada di URL (`?tab=`), filter dan
 * `anchor` (batas bawah periode preset) di state: anchor diset saat mount, ganti periode dan "Refresh",
 * tidak pernah dihitung di render, supaya query key stabil.
 */
function XIntelContent() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab: XIntelTab = params.get("tab") === "accounts" ? "accounts" : "tweets";
  usePageTitle(tab === "tweets" ? "X Intel" : "Monitored accounts");

  const [filters, setFilters] = useState<XIntelFilters>(DEFAULT_FILTERS);
  const [anchor, setAnchor] = useState(() => Date.now());

  const onFilters = useCallback(
    (next: XIntelFilters) => {
      if (next.period !== filters.period) setAnchor(Date.now());
      setFilters(next);
    },
    [filters.period],
  );
  const stats = useTweetStats(filters, anchor);

  return (
    <div>
      <XIntelPageHeader tab={tab} onTabChange={(t) => router.replace(`${pathname}?tab=${t}`)} />
      {tab === "tweets" ? (
        <>
          <XIntelToolbar
            value={filters}
            onChange={onFilters}
            total={stats.data?.total}
            confirmed={stats.data?.confirmed}
            onRefresh={() => setAnchor(Date.now())}
          />
          <TweetList />
        </>
      ) : (
        <MonitoredAccounts />
      )}
    </div>
  );
}

export default function XIntelPage() {
  return (
    <Suspense>
      <XIntelContent />
    </Suspense>
  );
}
