"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { TaGroupsPanel } from "@/components/intelligence/threat-actor-room/ta-groups-panel";
import { TaWhitelistPanel } from "@/components/intelligence/threat-actor-room/ta-whitelist-panel";
import { TaWatchlistPanel } from "@/components/intelligence/threat-actor-room/ta-watchlist-panel";
import type { TaStats } from "@/lib/api/loose-types";

const TABS = [
  { value: "tracked", label: "Tracked Groups" },
  { value: "whitelist", label: "Whitelist" },
  { value: "watchlist", label: "Watchlist" },
] as const;
type Tab = (typeof TABS)[number]["value"];

/** Port sub-view `threatroom` (`intel.js`, 3 sub-tab: Tracked/Whitelist/
 * Watchlist -- `taSwitchView()` `ta.js:207-224`). Render cuma tab aktif
 * (sama pola kayak ATT&CK DB G3), gak nembak query 3 tab bareng. */
export function ThreatActorRoomView() {
  const [tab, setTab] = useState<Tab>("tracked");

  const statsQuery = useQuery({
    queryKey: ["ta-room", "ta-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/ta/stats");
      if (error) throw error;
      return data as unknown as TaStats;
    },
  });

  return (
    <div>
      {statsQuery.data && (
        <div className="mb-4 flex flex-wrap gap-3 border-b border-border pb-3">
          <StatCard label="Total Groups" value={statsQuery.data.total_groups} />
          <StatCard label="Whitelisted" value={statsQuery.data.total_whitelisted} />
          <StatCard label="Manual Additions" value={statsQuery.data.manual_count} />
          <StatCard label="Covered in News" value={statsQuery.data.in_news_count} />
        </div>
      )}

      <div className="mb-4 flex gap-1.5 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              tab === t.value ? "border-primary/30 bg-primary/10 text-primary" : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "tracked" && <TaGroupsPanel />}
      {tab === "whitelist" && <TaWhitelistPanel />}
      {tab === "watchlist" && <TaWatchlistPanel />}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border bg-background px-3 py-2">
      <div className="text-sm font-semibold text-muted-foreground">{label}</div>
      <div className="text-lg font-bold text-foreground">{value}</div>
    </div>
  );
}
