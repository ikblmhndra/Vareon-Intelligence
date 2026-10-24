"use client";

import { Suspense, useState } from "react";

import { TabPills } from "@/components/ui/tab-pills";
import { CveCoreView } from "@/components/cve/cve-core-view";
import { CveDashboardView } from "@/components/cve/cve-dashboard-view";
import { CveTicketingView } from "@/components/cve/cve-ticketing-view";
import { AllTechView } from "@/components/cve/all-tech-view";
import { CveDbView } from "@/components/cve/cve-db-view";
import { MonitoredTechPanel } from "@/components/cve/monitored-tech-panel";
import { PkgVulnView } from "@/components/cve/pkgvuln/pkgvuln-view";

const VIEWS = [
  { value: "cves", label: "CVE Tracker" },
  { value: "pkgvuln", label: "Package Vulnerabilities" },
] as const;
type View = (typeof VIEWS)[number]["value"];

const CVE_SUBVIEWS = [
  { value: "cves", label: "CVEs" },
  { value: "dashboard", label: "Dashboard" },
  { value: "ticketing", label: "Ticketing" },
  { value: "monitored", label: "Monitored Tech" },
  { value: "alltech", label: "All Tech" },
  { value: "cvedb", label: "CVE DB" },
] as const;
type CveSubview = (typeof CVE_SUBVIEWS)[number]["value"];

/**
 * Port `tab_cvetracker.html`+`cve.js`+`techstack.js`+`pkgvuln.js`.
 * Area terbesar tunggal Fase 8 (Grup E) -- 2 level switch: view
 * (CVEs|Package Vulnerabilities, `cveSwitchView`) dan, di dalam CVEs,
 * sub-view (CVEs|Dashboard|Ticketing|Monitored Tech|All Tech|CVE DB; tiga terakhir = katalog tech #19). Backend (ticket
 * workflow, 3 lookup eksternal, techstack, pkgvuln) SUDAH lengkap
 * diporting sejak Fase 7 -- ini murni build frontend.
 */
export default function CveTrackerPage() {
  const [view, setView] = useState<View>("cves");
  const [subview, setSubview] = useState<CveSubview>("cves");

  return (
    <div>
      <TabPills aria-label="CVE sections" className="mb-4 border-b border-border pb-3" items={VIEWS} value={view} onChange={setView} />

      {view === "cves" ? (
        <div>
          <TabPills aria-label="CVE views" className="mb-3" items={CVE_SUBVIEWS} value={subview} onChange={setSubview} />
          {subview === "cves" ? (
            // `useSearchParams` di CveCoreView butuh Suspense supaya halaman tetap bisa di-prerender.
            <Suspense>
              <CveCoreView />
            </Suspense>
          ) : subview === "dashboard" ? (
            <CveDashboardView />
          ) : subview === "ticketing" ? (
            <CveTicketingView />
          ) : subview === "monitored" ? (
            <MonitoredTechPanel />
          ) : subview === "alltech" ? (
            <AllTechView />
          ) : (
            <CveDbView />
          )}
        </div>
      ) : (
        <PkgVulnView />
      )}
    </div>
  );
}
