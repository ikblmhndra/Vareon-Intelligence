"use client";

import { useState } from "react";

import { TabPills } from "@/components/ui/tab-pills";
import { FeedStatusBanner } from "@/components/xintel/feed-status-banner";
import { TweetList } from "@/components/xintel/tweet-list";
import { MonitoredAccounts } from "@/components/xintel/monitored-accounts";

const SUB_TABS = [
  { value: "tweets", label: "Tweets" },
  { value: "accounts", label: "Monitored Accounts" },
] as const;

type SubTab = (typeof SUB_TABS)[number]["value"];

/**
 * Port `tab_xintel.html` + `xintel.js`. 𝕏 API balance chip (`GET
 * /api/tweets/balance`) SENGAJA gak diport -- backend-nya juga gak ada,
 * `routers/tweets.py` bilang eksplisit "passthrough eksternal doang, gak
 * genting buat inti" (keputusan Fase 7.3, bukan keputusan baru di sini).
 */
export default function XIntelPage() {
  const [tab, setTab] = useState<SubTab>("tweets");

  return (
    <div>
      <FeedStatusBanner />
      <TabPills aria-label="X Intel views" className="mb-4 border-b border-border pb-3" items={SUB_TABS} value={tab} onChange={setTab} />

      {tab === "tweets" ? <TweetList /> : <MonitoredAccounts />}
    </div>
  );
}
