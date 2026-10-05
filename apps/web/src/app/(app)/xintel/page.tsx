"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { TweetList } from "@/components/xintel/tweet-list";
import { MonitoredAccounts } from "@/components/xintel/monitored-accounts";

const SUB_TABS = [
  { id: "tweets", label: "Tweets" },
  { id: "accounts", label: "Monitored Accounts" },
] as const;

type SubTab = (typeof SUB_TABS)[number]["id"];

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
      <div className="mb-4 flex gap-1.5 border-b border-border pb-3 overflow-x-auto">
        {SUB_TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              tab === t.id
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "tweets" ? <TweetList /> : <MonitoredAccounts />}
    </div>
  );
}
