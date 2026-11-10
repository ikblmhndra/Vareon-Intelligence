"use client";

import { ChevronDownIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { PirArticlesDialog } from "@/components/intelligence/pir/pir-articles-dialog";
import { PirDetailCard, PirGapCard } from "@/components/intelligence/pir/pir-detail-card";
import { PirFormDialog } from "@/components/intelligence/pir/pir-form-dialog";
import { PirList } from "@/components/intelligence/pir/pir-list";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FilterSelect } from "@/components/ui/filter-select";
import { MasterDetail } from "@/components/ui/master-detail";
import { StatePanel } from "@/components/ui/state-panel";
import { TabPills } from "@/components/ui/tab-pills";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { downloadBlob } from "@/lib/csv";
import { displayId, PIR_PRIORITY_OPTIONS } from "@/lib/intelligence/format";
import {
  invalidatePirs,
  isPirStatusTab,
  PIR_STATUS_TABS,
  usePirCampaigns,
  usePirs,
  type PIROut,
  type PirStatusTab,
} from "@/lib/intelligence/pir";

const ALL = "all";
const PRIORITY_FILTER = [{ value: ALL, label: "all" }, ...PIR_PRIORITY_OPTIONS];

// `useSearchParams` di client page wajib dibungkus Suspense (Next 16).
export default function PirPage() {
  return (
    <Suspense fallback={null}>
      <PirView />
    </Suspense>
  );
}

/** PIR (spec 2b 6.4): master-detail. URL memegang tab status (`?status=`, baku active) dan PIR terpilih
 * (`?id=`, dipakai tautan "Link to PIR" Campaigns dan chip RFI); filter Owner/Priority lokal (sisi klien). */
function PirView() {
  const can = useCan();
  const canManage = can("manage_pir");
  const canExport = can("export_data");
  // bundle STIX dilayani `/api/stix/pirs` yang dijaga `view_stix`, bukan `export_data`
  const canStix = can("view_stix");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const pirsQuery = usePirs();
  // Kampanye diambil di latar (clustering mahal); hanya baris "Campaigns matched" yang menunggunya.
  const campaignsQuery = usePirCampaigns();
  const pirs = pirsQuery.data ?? [];

  const [owner, setOwner] = useState(ALL);
  const [priority, setPriority] = useState(ALL);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [editTarget, setEditTarget] = useState<PIROut | null>(null);
  const [viewTarget, setViewTarget] = useState<PIROut | null>(null);
  const [removeTarget, setRemoveTarget] = useState<PIROut | null>(null);
  const [removing, setRemoving] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);

  const idParam = Number(params.get("id"));
  const requestedId = Number.isInteger(idParam) && idParam > 0 ? idParam : null;
  const requested = requestedId != null ? pirs.find((p) => p.id === requestedId) : undefined;
  const statusParam = params.get("status");
  // `?id=` tanpa `?status=` (tautan dari Campaigns/RFI) membuka tab tempat PIR itu berada.
  const status: PirStatusTab = isPirStatusTab(statusParam)
    ? statusParam
    : requested && isPirStatusTab(requested.status)
      ? requested.status
      : "active";

  function setUrl(next: { status?: PirStatusTab; id?: number | null }) {
    const qs = new URLSearchParams(params.toString());
    if (next.status !== undefined) {
      if (next.status === "active") qs.delete("status");
      else qs.set("status", next.status);
    }
    if (next.id !== undefined) {
      if (next.id == null) qs.delete("id");
      else qs.set("id", String(next.id));
    }
    const s = qs.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }

  const counts = Object.fromEntries(
    PIR_STATUS_TABS.map((t) => [t.value, pirs.filter((p) => p.status === t.value).length]),
  ) as Record<PirStatusTab, number>;
  const tabs = PIR_STATUS_TABS.map((t) => ({ ...t, count: pirsQuery.data ? counts[t.value] : undefined }));

  const owners = [...new Set(pirs.map((p) => p.owner).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  const ownerOptions = [{ value: ALL, label: "all" }, ...owners.map((o) => ({ value: o, label: o }))];

  const inTab = pirs.filter((p) => p.status === status);
  const visible = inTab.filter(
    (p) => (owner === ALL || p.owner === owner) && (priority === ALL || p.priority === priority),
  );
  // PIR terpilih: dari URL bila terlihat di tampilan ini, selain itu kartu pertama (seperti mockup).
  const selected = visible.find((p) => p.id === requestedId) ?? visible[0] ?? null;

  async function runExport(key: string, url: string, fallback: string) {
    setExporting(key);
    try {
      await downloadBlob(url, fallback);
    } catch (e) {
      const msg = (e as Error).message;
      toast.error(msg.includes("(501)") ? "python-docx not installed on server." : "Export failed.");
    } finally {
      setExporting(null);
    }
  }
  const exportJson = (p: PIROut) =>
    void runExport(`json-${p.id}`, `/api/pir/${p.id}/export`, `${displayId("PIR", p.id)}.json`);
  const exportDocx = (p: PIROut) =>
    void runExport(`docx-${p.id}`, `/api/pir/${p.id}/export/docx`, `${displayId("PIR", p.id)}.docx`);

  async function removePir(target: PIROut) {
    setRemoving(true);
    try {
      const { error } = await api.DELETE("/api/pir/{pir_id}", { params: { path: { pir_id: target.id } } });
      if (error) {
        toast.error("Error deleting PIR");
        return;
      }
      toast.success("PIR deleted.");
      if (target.id === requestedId) setUrl({ id: null });
      invalidatePirs(queryClient);
    } catch {
      toast.error("Error deleting PIR");
    } finally {
      setRemoving(false);
      setRemoveTarget(null);
    }
  }

  function onSaved(saved: PIROut) {
    invalidatePirs(queryClient);
    // Pindah ke tab status PIR yang baru disimpan supaya kartunya tetap terlihat dan terpilih.
    setUrl({ id: saved.id, status: isPirStatusTab(saved.status) ? saved.status : "active" });
  }

  let list;
  if (pirsQuery.isPending) list = <StatePanel variant="loading" title="Loading PIRs" />;
  else if (pirsQuery.isError)
    list = (
      <StatePanel
        variant="error"
        title="Failed to load PIRs"
        action={
          <Button variant="outline" size="sm" onClick={() => void pirsQuery.refetch()}>
            Retry
          </Button>
        }
      />
    );
  else if (pirs.length === 0)
    list = (
      <StatePanel
        variant="empty"
        title="No PIRs yet"
        description={canManage ? "Create one with + New PIR." : undefined}
      />
    );
  else if (visible.length === 0)
    list = (
      <StatePanel
        variant="empty"
        title={inTab.length === 0 ? `No ${tabLabel(status).toLowerCase()} PIRs` : "No PIRs match these filters"}
      />
    );
  else
    list = (
      <PirList
        pirs={visible}
        selectedId={selected?.id ?? null}
        onSelect={(id) => setUrl({ id })}
        canManage={canManage}
        canExport={canExport}
        onEdit={setEditTarget}
        onExportJson={exportJson}
        onExportDocx={exportDocx}
        onDelete={setRemoveTarget}
      />
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <TabPills
          aria-label="PIR status"
          items={tabs}
          value={status}
          onChange={(s) => setUrl({ status: s, id: null })}
        />
        <FilterSelect prefix="Owner" value={owner} onChange={setOwner} options={ownerOptions} />
        <FilterSelect prefix="Priority" value={priority} onChange={setPriority} options={PRIORITY_FILTER} />
        <div className="ml-auto flex items-center gap-2">
          {canStix && (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="outline" size="sm" loading={exporting === "stix"} />}
              >
                Export
                <ChevronDownIcon aria-hidden />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={() => void runExport("stix", "/api/stix/pirs", "stix-pirs.json")}
                >
                  STIX bundle of active PIRs
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {canManage && (
            <Button
              size="sm"
              onClick={() => {
                setAddKey((k) => k + 1);
                setAddOpen(true);
              }}
            >
              + New PIR
            </Button>
          )}
        </div>
      </div>

      <MasterDetail
        list={list}
        detail={
          <div className="flex flex-col gap-4">
            {selected ? (
              <PirDetailCard
                key={selected.id}
                pir={selected}
                campaigns={campaignsQuery}
                canManage={canManage}
                canExport={canExport}
                exportingJson={exporting === `json-${selected.id}`}
                onViewArticles={() => setViewTarget(selected)}
                onExportJson={() => exportJson(selected)}
                onExportDocx={() => exportDocx(selected)}
                onEdit={() => setEditTarget(selected)}
                onDelete={() => setRemoveTarget(selected)}
              />
            ) : (
              pirsQuery.data && <StatePanel variant="empty" title="Select a PIR to see its coverage" />
            )}
            <PirGapCard />
          </div>
        }
      />

      <PirFormDialog key={`add-${addKey}`} open={addOpen} onClose={() => setAddOpen(false)} onSaved={onSaved} />
      <PirFormDialog
        key={`edit-${editTarget?.id ?? "none"}`}
        pir={editTarget}
        open={editTarget !== null}
        onClose={() => setEditTarget(null)}
        onSaved={onSaved}
      />
      <PirArticlesDialog pir={viewTarget} onClose={() => setViewTarget(null)} />
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={removeTarget ? `Delete ${displayId("PIR", removeTarget.id)}` : "Delete PIR"}
        description={`Delete "${removeTarget?.title ?? ""}"? Its article notes are deleted and linked RFIs are unlinked. This cannot be undone.`}
        confirmLabel="Delete"
        tone="danger"
        cancelVariant="ghost"
        confirmLoading={removing}
        onConfirm={() => removeTarget && void removePir(removeTarget)}
      />
    </div>
  );
}

function tabLabel(s: PirStatusTab): string {
  return PIR_STATUS_TABS.find((t) => t.value === s)?.label ?? s;
}
