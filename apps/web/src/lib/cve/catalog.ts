"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { TechStackActionResult } from "@/lib/api/loose-types";

export type CatalogVendor = components["schemas"]["CatalogVendorOut"];
export type CatalogFamily = components["schemas"]["CatalogFamilyOut"];
export type TechStackOut = components["schemas"]["TechStackOut"];
export type TechStackTarget = components["schemas"]["TechStackTargetOut"];

/** Satu rujukan katalog: tepat satu dari `vendor_id` / `family_id` (sama dengan body API). */
export type CatalogRef = { vendor_id: number } | { family_id: number };

/** Ketikan di-debounce 400ms sebelum jadi query (satu request per jeda, bukan per huruf). */
export function useDebounced<T>(value: T, ms = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Pilihan Exposure/Hosting entri techstack (D15): nilai API -> label tampilan. */
export const EXPOSURE_LABEL: Record<string, string> = { public: "Public", internal: "Internal", both: "Public + internal" };
export const HOSTING_LABEL: Record<string, string> = { on_prem: "On-prem", cloud: "Cloud", saas: "SaaS" };

const REASONS: Record<string, string> = {
  duplicate: "A tech with this name already exists for this client",
  not_found: "That catalog item no longer exists",
  vendor_not_monitorable: "This vendor has no identity (\"tanpa vendor\"); monitor one of its products instead",
  invalid_target: "Invalid target",
};

function reasonText(reason: string | undefined): string {
  return (reason && REASONS[reason]) || reason || "Request failed";
}

function detailText(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : "Request failed";
}

/** Ringkas target entri untuk ditampilkan: "Fortinet" (vendor) atau "Fortinet › FortiOS". */
export function targetLabel(t: TechStackTarget): string {
  return t.kind === "family" && t.vendor_label ? `${t.vendor_label} › ${t.label}` : t.label;
}

/**
 * Aksi Monitor (tambah entri katalog, tambah/lepas target, aktif/nonaktif). Semua menampilkan
 * toast sendiri dan meng-invalidate query yang berubah (daftar techstack, katalog, CVE DB, tab
 * CVEs). Mengembalikan `true` bila berhasil, supaya pemanggil bisa menutup dialog dst.
 */
export function useMonitorActions() {
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  function invalidate() {
    for (const key of ["techstack", "catalog", "cve-db", "cve"]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  }

  async function guarded(fn: () => Promise<boolean>): Promise<boolean> {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      toast.error((e as Error).message || "Request failed");
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** Tombol Monitor di All Tech / CVE DB: entri baru dengan satu target katalog. */
  const monitor = (
    ref: CatalogRef,
    label?: string,
    opts: { exposure: string; hosting_type: string } = { exposure: "internal", hosting_type: "on_prem" },
  ) =>
    guarded(async () => {
      const { data, error } = await api.POST("/api/techstack", { body: { ...ref, name: label, ...opts } });
      if (error) throw new Error(detailText(error));
      const d = data as unknown as TechStackActionResult;
      if (!d.success) {
        toast.error(reasonText(d.reason));
        return false;
      }
      toast.success(`Monitoring ${d.item?.name ?? "tech"}`);
      invalidate();
      return true;
    });

  const addTarget = (entryId: number, ref: CatalogRef) =>
    guarded(async () => {
      const { error } = await api.POST("/api/techstack/{tech_id}/targets", {
        params: { path: { tech_id: entryId } },
        body: ref,
      });
      if (error) throw new Error(detailText(error));
      toast.success("Target added");
      invalidate();
      return true;
    });

  const removeTarget = (entryId: number, targetId: number) =>
    guarded(async () => {
      const { error } = await api.DELETE("/api/techstack/{tech_id}/targets/{target_id}", {
        params: { path: { tech_id: entryId, target_id: targetId } },
      });
      if (error) throw new Error(detailText(error));
      toast.success("Target removed");
      invalidate();
      return true;
    });

  const setActive = (entryId: number, active: boolean) =>
    guarded(async () => {
      const { error } = await api.PATCH("/api/techstack/{tech_id}", {
        params: { path: { tech_id: entryId } },
        body: { active },
      });
      if (error) throw new Error(detailText(error));
      toast.success(active ? "Monitoring resumed" : "Paused (hidden, nothing is deleted)");
      invalidate();
      return true;
    });

  return { busy, monitor, addTarget, removeTarget, setActive, invalidate };
}

/**
 * Sembunyikan / tampilkan lagi keluarga produk di All Tech client aktif (D16; tampilan saja, Monitor dan CVE DB
 * tidak berubah). 409 = produk di-Monitor langsung: detail dari API ("{produk} is monitored directly, so it cannot
 * be hidden") ditampilkan sebagai toast. Hanya `manage_cve`; pemanggil yang menyembunyikan tombolnya.
 */
export function useHideFamily() {
  const queryClient = useQueryClient();

  async function run(family: CatalogFamily, hide: boolean) {
    const path = { family_id: family.id };
    const { error } = hide
      ? await api.PUT("/api/catalog/families/{family_id}/hide", { params: { path } })
      : await api.DELETE("/api/catalog/families/{family_id}/hide", { params: { path } });
    if (error) {
      const text = detailText(error);
      toast.error(text === "Request failed" && hide ? `${family.display_name} could not be hidden` : text);
      return;
    }
    toast.success(hide ? `Hidden ${family.display_name}` : `Unhidden ${family.display_name}`);
    for (const key of ["catalog", "techstack"]) void queryClient.invalidateQueries({ queryKey: [key] });
  }

  return { hide: (f: CatalogFamily) => void run(f, true), unhide: (f: CatalogFamily) => void run(f, false) };
}
