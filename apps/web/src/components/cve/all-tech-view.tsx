"use client";

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager, usePageResetOn } from "@/components/pager";
import { PanelEmpty, PanelError, PanelLoading } from "@/components/newsroom/panel-shell";
import { useDebounced, useMonitorActions, type CatalogFamily, type CatalogVendor } from "@/lib/cve/catalog";

const PAGE_SIZE = 25;
const MIN_QUERY = 2;

function MonitorStatus({ monitored, viaVendor }: { monitored: boolean; viaVendor?: boolean }) {
  if (!monitored) return null;
  return (
    <Badge variant={viaVendor ? "secondary" : "default"} className="text-xs">
      {viaVendor ? "Covered by vendor" : "Monitored"}
    </Badge>
  );
}

function cveCount(n: number): string {
  return `${n.toLocaleString()} CVE`;
}

/** Baris keluarga produk (dipakai di dalam vendor dan di hasil pencarian). */
function FamilyRow({
  family,
  showVendor,
  busy,
  onMonitor,
}: {
  family: CatalogFamily;
  showVendor: boolean;
  busy: boolean;
  onMonitor: (family: CatalogFamily) => void;
}) {
  return (
    <TableRow>
      <TableCell className="pl-8 text-xs">
        <span className="font-medium">{family.display_name}</span>
        {showVendor && <span className="ml-2 text-muted-foreground">{family.vendor_name}</span>}
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{cveCount(family.cve_seen_total)}</TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">{family.last_cve_at ?? "—"}</TableCell>
      <TableCell>
        <MonitorStatus monitored={family.monitored} viaVendor={family.covered_by_vendor} />
      </TableCell>
      <TableCell className="text-right">
        <Button size="sm" variant="outline" disabled={busy || family.monitored} onClick={() => onMonitor(family)}>
          {family.monitored ? "Monitored" : "Monitor"}
        </Button>
      </TableCell>
    </TableRow>
  );
}

function VendorFamilies({ vendor, showAll, searching }: { vendor: CatalogVendor; showAll: boolean; searching: boolean }) {
  const actions = useMonitorActions();
  const [page, setPage] = useState(1);
  const reveal = showAll || searching;
  const query = useQuery({
    queryKey: ["catalog", "families", "vendor", vendor.id, reveal, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/vendors/{vendor_id}/families", {
        params: { path: { vendor_id: vendor.id }, query: { show_all: reveal, page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
  });

  if (query.isPending) {
    return (
      <TableRow>
        <TableCell colSpan={5}>
          <PanelLoading />
        </TableCell>
      </TableRow>
    );
  }
  if (query.isError) {
    return (
      <TableRow>
        <TableCell colSpan={5}>
          <PanelError />
        </TableCell>
      </TableRow>
    );
  }
  const totalPages = Math.ceil(query.data.total / PAGE_SIZE) || 1;
  return (
    <>
      {query.data.items.length === 0 && (
        <TableRow>
          <TableCell colSpan={5} className="py-3 pl-8 text-xs text-muted-foreground">
            No products to show{query.data.hidden > 0 ? ` (${query.data.hidden} with only 1 CVE hidden)` : ""}.
          </TableCell>
        </TableRow>
      )}
      {query.data.items.map((f) => (
        <FamilyRow
          key={f.id}
          family={f}
          showVendor={false}
          busy={actions.busy}
          onMonitor={(fam) => void actions.monitor({ family_id: fam.id })}
        />
      ))}
      {query.data.hidden > 0 && (
        <TableRow>
          <TableCell colSpan={5} className="py-2 pl-8 text-xs text-muted-foreground">
            {query.data.hidden} product(s) with only 1 CVE are hidden. Tick “Show all” above to list them.
          </TableCell>
        </TableRow>
      )}
      {totalPages > 1 && (
        <TableRow>
          <TableCell colSpan={5}>
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${query.data.total} products`} onPageChange={setPage} />
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function VendorsTable({ q, showAll }: { q: string; showAll: boolean }) {
  const actions = useMonitorActions();
  const [page, setPage] = usePageResetOn(`${q}|${showAll}`);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const searching = q.length >= MIN_QUERY;

  const query = useQuery({
    queryKey: ["catalog", "vendors", q, showAll, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/vendors", {
        params: { query: { q: searching ? q : undefined, show_all: showAll, page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
  });

  function toggle(id: number) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (query.isPending) return <PanelLoading />;
  if (query.isError) return <PanelError />;
  const totalPages = Math.ceil(query.data.total / PAGE_SIZE) || 1;
  if (query.data.items.length === 0) return <PanelEmpty message={searching ? `No vendor matches “${q}”.` : "No vendors yet."} />;

  return (
    <>
      <Table framed>
        <TableHeader>
          <TableRow>
            <TableHead>Vendor / product</TableHead>
            <TableHead>CVEs</TableHead>
            <TableHead>Last CVE</TableHead>
            <TableHead>Status</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data.items.map((v) => {
            const expanded = open.has(v.id);
            return (
              <Fragment key={v.id}>
                <TableRow>
                  <TableCell>
                    <button
                      type="button"
                      className="flex items-center gap-1.5 text-left text-sm font-medium"
                      onClick={() => toggle(v.id)}
                      aria-expanded={expanded}
                    >
                      {expanded ? <ChevronDownIcon className="size-4" /> : <ChevronRightIcon className="size-4" />}
                      {v.display_name}
                      <span className="text-xs font-normal text-muted-foreground">
                        {v.family_count} product{v.family_count === 1 ? "" : "s"}
                        {!showAll && !searching && v.visible_family_count < v.family_count
                          ? ` · ${v.visible_family_count} shown`
                          : ""}
                      </span>
                    </button>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{cveCount(v.cve_seen_total)}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{v.last_cve_at ?? "—"}</TableCell>
                  <TableCell>
                    <MonitorStatus monitored={v.monitored} />
                  </TableCell>
                  <TableCell className="text-right">
                    {v.monitorable ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={actions.busy || v.monitored}
                        onClick={() => void actions.monitor({ vendor_id: v.id })}
                      >
                        {v.monitored ? "Monitored" : "Monitor vendor"}
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">monitor a product instead</span>
                    )}
                  </TableCell>
                </TableRow>
                {expanded && <VendorFamilies vendor={v} showAll={showAll} searching={searching} />}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
      {query.data.hidden > 0 && (
        <p className="mt-2 text-center text-xs text-muted-foreground">
          {query.data.hidden} vendor(s) whose products all have only 1 CVE are hidden. Search for them, or tick “Show all”.
        </p>
      )}
      <div className="mt-3 flex justify-center">
        <SimplePager page={page} totalPages={totalPages} totalLabel={`${query.data.total} vendors`} onPageChange={setPage} />
      </div>
    </>
  );
}

function ProductSearch({ q }: { q: string }) {
  const actions = useMonitorActions();
  const [page, setPage] = usePageResetOn(q);
  const query = useQuery({
    queryKey: ["catalog", "families", "search", q, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/catalog/families", {
        params: { query: { q, page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
  });
  if (query.isPending) return <PanelLoading />;
  if (query.isError) return <PanelError />;
  if (query.data.items.length === 0) return <PanelEmpty message={`No product matches “${q}”.`} />;
  const totalPages = Math.ceil(query.data.total / PAGE_SIZE) || 1;
  return (
    <>
      <Table framed>
        <TableHeader>
          <TableRow>
            <TableHead>Product</TableHead>
            <TableHead>CVEs</TableHead>
            <TableHead>Last CVE</TableHead>
            <TableHead>Status</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {query.data.items.map((f) => (
            <FamilyRow
              key={f.id}
              family={f}
              showVendor
              busy={actions.busy}
              onMonitor={(fam) => void actions.monitor({ family_id: fam.id })}
            />
          ))}
        </TableBody>
      </Table>
      <div className="mt-3 flex justify-center">
        <SimplePager page={page} totalPages={totalPages} totalLabel={`${query.data.total} products`} onPageChange={setPage} />
      </div>
    </>
  );
}

/**
 * Tab "All Tech" (ROADMAP #19, irisan 6): katalog vendor -> produk dari CVE List V5, dengan tombol
 * Monitor. Search-first: jelajah (tanpa pencarian) menyembunyikan produk yang hanya punya 1 CVE
 * (keputusan user), pencarian dan "Show all" tidak menyembunyikan apa pun. Monitor membuat entri di
 * tab "Monitored Tech" dengan satu target; target tambahan diatur di sana.
 */
export function AllTechView() {
  const [search, setSearch] = useState("");
  const [showAll, setShowAll] = useState(false);
  const q = useDebounced(search.trim()).toLowerCase();
  const searching = q.length >= MIN_QUERY;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-3 border-b border-border pb-3">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search vendor or product</Label>
          <Input
            placeholder="e.g. fortinet, nginx, junos…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-72 font-mono text-xs"
          />
        </div>
        {!searching && (
          <label className="flex items-center gap-2 pb-2 text-sm text-muted-foreground">
            <Checkbox checked={showAll} onCheckedChange={(v) => setShowAll(v === true)} />
            Show all (include products with only 1 CVE)
          </label>
        )}
        <p className="ml-auto max-w-md pb-1 text-xs text-muted-foreground">
          Catalog built from CVE List V5. “Monitor” adds the item to <strong>Monitored Tech</strong>; matching CVEs then
          appear in the CVEs tab.
        </p>
      </div>

      {search.trim().length > 0 && !searching && (
        <p className="mb-3 text-xs text-muted-foreground">Type at least {MIN_QUERY} characters to search.</p>
      )}

      {searching ? (
        <div className="flex flex-col gap-6">
          <section>
            <h3 className="mb-2 text-sm font-medium">Vendors</h3>
            <VendorsTable q={q} showAll />
          </section>
          <section>
            <h3 className="mb-2 text-sm font-medium">Products</h3>
            <ProductSearch q={q} />
          </section>
        </div>
      ) : (
        <VendorsTable q="" showAll={showAll} />
      )}
    </div>
  );
}
