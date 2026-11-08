"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, Plus, Search, TrendingDown, TrendingUp } from "lucide-react";
import { toast } from "sonner";

import { AttackSyncCard } from "@/components/entities/attack-sync-card";
import { otherAliases } from "@/components/entities/entity-action-utils";
import { EntityChip } from "@/components/entities/entity-chip";
import { EntityCreateDialog } from "@/components/entities/entity-create-dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { TabPills } from "@/components/ui/tab-pills";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { getActiveClientId } from "@/lib/auth/client-id";
import { useCan } from "@/lib/auth/permissions";
import { relativeTime } from "@/lib/cve/freshness";
import { ENTITY_TABS } from "@/lib/entities/types";
import { cn } from "@/lib/utils";

type EntityListItem = components["schemas"]["EntityListItem"];

const PAGE_SIZE = 50;

/** Tren 30 hari vs rata-rata bulanan dari 90 hari: naik/turun bila selisih >= 10 %, selain itu datar. */
function trend(m30: number, m90: number): { dir: "up" | "down" | null; pct: number | null } {
  const avg = m90 / 3;
  if (avg === 0) return { dir: m30 > 0 ? "up" : null, pct: null };
  const ratio = m30 / avg;
  const pct = Math.round((ratio - 1) * 100);
  if (ratio >= 1.1) return { dir: "up", pct };
  if (ratio <= 0.9) return { dir: "down", pct };
  return { dir: null, pct };
}

function Mentions30({ item }: { item: EntityListItem }) {
  const t = trend(item.mentions_30d, item.mentions_90d);
  return (
    <span className="inline-flex items-center gap-1">
      <b className="font-semibold text-foreground">{item.mentions_30d}</b>
      {t.dir === "up" && (
        <span className="inline-flex items-center gap-0.5 text-xs text-success-text">
          <TrendingUp aria-hidden className="size-3.5" />
          <span className="sr-only">Up</span>
          {t.pct != null && `+${t.pct}%`}
        </span>
      )}
      {t.dir === "down" && (
        <span className="inline-flex items-center gap-0.5 text-xs text-destructive-text">
          <TrendingDown aria-hidden className="size-3.5" />
          <span className="sr-only">Down</span>
          {t.pct != null && `−${Math.abs(t.pct)}%`}
        </span>
      )}
    </span>
  );
}

function Aliases({ item }: { item: { name: string; external_id?: string | null; aliases: string[] } }) {
  const aliases = otherAliases(item.aliases, item.name, item.external_id);
  if (aliases.length === 0) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {aliases.slice(0, 3).map((a) => (
        <span key={a} className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground">
          {a}
        </span>
      ))}
      {aliases.length > 3 && (
        <span className="text-xs text-muted-foreground">+{aliases.length - 3}</span>
      )}
    </div>
  );
}

function WatchButton({
  item,
  onToggle,
  busy,
}: {
  item: EntityListItem;
  onToggle: (item: EntityListItem) => void;
  busy: boolean;
}) {
  return (
    <Button
      size="sm"
      variant={item.watched ? "default" : "outline"}
      aria-pressed={item.watched}
      aria-label={`${item.watched ? "Stop watching" : "Watch"} ${item.name}`}
      disabled={busy}
      onClick={() => onToggle(item)}
      className="max-sm:h-11"
    >
      <Eye aria-hidden />
      {item.watched ? "Watching" : "Watch"}
    </Button>
  );
}

/**
 * Daftar entity (P7c): satu halaman untuk semua tipe, tab per tipe. State di URL (`tab`, `q`,
 * `watched=1`, `suppressed=1`) supaya bisa di-bookmark; `?new=1&type=&name=` membuka dialog buat
 * entity (dipakai halaman resolve untuk nama yang belum punya entity). Menggantikan Threat Actor
 * Room dan ATT&CK DB.
 */
export function EntitiesListView() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const can = useCan();

  const tabKey = ENTITY_TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "actors";
  const tab = ENTITY_TABS.find((t) => t.key === tabKey)!;
  const q = params.get("q") ?? "";
  const watchedOnly = params.get("watched") === "1";
  const includeSuppressed = params.get("suppressed") === "1" && can("manage_entities");
  const creating = params.get("new") === "1";

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v == null || v === "") next.delete(k);
        else next.set(k, v);
      }
      router.replace(`/intelligence/entities?${next}`, { scroll: false });
    },
    [params, router],
  );

  // Kotak cari: state lokal, ditulis ke URL setelah 300 ms tanpa ketikan.
  const [qInput, setQInput] = useState(q);
  useEffect(() => {
    if (qInput === q) return;
    const t = setTimeout(() => setParams({ q: qInput }), 300);
    return () => clearTimeout(t);
  }, [qInput, q, setParams]);

  const list = useInfiniteQuery({
    queryKey: ["entities", "list", tabKey, q, watchedOnly, includeSuppressed],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const { data, error, response } = await api.GET("/api/entities", {
        params: {
          query: {
            type: tab.types.join(","),
            identity_class: tab.identityClass ?? undefined,
            q: q || undefined,
            watched: watchedOnly || undefined,
            include_suppressed: includeSuppressed || undefined,
            cursor: pageParam ?? undefined,
            limit: PAGE_SIZE,
          },
        },
      });
      if (error || !data) throw new Error("Failed to load entities", { cause: response.status });
      return data;
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];

  const [busyId, setBusyId] = useState<number | null>(null);
  async function toggleWatch(item: EntityListItem) {
    setBusyId(item.id);
    try {
      const path = { params: { path: { entity_id: item.id } } };
      const { error } = item.watched
        ? await api.DELETE("/api/entities/{entity_id}/watch", path)
        : await api.PUT("/api/entities/{entity_id}/watch", path);
      if (error) throw new Error("request failed");
      await queryClient.invalidateQueries({ queryKey: ["entities"] });
    } catch (e) {
      toast.error(`Could not update watch: ${(e as Error).message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function downloadLayer() {
    try {
      const clientId = getActiveClientId();
      const resp = await fetch(
        "/api/proxy/api/ta/watchlist/navigator-layer",
        clientId ? { headers: { "X-Client-ID": clientId } } : undefined,
      );
      if (!resp.ok) throw new Error(await resp.text());
      const blob = await resp.blob();
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = "watchlist-navigator-layer.json";
      anchor.click();
      URL.revokeObjectURL(anchor.href);
    } catch (e) {
      toast.error(`Download failed: ${(e as Error).message}`);
    }
  }

  const tabItems = ENTITY_TABS.map((t) => ({ value: t.key, label: t.label }));
  const singular = tab.label;

  return (
    <div className="space-y-4">
      <TabPills
        aria-label="Entity types"
        items={tabItems}
        value={tabKey}
        onChange={(v) => setParams({ tab: v })}
      />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-search" className="text-sm font-medium text-muted-foreground">
              Search name or alias
            </Label>
            <div className="relative">
              <Search
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                id="entity-search"
                value={qInput}
                onChange={(e) => setQInput(e.target.value)}
                placeholder={`Search ${singular.toLowerCase()}…`}
                className="w-64 pl-8 text-xs max-sm:h-11 max-sm:w-full"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span id="entity-show-label" className="text-sm font-medium text-muted-foreground">
              Show
            </span>
            <div role="group" aria-labelledby="entity-show-label" className="flex gap-1.5">
              <Button
                size="sm"
                variant={watchedOnly ? "outline" : "default"}
                aria-pressed={!watchedOnly}
                onClick={() => setParams({ watched: null })}
                className="max-sm:h-11"
              >
                All
              </Button>
              <Button
                size="sm"
                variant={watchedOnly ? "default" : "outline"}
                aria-pressed={watchedOnly}
                onClick={() => setParams({ watched: "1" })}
                className="max-sm:h-11"
              >
                Watched
              </Button>
            </div>
          </div>
          {can("manage_entities") && (
          <div className="flex h-8 items-center gap-2 max-sm:h-11">
            <Checkbox
              id="entity-suppressed"
              checked={includeSuppressed}
              onCheckedChange={(c) => setParams({ suppressed: c ? "1" : null })}
            />
            <Label htmlFor="entity-suppressed" className="text-sm text-foreground">
              Include suppressed
            </Label>
          </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {tabKey === "actors" && (
            <Button variant="outline" onClick={() => void downloadLayer()} className="max-sm:h-11">
              <Download aria-hidden />
              Watchlist Navigator layer
            </Button>
          )}
          {can("manage_entities") && (
            <Button
              onClick={() => setParams({ new: "1", type: tab.types[0], name: null })}
              className="max-sm:h-11"
            >
              <Plus aria-hidden />
              New entity
            </Button>
          )}
        </div>
      </div>

      {tabKey === "techniques" && can("manage_intel") && <AttackSyncCard />}

      <section aria-label={`${singular} list`} className="rounded-2xl surface-raised">
        {list.isPending && (
          <div className="space-y-2 p-4" role="status" aria-label="Loading entities">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        )}
        {list.isError && (
          <p role="alert" className="p-4 text-sm text-destructive-text">
            {list.error instanceof Error && list.error.cause === 403
              ? "You don't have access to entity pages."
              : "Failed to load entities."}
          </p>
        )}
        {list.isSuccess && items.length === 0 && (
          <p className="p-6 text-center text-sm text-muted-foreground">
            No {singular.toLowerCase()} match these filters.
          </p>
        )}
        {items.length > 0 && (
          <>
            {/* >= 640 px: tabel; di bawahnya jadi kartu supaya halaman tidak scroll horizontal. */}
            <div className="max-sm:hidden">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Also known as</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead className="text-right">Mentions 30 d</TableHead>
                    <TableHead className="text-right">90 d</TableHead>
                    <TableHead>Last seen</TableHead>
                    <TableHead className="text-right">
                      <span className="sr-only">Watch</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((it) => (
                    <TableRow key={it.id} className={cn(it.suppressed && "text-muted-foreground")}>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          <EntityChip type={it.type} name={it.name} id={it.id} />
                          {it.external_id && (
                            <span className="font-code text-xs text-muted-foreground">
                              {it.external_id}
                            </span>
                          )}
                          {it.suppressed && (
                            <span className="rounded-md bg-muted px-1.5 py-0.5 text-2xs">Suppressed</span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Aliases item={it} />
                      </TableCell>
                      <TableCell>
                        <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs">{it.source}</span>
                      </TableCell>
                      <TableCell className="text-right">
                        <Mentions30 item={it} />
                      </TableCell>
                      <TableCell className="text-right">{it.mentions_90d}</TableCell>
                      <TableCell className="text-xs whitespace-nowrap">
                        {it.last_seen ? relativeTime(it.last_seen) : "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        {can("manage_pir") && (
                          <WatchButton item={it} onToggle={toggleWatch} busy={busyId === it.id} />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <ul className="divide-y divide-border sm:hidden">
              {items.map((it) => (
                <li key={it.id} className="space-y-2 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <EntityChip type={it.type} name={it.name} id={it.id} />
                    {it.external_id && (
                      <span className="font-code text-xs text-muted-foreground">{it.external_id}</span>
                    )}
                    {it.suppressed && (
                      <span className="rounded-md bg-muted px-1.5 py-0.5 text-2xs">Suppressed</span>
                    )}
                  </div>
                  <Aliases item={it} />
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span className="rounded-md bg-muted px-1.5 py-0.5">{it.source}</span>
                    <span>
                      30 d <Mentions30 item={it} />
                    </span>
                    <span>90 d {it.mentions_90d}</span>
                    <span>{it.last_seen ? relativeTime(it.last_seen) : "—"}</span>
                  </div>
                  {can("manage_pir") && (
                    <WatchButton item={it} onToggle={toggleWatch} busy={busyId === it.id} />
                  )}
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-3 text-xs text-muted-foreground">
              <span>Trend = 30 d compared with the 90 d monthly average</span>
              {list.hasNextPage && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={list.isFetchingNextPage}
                  onClick={() => void list.fetchNextPage()}
                  className="max-sm:h-11"
                >
                  {list.isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              )}
            </div>
          </>
        )}
      </section>

      <EntityCreateDialog
        key={creating ? `new-${params.get("type")}-${params.get("name")}` : "closed"}
        open={creating && can("manage_entities")}
        onClose={() => setParams({ new: null, type: null, name: null })}
        initialType={params.get("type") ?? tab.types[0]}
        initialName={params.get("name") ?? ""}
      />
    </div>
  );
}
