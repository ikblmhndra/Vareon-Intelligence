"use client";

import { useState, type ReactNode } from "react";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { FilterSelect } from "@/components/ui/filter-select";
import { LoadMoreFooter } from "@/components/ui/load-more-footer";
import { MasterDetail } from "@/components/ui/master-detail";
import { SearchInput } from "@/components/ui/search-input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import {
  useDebounced,
  useHideFamily,
  useMonitorActions,
  type CatalogFamily,
  type CatalogVendor,
  type TechStackOut,
} from "@/lib/cve/catalog";
import { fmtCompactAge } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;
const MIN_QUERY = 2;
const FETCH_ALL = 500;

type Mode = "vendors" | "products";
type Show = "with_cves" | "all";

const SHOW_OPTIONS = [
  { value: "with_cves", label: "with CVEs" },
  { value: "all", label: "all" },
] as const;

const LINK =
  "rounded-sm text-xs font-semibold underline outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:text-muted-foreground";

function ActionLink({
  children,
  onClick,
  disabled,
  danger,
  "aria-label": ariaLabel,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  "aria-label": string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn(LINK, danger ? "text-destructive-text" : "text-foreground")}
    >
      {children}
    </button>
  );
}

/** Nama entri techstack per id (untuk "MONITORED {nama entri}"); daftar yang sama dengan tab Monitored Tech. */
function useEntryNames(): ReadonlyMap<number, string> {
  const q = useQuery({
    queryKey: ["techstack", "list", "all"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack", {
        params: { query: { page: 1, page_size: FETCH_ALL, sort_by: "name", sort_dir: "asc" } },
      });
      if (error) throw error;
      return data;
    },
  });
  return new Map((q.data?.items ?? []).map((t: TechStackOut) => [t.id, t.name]));
}

function ListSkeleton() {
  return <Skeleton className="h-64 w-full rounded-lg" />;
}

function ListError({ onRetry }: { onRetry: () => void }) {
  return (
    <StatePanel
      variant="error"
      title="Could not load the catalog"
      action={
        <Button variant="outline" onClick={onRetry}>
          Retry
        </Button>
      }
    />
  );
}

/** Status baris keluarga: MONITORED + nama entri, COVERED BY VENDOR, atau tautan Monitor / Hide; baris tersembunyi
 * menawarkan Unhide. Produk yang di-Monitor langsung tidak bisa disembunyikan (API menolak 409). */
function FamilyStatus({
  family,
  entryNames,
  canManage,
  busy,
  onMonitor,
  onHide,
  onUnhide,
}: {
  family: CatalogFamily;
  entryNames: ReadonlyMap<number, string>;
  canManage: boolean;
  busy: boolean;
  onMonitor: () => void;
  onHide: () => void;
  onUnhide: () => void;
}) {
  const direct = family.monitored && !family.covered_by_vendor;
  const name = family.display_name;
  return (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
      {direct && (
        <>
          <Chip kind="cve" value="monitored" />
          {family.monitor_entry_id != null && entryNames.get(family.monitor_entry_id) && (
            <span className="text-xs text-muted-foreground">{entryNames.get(family.monitor_entry_id)}</span>
          )}
        </>
      )}
      {family.covered_by_vendor && <Chip kind="cve" value="covered_by_vendor" />}
      {canManage && !family.monitored && (
        <ActionLink danger disabled={busy} onClick={onMonitor} aria-label={`Monitor ${name}`}>
          Monitor
        </ActionLink>
      )}
      {canManage && !direct && !family.hidden && (
        <ActionLink onClick={onHide} aria-label={`Hide ${name}`}>
          Hide
        </ActionLink>
      )}
      {canManage && family.hidden && (
        <ActionLink onClick={onUnhide} aria-label={`Unhide ${name}`}>
          Unhide
        </ActionLink>
      )}
    </span>
  );
}

function useFamilyActions() {
  const monitor = useMonitorActions();
  const hide = useHideFamily();
  return { monitor, hide };
}

/** Tabel keluarga produk; `withVendor` menambah kolom VENDOR (mode Products). */
function FamilyTable({ families, withVendor }: { families: CatalogFamily[]; withVendor: boolean }) {
  const can = useCan();
  const canManage = can("manage_cve");
  const entryNames = useEntryNames();
  const { monitor, hide } = useFamilyActions();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Product</TableHead>
          {withVendor && <TableHead>Vendor</TableHead>}
          <TableHead className="text-right">CVEs</TableHead>
          <TableHead>Last CVE</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {families.map((f) => (
          <TableRow key={f.id} className={cn(f.hidden && "text-muted-foreground")}>
            <TableCell className="font-semibold">{f.display_name}</TableCell>
            {withVendor && <TableCell className="text-xs text-muted-foreground">{f.vendor_name}</TableCell>}
            <TableCell className="text-right text-xs tabular-nums">{f.cve_seen_total.toLocaleString()}</TableCell>
            <TableCell className="text-xs">{fmtCompactAge(f.last_cve_at)}</TableCell>
            <TableCell className="whitespace-normal">
              <FamilyStatus
                family={f}
                entryNames={entryNames}
                canManage={canManage}
                busy={monitor.busy}
                onMonitor={() => void monitor.monitor({ family_id: f.id })}
                onHide={() => hide.hide(f)}
                onUnhide={() => hide.unhide(f)}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Detail vendor (kanan): produk milik vendor, tombol "Monitor whole vendor" dan saklar "Show hidden". */
function VendorDetail({ vendor, reveal }: { vendor: CatalogVendor; reveal: boolean }) {
  const can = useCan();
  const canManage = can("manage_cve");
  const { monitor } = useFamilyActions();
  const [showHidden, setShowHidden] = useState(false);

  const list = useInfiniteQuery({
    queryKey: ["catalog", "families", "vendor", vendor.id, reveal, showHidden],
    initialPageParam: 1,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/catalog/vendors/{vendor_id}/families", {
        params: {
          path: { vendor_id: vendor.id },
          query: { show_all: reveal, show_hidden: showHidden, page: pageParam, page_size: PAGE_SIZE },
        },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last, all) => (all.reduce((n, p) => n + p.items.length, 0) < last.total ? last.page + 1 : undefined),
  });

  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total ?? 0;

  return (
    <Card className="lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle>{vendor.display_name} - products</CardTitle>
            <CardDescription>
              {vendor.family_count} products - {vendor.cve_seen_total.toLocaleString()} CVEs
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Switch checked={showHidden} onCheckedChange={setShowHidden} aria-label="Show hidden products" label={<span className="text-xs">Show hidden</span>} />
            {canManage && vendor.monitorable && !vendor.monitored && (
              <Button size="sm" disabled={monitor.busy} onClick={() => void monitor.monitor({ vendor_id: vendor.id })}>
                Monitor whole vendor
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!vendor.monitorable && (
          <p className="text-xs text-muted-foreground">This vendor has no identity; monitor one of its products instead.</p>
        )}
        {list.isPending && <ListSkeleton />}
        {list.isError && <ListError onRetry={() => void list.refetch()} />}
        {list.isSuccess && items.length === 0 && (
          <StatePanel
            variant="empty"
            title="No products to show"
            description={
              (list.data.pages[0]?.hidden ?? 0) > 0
                ? `${list.data.pages[0].hidden} product(s) with only 1 CVE are hidden. Set Show to "all" to list them.`
                : undefined
            }
          />
        )}
        {items.length > 0 && (
          <>
            <FamilyTable families={items} withVendor={false} />
            <LoadMoreFooter
              shown={items.length}
              total={total}
              hasMore={!!list.hasNextPage}
              loading={list.isFetchingNextPage}
              onLoadMore={() => void list.fetchNextPage()}
            />
          </>
        )}
        <p className="text-xs text-muted-foreground">
          Covered by vendor means a whole-vendor entry already watches this product.
        </p>
      </CardContent>
    </Card>
  );
}

function VendorStatus({ vendor, canManage, busy, onMonitor }: { vendor: CatalogVendor; canManage: boolean; busy: boolean; onMonitor: () => void }) {
  if (vendor.monitored) return <Chip kind="cve" value="monitored" />;
  if (!canManage || !vendor.monitorable) return null;
  return (
    <ActionLink danger disabled={busy} onClick={onMonitor} aria-label={`Monitor ${vendor.display_name}`}>
      Monitor
    </ActionLink>
  );
}

/**
 * Tab "All Tech" (spec 2a, D16): katalog vendor dan produk dari CVE List V5. Mode Vendors = master-detail
 * (vendor di kiri, produknya di kanan); mode Products = satu kartu penuh yang bisa dijelajah tanpa mencari.
 * "Show: with CVEs" menyembunyikan produk yang hanya punya 1 CVE, pencarian dan "all" tidak. Hide/Unhide
 * per client (tampilan saja) dan Monitor hanya untuk `manage_cve`. Monitor membuat entri di Monitored Tech
 * dengan satu target; target tambahan diatur di sana.
 */
export function AllTechView() {
  const can = useCan();
  const canManage = can("manage_cve");
  const { monitor } = useFamilyActions();
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<Mode>("vendors");
  const [show, setShow] = useState<Show>("with_cves");
  const [picked, setPicked] = useState<number | null>(null);
  const trimmed = useDebounced(search.trim()).toLowerCase();
  const searching = trimmed.length >= MIN_QUERY;
  const showAll = show === "all";
  // Pencarian tidak menyembunyikan apa pun (aturan katalog), jadi daftar vendor ikut "reveal".
  const reveal = showAll || searching;

  const vendors = useInfiniteQuery({
    queryKey: ["catalog", "vendors", trimmed, reveal],
    initialPageParam: 1,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/catalog/vendors", {
        params: { query: { q: searching ? trimmed : undefined, show_all: reveal, page: pageParam, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last, all) => (all.reduce((n, p) => n + p.items.length, 0) < last.total ? last.page + 1 : undefined),
  });

  const products = useInfiniteQuery({
    queryKey: ["catalog", "families", "browse", searching ? trimmed : "", showAll],
    initialPageParam: 1,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/catalog/families", {
        params: { query: { q: searching ? trimmed : undefined, show_all: showAll, page: pageParam, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last, all) => (all.reduce((n, p) => n + p.items.length, 0) < last.total ? last.page + 1 : undefined),
  });

  const vendorItems = vendors.data?.pages.flatMap((p) => p.items) ?? [];
  const vendorTotal = vendors.data?.pages[0]?.total ?? 0;
  const productItems = products.data?.pages.flatMap((p) => p.items) ?? [];
  const productTotal = products.data?.pages[0]?.total ?? 0;
  const hiddenCount = (products.data?.pages[0]?.hidden ?? 0) + (products.data?.pages[0]?.hidden_by_client ?? 0);
  const selected = vendorItems.find((v) => v.id === picked) ?? vendorItems[0] ?? null;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search vendor or product"
          aria-label="Search vendor or product"
          className="w-full sm:w-64"
        />
        <SegmentedControl
          aria-label="All Tech mode"
          value={mode}
          onChange={setMode}
          options={[
            { value: "vendors", label: `Vendors ${vendorTotal.toLocaleString()}` },
            { value: "products", label: `Products ${productTotal.toLocaleString()}` },
          ]}
        />
        <FilterSelect prefix="Show" value={show} onChange={setShow} options={SHOW_OPTIONS} />
        <p className="w-full text-xs text-muted-foreground lg:ml-auto lg:w-auto">
          {hiddenCount.toLocaleString()} hidden - catalog from the CVE mirror
        </p>
      </div>

      {search.trim().length > 0 && !searching && (
        <p className="mb-3 text-xs text-muted-foreground">Type at least {MIN_QUERY} characters to search.</p>
      )}

      {mode === "vendors" ? (
        <MasterDetail
          list={
            <Card>
              <CardHeader>
                <CardTitle>Vendors</CardTitle>
                <CardDescription>Sorted by CVEs seen</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {vendors.isPending && <ListSkeleton />}
                {vendors.isError && <ListError onRetry={() => void vendors.refetch()} />}
                {vendors.isSuccess && vendorItems.length === 0 && (
                  <StatePanel
                    variant="empty"
                    title={searching ? `No vendor matches "${trimmed}"` : "No vendors yet"}
                    description={searching ? undefined : "The catalog fills as the CVE mirror syncs."}
                  />
                )}
                {vendorItems.length > 0 && (
                  <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Vendor</TableHead>
                          <TableHead className="text-right">Products</TableHead>
                          <TableHead className="text-right">CVEs</TableHead>
                          <TableHead>Last CVE</TableHead>
                          <TableHead>Status</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {vendorItems.map((v) => (
                          <TableRow key={v.id} selected={v.id === selected?.id}>
                            <TableCell>
                              <button
                                type="button"
                                aria-current={v.id === selected?.id ? "true" : undefined}
                                onClick={() => setPicked(v.id)}
                                className="rounded-sm text-left font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                              >
                                {v.display_name}
                              </button>
                            </TableCell>
                            <TableCell className="text-right text-xs tabular-nums">{v.family_count}</TableCell>
                            <TableCell className="text-right text-xs tabular-nums">{v.cve_seen_total.toLocaleString()}</TableCell>
                            <TableCell className="text-xs">{fmtCompactAge(v.last_cve_at)}</TableCell>
                            <TableCell>
                              <VendorStatus
                                vendor={v}
                                canManage={canManage}
                                busy={monitor.busy}
                                onMonitor={() => void monitor.monitor({ vendor_id: v.id })}
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <LoadMoreFooter
                      shown={vendorItems.length}
                      total={vendorTotal}
                      hasMore={!!vendors.hasNextPage}
                      loading={vendors.isFetchingNextPage}
                      onLoadMore={() => void vendors.fetchNextPage()}
                    />
                  </>
                )}
              </CardContent>
            </Card>
          }
          detail={
            selected ? (
              <VendorDetail key={selected.id} vendor={selected} reveal={reveal} />
            ) : vendors.isPending ? (
              <Skeleton className="h-64 rounded-lg" />
            ) : (
              <StatePanel variant="empty" title="No vendor selected" description="Pick a vendor to see its products." />
            )
          }
        />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>Products</CardTitle>
            <CardDescription>
              {productTotal.toLocaleString()} products{searching ? ` matching "${trimmed}"` : ""} - sorted by CVEs seen
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {products.isPending && <ListSkeleton />}
            {products.isError && <ListError onRetry={() => void products.refetch()} />}
            {products.isSuccess && productItems.length === 0 && (
              <StatePanel variant="empty" title={searching ? `No product matches "${trimmed}"` : "No products to show"} />
            )}
            {productItems.length > 0 && (
              <>
                <FamilyTable families={productItems} withVendor />
                <LoadMoreFooter
                  shown={productItems.length}
                  total={productTotal}
                  hasMore={!!products.hasNextPage}
                  loading={products.isFetchingNextPage}
                  onLoadMore={() => void products.fetchNextPage()}
                />
              </>
            )}
            <p className="text-xs text-muted-foreground">
              Covered by vendor means a whole-vendor entry already watches this product.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
