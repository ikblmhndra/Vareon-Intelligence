"use client";

import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/page-header";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { FeedStatusChip } from "@/components/xintel/feed-status-chip";
import { useAccounts } from "@/components/xintel/monitored-accounts";
import { api } from "@/lib/api/client";
import { isClientError } from "@/lib/exec/query";

export type XIntelTab = "tweets" | "accounts";

/** Total tweet tanpa filter untuk label tab (`page_size=1` cukup, hanya `total` yang dibaca). */
function useTweetsTotal() {
  return useQuery({
    queryKey: ["xintel", "tweets-total"],
    retry: (n, e) => n < 2 && !isClientError(e),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/tweets", {
        params: { query: { page: 1, page_size: 1, apac_only: false, ot_only: false, confirmed_only: false, has_cve: false } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return data?.total ?? 0;
    },
  });
}

export function XIntelPageHeader({ tab, onTabChange }: { tab: XIntelTab; onTabChange: (t: XIntelTab) => void }) {
  const total = useTweetsTotal();
  const accounts = useAccounts();
  const tweets = tab === "tweets";

  return (
    <>
      <PageHeader
        kicker="SOCIAL SIGNALS"
        title={tweets ? "X Intel" : "Monitored accounts"}
        description={
          tweets
            ? "Posts from monitored researchers and leak-watchers, classified for incidents, CVEs and APAC relevance"
            : "The handles the X collector reads. Deactivating keeps the history; removing deletes the account from the list but keeps its posts."
        }
        actions={tweets ? <FeedStatusChip /> : undefined}
        className="mb-2"
      />
      <UnderlineTabs
        aria-label="X Intel views"
        className="mb-5"
        value={tab}
        onChange={onTabChange}
        items={[
          { value: "tweets", label: "Tweets", count: total.data },
          { value: "accounts", label: "Monitored Accounts", count: accounts.data?.length },
        ]}
      />
    </>
  );
}
