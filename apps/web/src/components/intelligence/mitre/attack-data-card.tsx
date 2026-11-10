"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { StatePanel } from "@/components/ui/state-panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/client";
import type { AttackDomainStatus, AttackSyncStartedResult } from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const STATUS_QUERY_KEY = ["intelligence", "attack-status"];

/** Kartu "ATT&CK data" (pindahan `AttackSyncCard` dari Entities, D27). Terbaca untuk semua pemegang
 * `view_intel`; tombol "Sync now" hanya `manage_intel`. Logika sync dan polling sama dengan kartu lama:
 * `POST /api/attack/sync` (semua domain), lalu poll 5 dtk SELAMA ada domain berstatus "syncing", bukan
 * polling terus-menerus. Sync per domain (GET `/sync/{key}`) sengaja tidak dibawa: mockup hanya punya satu
 * tombol dan "Sync now" sudah menyinkronkan semua domain. */
export function AttackDataCard() {
  const queryClient = useQueryClient();
  const canSync = useCan()("manage_intel");
  const [syncing, setSyncing] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const query = useQuery({
    queryKey: STATUS_QUERY_KEY,
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
    setSyncing(true);
    try {
      const { data, error } = await api.POST("/api/attack/sync", { body: {} });
      if (error) throw new Error(JSON.stringify(error));
      const d = data as unknown as AttackSyncStartedResult;
      toast.success(`Sync started for ${d.domains?.length ?? "all"} domain(s).`);
      setTimeout(() => void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY }), 2000);
    } catch (e) {
      toast.error(`Sync failed to start: ${(e as Error).message}`);
    } finally {
      setSyncing(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-col gap-3 px-5">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="font-heading text-base font-semibold">ATT&amp;CK data</h2>
            <p className="text-xs text-muted-foreground">Synced weekly from MITRE STIX</p>
          </div>
          {canSync && (
            <Button size="sm" variant="outline" disabled={syncing || anySyncing} onClick={() => void syncAll()}>
              {syncing || anySyncing ? "Syncing…" : "Sync now"}
            </Button>
          )}
        </div>

        {query.isPending && <StatePanel variant="loading" title="Loading sync status" className="py-8" />}
        {query.isError && <StatePanel variant="error" title="Failed to load sync status" className="py-8" />}

        {query.data && (
          <ul className="divide-y divide-border">
            {query.data.map((d) => (
              <DomainRow key={d.domain_key} d={d} />
            ))}
          </ul>
        )}

        <p className="text-2xs text-muted-foreground">
          Techniques not in the catalog show without a link to their entity page.
        </p>
      </div>
    </Card>
  );
}

function DomainRow({ d }: { d: AttackDomainStatus }) {
  const failed = d.status === "error";
  const busy = d.status === "syncing";
  const never = d.status === "never";
  const when = fmtShortDate(failed ? (d.last_attempted ?? d.last_sync) : d.last_sync);
  const status = failed ? `sync error ${when}` : busy ? "syncing…" : never ? "never synced" : when;
  const dot = failed || busy ? "bg-warning" : never ? "bg-muted-foreground" : "bg-success";

  const text = (
    <span className={cn("text-xs", failed ? "text-warning-text" : "text-muted-foreground")}>{status}</span>
  );

  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <span className="text-xs font-medium">{d.label || d.domain_key}</span>
      <span className="flex items-center gap-3">
        <span className="font-code text-xs text-muted-foreground">{d.version ? `v${d.version}` : "—"}</span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className={cn("size-2 rounded-full", dot)} />
          {failed && d.error ? (
            <Tooltip>
              <TooltipTrigger render={<span tabIndex={0} aria-label={`${status}: ${d.error}`} />}>
                {text}
              </TooltipTrigger>
              <TooltipContent>{d.error}</TooltipContent>
            </Tooltip>
          ) : (
            text
          )}
        </span>
      </span>
    </li>
  );
}
