"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontalIcon, Plus, TrendingDown, TrendingUp } from "lucide-react";
import { toast } from "sonner";

import { otherAliases } from "@/components/entities/entity-action-utils";
import { EntityChip } from "@/components/entities/entity-chip";
import { EntityCreateDialog } from "@/components/entities/entity-create-dialog";
import { EntityPreviewPanel } from "@/components/entities/entity-preview-panel";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { MasterDetail } from "@/components/ui/master-detail";
import { Notice } from "@/components/ui/notice";
import { SearchInput } from "@/components/ui/search-input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { StarToggle } from "@/components/ui/star-toggle";
import { StatePanel } from "@/components/ui/state-panel";
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
import { ENTITY_TABS, entityTypeMeta } from "@/lib/entities/types";
import { fmtAgo } from "@/lib/format";
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
      {aliases.slice(0, 2).map((a) => (
        <span key={a} className="rounded-md bg-muted px-1.5 py-0.5 text-xs text-foreground">
          {a}
        </span>
      ))}
      {aliases.length > 2 && (
        <span className="text-xs text-muted-foreground">+{aliases.length - 2}</span>
      )}
    </div>
  );
}

/**
 * Daftar entity (P7c, desain 2b 6.7): tab per tipe + "All", urut 30 hari terbanyak (C6), baris terpilih
 * tampil di panel pratinjau. State di URL (`tab`, `q`, `watched=1`, `suppressed=1`, `id`) supaya bisa
 * di-bookmark; `?new=1&type=&name=` membuka dialog buat entity (dipakai halaman resolve untuk nama yang
 * belum punya entity). Hanya halaman ini yang mengirim `sort=mentions`; picker dan dialog tetap urut nama.
 */
export function EntitiesListView() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const can = useCan();

  const tabKey = ENTITY_TABS.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "all";
  const tab = ENTITY_TABS.find((t) => t.key === tabKey)!;
  const q = params.get("q") ?? "";
  const watchedOnly = params.get("watched") === "1";
  const includeSuppressed = params.get("suppressed") === "1" && can("manage_entities");
  const creating = params.get("new") === "1";
  const idParam = Number(params.get("id"));

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

  // Kotak cari: state lokal, ditulis ke URL setelah 300 ms tanpa ketikan; pilihan baris dilepas
  // supaya baris pertama hasil baru jadi default.
  const [qInput, setQInput] = useState(q);
  useEffect(() => {
    if (qInput === q) return;
    const t = setTimeout(() => setParams({ q: qInput, id: null }), 300);
    return () => clearTimeout(t);
  }, [qInput, q, setParams]);

  const list = useInfiniteQuery({
    queryKey: ["entities", "list", tabKey, q, watchedOnly, includeSuppressed, "mentions"],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const { data, error, response } = await api.GET("/api/entities", {
        params: {
          query: {
            type: tab.types.length ? tab.types.join(",") : undefined,
            identity_class: tab.identityClass ?? undefined,
            q: q || undefined,
            watched: watchedOnly || undefined,
            include_suppressed: includeSuppressed || undefined,
            // Kursor bergantung pada `sort`: selalu kirim sort yang sama dengan halaman pertama.
            sort: "mentions",
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
  // `total` hanya terisi di halaman pertama (null saat ada kursor), jadi diambil dari sana.
  const total = list.data?.pages[0]?.total ?? items.length;
  const selected = items.find((i) => i.id === idParam) ?? items[0] ?? null;
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  function select(item: EntityListItem) {
    setParams({ id: String(item.id) });
  }

  // Satu tab stop untuk tabel (baris terpilih); panah memindahkan pilihan, Enter membuka halaman entity.
  // Hanya bila fokus di baris itu sendiri: tautan nama dan bintang punya Enter sendiri.
  function onRowKey(e: KeyboardEvent<HTMLTableRowElement>, index: number) {
    if (e.target !== e.currentTarget) return;
    if (e.key === "Enter") {
      e.preventDefault();
      router.push(`/intelligence/entities/${items[index].id}`);
      return;
    }
    let next: number;
    if (e.key === "ArrowDown") next = Math.min(items.length - 1, index + 1);
    else if (e.key === "ArrowUp") next = Math.max(0, index - 1);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    select(items[next]);
    rowRefs.current.get(items[next].id)?.focus();
  }

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

  const tabOptions = ENTITY_TABS.map((t) => ({ value: t.key, label: t.label }));
  const allTab = tabKey === "all";
  const starFor = (it: EntityListItem) => (
    <StarToggle
      on={it.watched}
      name={it.name}
      onToggle={can("manage_pir") ? () => void toggleWatch(it) : undefined}
      disabled={busyId === it.id}
    />
  );

  let body;
  if (list.isPending) body = <StatePanel variant="loading" title="Loading entities" className="m-4" />;
  else if (list.isError)
    body =
      list.error instanceof Error && list.error.cause === 403 ? (
        <StatePanel variant="no-access" title="You don't have access to entity pages." className="m-4" />
      ) : (
        <StatePanel
          variant="error"
          title="Failed to load entities."
          className="m-4"
          action={
            <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
              Retry
            </Button>
          }
        />
      );
  else if (items.length === 0) {
    // kata benda jamak per tab: "All" -> "entities", "CVEs" tetap huruf besar (bukan "No all"/"No cves")
    const noun = allTab ? "entities" : tab.key === "vulnerabilities" ? "CVEs" : tab.label.toLowerCase();
    const filtered = Boolean(q) || watchedOnly;
    body = (
      <StatePanel
        variant="empty"
        title={filtered ? `No ${noun} match these filters` : `No ${noun} yet`}
        description={filtered ? "Clear the search or turn off Watched only to see more." : undefined}
        className="m-4"
      />
    );
  } else
    body = (
      <>
        {/* >= 640 px: tabel; di bawahnya jadi kartu supaya halaman tidak scroll horizontal (D28). */}
        <div className="max-sm:hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-5">Name</TableHead>
                <TableHead>ATT&amp;CK ID</TableHead>
                <TableHead>Aliases</TableHead>
                <TableHead className="text-right">30 d</TableHead>
                <TableHead className="text-right">90 d</TableHead>
                <TableHead className={cn(!allTab && "pr-5")}>Last seen</TableHead>
                {allTab && <TableHead className="pr-5">Type</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it, i) => {
                const isSel = it.id === selected?.id;
                return (
                  <TableRow
                    key={it.id}
                    ref={(el: HTMLTableRowElement | null) => {
                      if (el) rowRefs.current.set(it.id, el);
                      else rowRefs.current.delete(it.id);
                    }}
                    selected={isSel}
                    tabIndex={isSel ? 0 : -1}
                    aria-current={isSel ? "true" : undefined}
                    onClick={() => select(it)}
                    onKeyDown={(e) => onRowKey(e, i)}
                    className={cn(
                      "cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                      it.suppressed && "text-muted-foreground",
                    )}
                  >
                    <TableCell className="pl-5">
                      <div className="flex flex-wrap items-center gap-2">
                        {starFor(it)}
                        <EntityChip type={it.type} name={it.name} id={it.id} />
                        {it.suppressed && (
                          <span className="rounded-md bg-muted px-1.5 py-0.5 text-2xs">Suppressed</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-code text-xs text-primary-text">{it.external_id ?? "—"}</TableCell>
                    <TableCell>
                      <Aliases item={it} />
                    </TableCell>
                    <TableCell className="text-right">
                      <Mentions30 item={it} />
                    </TableCell>
                    <TableCell className="text-right">{it.mentions_90d}</TableCell>
                    <TableCell className={cn("text-xs whitespace-nowrap", !allTab && "pr-5")}>
                      {it.last_seen ? fmtAgo(it.last_seen) : "—"}
                    </TableCell>
                    {allTab && (
                      <TableCell className="pr-5 text-xs whitespace-nowrap">
                        {entityTypeMeta(it.type).label}
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        <ul className="divide-y divide-border sm:hidden">
          {items.map((it) => (
            <li key={it.id} className="space-y-2 p-3">
              <div className="flex flex-wrap items-center gap-2">
                {starFor(it)}
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
                {allTab && <span>{entityTypeMeta(it.type).label}</span>}
                <span>
                  30 d <Mentions30 item={it} />
                </span>
                <span>90 d {it.mentions_90d}</span>
                <span>{it.last_seen ? fmtAgo(it.last_seen) : "—"}</span>
              </div>
            </li>
          ))}
        </ul>
        <div className="px-5 pb-4">
          <LoadMoreFooter
            shown={items.length}
            total={total}
            hasMore={!!list.hasNextPage}
            loading={list.isFetchingNextPage}
            onLoadMore={() => void list.fetchNextPage()}
          />
          <p className="pt-1 text-2xs text-muted-foreground">
            Trend = 30 d compared with the 90 d monthly average
          </p>
        </div>
      </>
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput
          className="w-72 max-sm:w-full"
          value={qInput}
          onChange={setQInput}
          placeholder="Search name, alias or ATT&CK ID"
          aria-label="Search entities by name, alias or ATT&CK ID"
        />
        <div className="max-w-full overflow-x-auto">
          <SegmentedControl
            aria-label="Entity types"
            size="sm"
            options={tabOptions}
            value={tabKey}
            onChange={(v) => setParams({ tab: v, id: null })}
          />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant={watchedOnly ? "default" : "outline"}
            size="sm"
            aria-pressed={watchedOnly}
            onClick={() => setParams({ watched: watchedOnly ? null : "1", id: null })}
            className="max-sm:h-11"
          >
            Watched only
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={<Button variant="outline" size="icon-sm" aria-label="More entity actions" />}
            >
              <MoreHorizontalIcon aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {can("manage_entities") && (
                <DropdownMenuCheckboxItem
                  checked={includeSuppressed}
                  onCheckedChange={(c) => setParams({ suppressed: c ? "1" : null, id: null })}
                >
                  Include suppressed
                </DropdownMenuCheckboxItem>
              )}
              <DropdownMenuItem onClick={() => void downloadLayer()}>
                Download watchlist Navigator layer
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          {can("manage_entities") && (
            <Button
              size="sm"
              onClick={() => setParams({ new: "1", type: tab.types[0] ?? null, name: null })}
              className="max-sm:h-11"
            >
              <Plus aria-hidden />
              New entity
            </Button>
          )}
        </div>
      </div>

      {tabKey === "techniques" && (
        <Notice
          tone="info"
          title="ATT&CK sync status moved to MITRE heatmap"
          action={
            <Link
              href="/intelligence/mitre"
              className="rounded-sm text-xs font-medium text-primary-text underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Open MITRE heatmap
            </Link>
          }
        />
      )}

      <MasterDetail
        list={
          <section aria-label={`${tab.label} list`} className="rounded-lg surface-raised">
            <div className="px-5 pt-4 pb-2">
              <h2 className="font-heading text-base font-semibold">{tab.label}</h2>
              {list.isSuccess && (
                <p className="text-xs text-muted-foreground">
                  {total} {total === 1 ? "entity" : "entities"} · sorted by mentions (30 d)
                </p>
              )}
            </div>
            {body}
          </section>
        }
        detail={selected ? <div className="max-sm:hidden"><EntityPreviewPanel item={selected} /></div> : null}
      />

      <EntityCreateDialog
        key={creating ? `new-${params.get("type")}-${params.get("name")}` : "closed"}
        open={creating && can("manage_entities")}
        onClose={() => setParams({ new: null, type: null, name: null })}
        initialType={params.get("type") ?? tab.types[0] ?? "intrusion-set"}
        initialName={params.get("name") ?? ""}
      />
    </div>
  );
}
