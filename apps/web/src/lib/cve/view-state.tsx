"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type CveView = "cves" | "pkgvuln";
export type CveSubview = "cves" | "dashboard" | "ticketing" | "monitored" | "alltech" | "cvedb";

interface CveViewState {
  view: CveView;
  subview: CveSubview;
  setView: (view: CveView) => void;
  setSubview: (subview: CveSubview) => void;
  /** Empty state CVEs meminta picker "Add from catalog" di Monitored Tech dibuka. */
  addFromCatalogRequested: boolean;
  requestAddFromCatalog: () => void;
  clearAddFromCatalog: () => void;
  /** Pencarian yang diteruskan ke sub-view CVEs (mis. "Open in CVE tracker" dari CVE DB); CveCoreView memakai lalu menghapusnya. */
  pendingSearch: string | null;
  openInTracker: (search: string) => void;
  clearPendingSearch: () => void;
}

const CveViewContext = createContext<CveViewState | null>(null);

/** State navigasi CVE Tracker (view + sub-view) di React state, bukan URL: header halaman
 * (layout) perlu mengganti judul, dan Empty A membuka picker Monitored Tech dari sub-view lain. */
export function CveViewProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<CveView>("cves");
  const [subview, setSubview] = useState<CveSubview>("cves");
  const [addFromCatalogRequested, setRequested] = useState(false);

  const requestAddFromCatalog = useCallback(() => {
    setRequested(true);
    setView("cves");
    setSubview("monitored");
  }, []);
  const clearAddFromCatalog = useCallback(() => setRequested(false), []);
  const [pendingSearch, setPendingSearch] = useState<string | null>(null);
  const openInTracker = useCallback((search: string) => {
    setPendingSearch(search);
    setView("cves");
    setSubview("cves");
  }, []);
  const clearPendingSearch = useCallback(() => setPendingSearch(null), []);

  const value = useMemo(
    () => ({
      view,
      subview,
      setView,
      setSubview,
      addFromCatalogRequested,
      requestAddFromCatalog,
      clearAddFromCatalog,
      pendingSearch,
      openInTracker,
      clearPendingSearch,
    }),
    [view, subview, addFromCatalogRequested, requestAddFromCatalog, clearAddFromCatalog, pendingSearch, openInTracker, clearPendingSearch],
  );
  return <CveViewContext.Provider value={value}>{children}</CveViewContext.Provider>;
}

export function useCveView(): CveViewState {
  const ctx = useContext(CveViewContext);
  if (!ctx) throw new Error("useCveView harus dipakai di dalam CveViewProvider");
  return ctx;
}
