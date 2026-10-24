"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AttackDomainStatus, AttackSyncStartedResult } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";

const STATUS_COLOR: Record<string, string> = {
  success: "text-primary",
  error: "text-destructive",
  syncing: "text-warning",
  never: "text-muted-foreground",
};

function delta(val: number | null | undefined) {
  if (val == null || val === 0) return null;
  return (
    <span className={val > 0 ? "text-primary" : "text-destructive"}>
      {" "}
      {val > 0 ? "+" : ""}
      {val}
    </span>
  );
}

/** Port kartu sync status + polling (`attack_db.js:26-124`). Polling 5s
 * SELAMA ada domain berstatus "syncing" -- port apa adanya, bukan
 * polling terus-terusan. `POST /api/attack/sync`/`GET /sync/{key}`
 * butuh `require_admin` -- tombol tetep tampil ke semua (port apa
 * adanya, backend yang nolak 403 kalau bukan admin, sama asimetri
 * kayak monitored-accounts Grup C). */
export function SyncStatusCards() {
  const queryClient = useQueryClient();
  const canSync = useCan()("manage_intel");
  const [syncingAll, setSyncingAll] = useState(false);
  const [syncingDomain, setSyncingDomain] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const query = useQuery({
    queryKey: ["intelligence", "attack-status"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/status");
      if (error) throw error;
      return data as unknown as AttackDomainStatus[];
    },
  });

  const anySyncing = (query.data ?? []).some((d) => d.status === "syncing");

  useEffect(() => {
    if (anySyncing) {
      pollTimer.current = setTimeout(() => void query.refetch(), 5000);
    }
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anySyncing, query.dataUpdatedAt]);

  async function syncAll() {
    setSyncingAll(true);
    try {
      const { data, error } = await api.POST("/api/attack/sync", { body: {} });
      if (error) throw new Error(JSON.stringify(error));
      const d = data as unknown as AttackSyncStartedResult;
      toast.success(`Sync started for ${d.domains?.length ?? "all"} domain(s).`);
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: ["intelligence", "attack-status"] }), 2000);
    } catch (e) {
      toast.error(`Sync failed to start: ${(e as Error).message}`);
    } finally {
      setSyncingAll(false);
    }
  }

  async function syncDomain(key: string) {
    setSyncingDomain(key);
    try {
      const { error } = await api.GET("/api/attack/sync/{domain_key}", { params: { path: { domain_key: key } } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`Sync started for ${key}.`);
      void queryClient.invalidateQueries({ queryKey: ["intelligence", "attack-status"] });
    } catch (e) {
      toast.error(`Sync failed to start: ${(e as Error).message}`);
    } finally {
      setSyncingDomain(null);
    }
  }

  return (
    <div className="mb-4 border-b border-border pb-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-semibold text-muted-foreground">ATT&amp;CK Sync Status</p>
        {canSync && (
          <Button size="sm" variant="outline" disabled={syncingAll} onClick={() => void syncAll()}>
            {syncingAll ? "Syncing…" : "Sync All Domains"}
          </Button>
        )}
      </div>
      {query.isPending && <p className="text-xs text-muted-foreground">Loading sync status…</p>}
      {query.isError && <p className="text-xs text-destructive">Failed to load sync status</p>}
      <div className="flex flex-wrap gap-3">
        {query.data?.map((d) => (
          <div key={d.domain_key} className="min-w-[220px] flex-1 rounded-xl border border-border bg-background p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-mono text-xs font-bold text-foreground">{d.label || d.domain_key}</span>
              {canSync && (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-xs"
                  disabled={syncingDomain === d.domain_key}
                  onClick={() => void syncDomain(d.domain_key)}
                >
                  Sync
                </Button>
              )}
            </div>
            <div className={cn("mb-1.5 font-mono text-xs", STATUS_COLOR[d.status] ?? "text-muted-foreground")}>
              ● {d.status.toUpperCase()} · {d.version ? `v${d.version}` : "—"}
            </div>
            {d.status === "syncing" && d.phase && (
              <div className="mb-1 font-mono text-xs text-warning">
                {d.phase === "downloading" && d.bytes_downloaded
                  ? `↓ downloading ${(d.bytes_downloaded / 1024 / 1024).toFixed(1)}MB${d.bytes_total ? ` / ${(d.bytes_total / 1024 / 1024).toFixed(0)}MB` : ""} ${d.download_pct ?? ""}`
                  : `${d.phase}`}
              </div>
            )}
            <div className="font-mono text-xs leading-relaxed text-muted-foreground">
              MITRE updated: {d.mitre_modified ? new Date(d.mitre_modified).toLocaleDateString() : "—"}
              <br />
              Last sync: {d.last_sync ? new Date(d.last_sync).toLocaleDateString() : "Never"}
              <br />
              Techniques: {d.technique_count ?? "—"}
              {delta(d.delta_technique_count)} · Groups: {d.group_count ?? "—"}
              {delta(d.delta_group_count)}
              <br />
              Software: {d.software_count ?? "—"}
              {delta(d.delta_software_count)} · Mitigations: {d.mitigation_count ?? "—"}
              {delta(d.delta_mitigation_count)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
