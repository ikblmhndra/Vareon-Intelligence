"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { SyncStatusCards } from "@/components/intelligence/attack-db/sync-status-cards";
import { TechniquesPanel } from "@/components/intelligence/attack-db/techniques-panel";
import { GroupsPanel } from "@/components/intelligence/attack-db/groups-panel";
import { SoftwarePanel } from "@/components/intelligence/attack-db/software-panel";
import { MitigationsPanel } from "@/components/intelligence/attack-db/mitigations-panel";
import { AttackDetailDialog, type DetailTarget } from "@/components/intelligence/attack-db/attack-detail-dialog";

const BROWSE_TABS = [
  { value: "techniques", label: "Techniques" },
  { value: "groups", label: "Groups" },
  { value: "software", label: "Software" },
  { value: "mitigations", label: "Mitigations" },
] as const;
type BrowseTab = (typeof BROWSE_TABS)[number]["value"];

/** Port `loadAttackDB()`/`_attackdbSetActiveTab()` (`attack_db.js:1-24,126-161`)
 * -- render CUMA panel aktif (bukan mount ke-4 sub-tab sekaligus, biar
 * gak nembak 4 query bareng), satu `AttackDetailDialog` dibagi ke 3
 * panel clickable (Mitigations gak punya detail, lihat komponennya). */
export function AttackDbView() {
  const [tab, setTab] = useState<BrowseTab>("techniques");
  const [detailTarget, setDetailTarget] = useState<DetailTarget>(null);

  return (
    <div>
      <SyncStatusCards />

      <div className="mb-4 flex gap-1.5 overflow-x-auto">
        {BROWSE_TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              tab === t.value
                ? "border-primary/30 bg-primary/10 text-primary-text"
                : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "techniques" && <TechniquesPanel onSelect={setDetailTarget} />}
      {tab === "groups" && <GroupsPanel onSelect={setDetailTarget} />}
      {tab === "software" && <SoftwarePanel onSelect={setDetailTarget} />}
      {tab === "mitigations" && <MitigationsPanel />}

      <AttackDetailDialog target={detailTarget} onNavigate={setDetailTarget} onClose={() => setDetailTarget(null)} />
    </div>
  );
}
