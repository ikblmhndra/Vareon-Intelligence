"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { RfiDetailCard } from "@/components/intelligence/rfi/rfi-detail-card";
import { RfiFormDialog } from "@/components/intelligence/rfi/rfi-form-dialog";
import { RfiList } from "@/components/intelligence/rfi/rfi-list";
import { Button } from "@/components/ui/button";
import { FilterSelect } from "@/components/ui/filter-select";
import { MasterDetail } from "@/components/ui/master-detail";
import { SearchInput } from "@/components/ui/search-input";
import { StatePanel } from "@/components/ui/state-panel";
import { TabPills } from "@/components/ui/tab-pills";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { useDebounced } from "@/lib/cve/catalog";
import { displayId } from "@/lib/intelligence/format";
import { usePirs } from "@/lib/intelligence/pir";
import {
  invalidateRfis,
  isRfiStatus,
  RFI_STATUS_OPTIONS,
  useRfis,
  type RFIOut,
  type RfiPirFilter,
  type RfiStatus,
} from "@/lib/intelligence/rfi";

// `useSearchParams` di client page wajib dibungkus Suspense (Next 16).
export default function RfiPage() {
  return (
    <Suspense fallback={null}>
      <RfiView />
    </Suspense>
  );
}

/** `?pir=` -> filter: angka positif = id PIR, `none` = tanpa PIR, selain itu semua. */
function parsePirParam(v: string | null): RfiPirFilter {
  if (v === "none") return "none";
  const n = Number(v);
  return v != null && Number.isInteger(n) && n > 0 ? (`${n}` as RfiPirFilter) : "all";
}

/** RFI (spec 2b 6.5): master-detail. URL memegang tab status (`?status=`, baku open), filter PIR (`?pir=`,
 * dipakai tautan "n open" dari halaman PIR) dan RFI terpilih (`?id=`); pencarian cukup state lokal. */
function RfiView() {
  const can = useCan();
  const canManage = can("manage_rfi");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queryClient = useQueryClient();

  const statusParam = params.get("status");
  const status: RfiStatus = isRfiStatus(statusParam) ? statusParam : "open";
  const pir = parsePirParam(params.get("pir"));
  const idParam = Number(params.get("id"));
  const requestedId = Number.isInteger(idParam) && idParam > 0 ? idParam : null;

  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim().slice(0, 200), 300);
  const [addOpen, setAddOpen] = useState(false);
  const [addKey, setAddKey] = useState(0);
  const [editTarget, setEditTarget] = useState<RFIOut | null>(null);
  const [removeTarget, setRemoveTarget] = useState<RFIOut | null>(null);
  const [removing, setRemoving] = useState(false);
  const [saving, setSaving] = useState(false);

  const pirsQuery = usePirs();
  const list = useRfis(status, q, pir);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;

  // "Tanpa PIR" disaring di klien: ambil semua halaman supaya hasilnya lengkap, bukan sepotong per halaman.
  useEffect(() => {
    if (pir === "none" && hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [pir, hasNextPage, isFetchingNextPage, fetchNextPage]);

  const loaded = list.data?.pages.flatMap((p) => p.rfis) ?? [];
  const rfis = pir === "none" ? loaded.filter((r) => r.linked_pir == null) : loaded;
  const total = pir === "none" ? rfis.length : (list.data?.pages[0]?.total ?? 0);
  const counts = list.data?.pages[0]?.status_counts;
  const selected = rfis.find((r) => r.id === requestedId) ?? rfis[0] ?? null;

  const tabs = RFI_STATUS_OPTIONS.map((t) => ({ ...t, count: counts?.[t.value] }));

  const pirTitles = new Map((pirsQuery.data ?? []).map((p) => [p.id, `${displayId("PIR", p.id)} ${p.title}`]));
  const pirOptions = [
    { value: "all" as const, label: "all" },
    { value: "none" as const, label: "none" },
    ...(pirsQuery.data ?? []).map((p) => ({ value: `${p.id}` as RfiPirFilter, label: pirTitles.get(p.id) ?? "" })),
  ];
  // Filter dari URL untuk PIR yang tak ada di daftar (dihapus/belum termuat) tetap punya label.
  if (!pirOptions.some((o) => o.value === pir)) pirOptions.push({ value: pir, label: displayId("PIR", Number(pir)) });

  function setUrl(next: { status?: RfiStatus; pir?: RfiPirFilter; id?: number | null }) {
    const qs = new URLSearchParams(params.toString());
    if (next.status !== undefined) {
      if (next.status === "open") qs.delete("status");
      else qs.set("status", next.status);
    }
    if (next.pir !== undefined) {
      if (next.pir === "all") qs.delete("pir");
      else qs.set("pir", next.pir);
    }
    if (next.id !== undefined) {
      if (next.id == null) qs.delete("id");
      else qs.set("id", String(next.id));
    }
    const s = qs.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }

  async function saveResponse(rfi: RFIOut, response: string, newStatus: RfiStatus) {
    setSaving(true);
    try {
      const { data, error } = await api.PUT("/api/rfi/{rfi_id}", {
        params: { path: { rfi_id: rfi.id } },
        body: { response, status: newStatus },
      });
      if (error || !data) {
        toast.error("Could not save the response.");
        return;
      }
      toast.success("Response saved.");
      invalidateRfis(queryClient);
      // Status baru = tab lain: pindah ke sana supaya RFI tetap terlihat dan terpilih.
      if (data.status !== status && isRfiStatus(data.status)) setUrl({ status: data.status, id: data.id });
    } catch {
      toast.error("Could not save the response.");
    } finally {
      setSaving(false);
    }
  }

  async function removeRfi(target: RFIOut) {
    setRemoving(true);
    try {
      const { error } = await api.DELETE("/api/rfi/{rfi_id}", { params: { path: { rfi_id: target.id } } });
      if (error) {
        toast.error("Error deleting RFI");
        return;
      }
      toast.success("RFI deleted.");
      if (target.id === requestedId) setUrl({ id: null });
      invalidateRfis(queryClient);
    } catch {
      toast.error("Error deleting RFI");
    } finally {
      setRemoving(false);
      setRemoveTarget(null);
    }
  }

  function onSaved(saved: RFIOut) {
    if (isRfiStatus(saved.status)) setUrl({ status: saved.status, id: saved.id });
  }

  const filtered = q !== "" || pir !== "all";
  let listPanel;
  if (list.isPending) listPanel = <StatePanel variant="loading" title="Loading RFIs" />;
  else if (list.isError)
    listPanel = (
      <StatePanel
        variant="error"
        title="Failed to load RFIs"
        action={
          <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
            Retry
          </Button>
        }
      />
    );
  else if (rfis.length === 0 && (pir === "none" ? hasNextPage : false))
    listPanel = <StatePanel variant="loading" title="Loading RFIs" />;
  else if (rfis.length === 0)
    listPanel = (
      <StatePanel
        variant="empty"
        title={filtered ? "No RFIs match these filters" : `No ${tabLabel(status).toLowerCase()} RFIs`}
        description={!filtered && status === "open" && canManage ? "Create one with + New RFI." : undefined}
      />
    );
  else
    listPanel = (
      <RfiList
        rfis={rfis}
        selectedId={selected?.id ?? null}
        onSelect={(id) => setUrl({ id })}
        shown={rfis.length}
        total={total}
        hasMore={pir !== "none" && !!hasNextPage}
        loadingMore={isFetchingNextPage}
        onLoadMore={() => void fetchNextPage()}
      />
    );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <TabPills
          aria-label="RFI status"
          items={tabs}
          value={status}
          onChange={(s) => setUrl({ status: s, id: null })}
        />
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search questions"
          aria-label="Search questions"
          className="w-full sm:w-64"
        />
        <FilterSelect
          prefix="Linked PIR"
          value={pir}
          onChange={(v) => setUrl({ pir: v, id: null })}
          options={pirOptions}
        />
        {canManage && (
          <Button
            size="sm"
            className="ml-auto"
            onClick={() => {
              setAddKey((k) => k + 1);
              setAddOpen(true);
            }}
          >
            + New RFI
          </Button>
        )}
      </div>

      <MasterDetail
        list={listPanel}
        detail={
          selected ? (
            <RfiDetailCard
              key={`${selected.id}-${selected.updated_at}`}
              rfi={selected}
              pirLabel={selected.linked_pir != null ? (pirTitles.get(selected.linked_pir) ?? null) : null}
              canManage={canManage}
              saving={saving}
              onSave={(response, s) => void saveResponse(selected, response, s)}
              onEdit={() => setEditTarget(selected)}
              onDelete={() => setRemoveTarget(selected)}
            />
          ) : (
            list.data && <StatePanel variant="empty" title="Select an RFI to see its response" />
          )
        }
      />

      <RfiFormDialog key={`add-${addKey}`} open={addOpen} onOpenChange={setAddOpen} onSaved={onSaved} />
      <RfiFormDialog
        key={`edit-${editTarget?.id ?? "none"}-${editTarget?.updated_at ?? ""}`}
        rfi={editTarget}
        open={editTarget !== null}
        onOpenChange={(o) => !o && setEditTarget(null)}
        onSaved={onSaved}
      />
      <ConfirmDialog
        open={removeTarget !== null}
        onOpenChange={(open) => !open && setRemoveTarget(null)}
        title={removeTarget ? `Delete ${displayId("RFI", removeTarget.id)}` : "Delete RFI"}
        description="Delete this RFI? This cannot be undone."
        confirmLabel="Delete"
        tone="danger"
        confirmLoading={removing}
        onConfirm={() => removeTarget && void removeRfi(removeTarget)}
      />
    </div>
  );
}

function tabLabel(s: RfiStatus): string {
  return RFI_STATUS_OPTIONS.find((t) => t.value === s)?.label ?? s;
}
