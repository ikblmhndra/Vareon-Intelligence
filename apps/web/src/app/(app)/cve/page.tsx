"use client";

import { Suspense } from "react";

import { Notice } from "@/components/ui/notice";
import { TabPills } from "@/components/ui/tab-pills";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { useAuth } from "@/components/providers/auth-provider";
import { useCan } from "@/lib/auth/permissions";
import { ticketStatusOf, useCveTickets } from "@/lib/cve/tickets";
import { useCveView, type CveSubview } from "@/lib/cve/view-state";
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

const CVE_SUBVIEWS = [
  { value: "cves", label: "CVEs" },
  { value: "dashboard", label: "Dashboard" },
  { value: "ticketing", label: "Ticketing" },
  { value: "monitored", label: "Monitored Tech" },
  { value: "alltech", label: "All Tech" },
  { value: "cvedb", label: "CVE DB" },
] as const satisfies readonly { value: CveSubview; label: string }[];

/**
 * Port `tab_cvetracker.html`+`cve.js`+`techstack.js`+`pkgvuln.js`.
 * Area terbesar tunggal Fase 8 (Grup E) -- 2 level switch: view
 * (CVEs|Package Vulnerabilities, `cveSwitchView`) dan, di dalam CVEs,
 * sub-view (CVEs|Dashboard|Ticketing|Monitored Tech|All Tech|CVE DB; tiga terakhir = katalog tech #19). Backend (ticket
 * workflow, 3 lookup eksternal, techstack, pkgvuln) SUDAH lengkap
 * diporting sejak Fase 7 -- ini murni build frontend.
 */
export default function CveTrackerPage() {
  const { view, setView, subview, setSubview } = useCveView();
  const can = useCan();
  const { user } = useAuth();
  const canTicket = can("manage_cve");
  // Dipasang di level halaman supaya hitungan tab Ticketing tetap hangat.
  const tickets = useCveTickets();
  const openCount = tickets.data
    ? tickets.data.tickets.filter((t) => ticketStatusOf(t) === "Open").length
    : undefined;

  const subviews = CVE_SUBVIEWS.filter((s) => s.value !== "ticketing" || canTicket).map((s) =>
    s.value === "ticketing" ? { ...s, count: openCount } : s,
  );
  // Role tanpa manage_cve tidak punya tab Ticketing: jatuh ke CVEs.
  const active: CveSubview = subview === "ticketing" && !canTicket ? "cves" : subview;

  return (
    <div>
      <UnderlineTabs aria-label="CVE sections" className="mb-4" items={VIEWS} value={view} onChange={setView} />

      {view === "cves" ? (
        <div>
          <TabPills aria-label="CVE views" className="mb-3" items={subviews} value={active} onChange={setSubview} />
          {!canTicket && (
            <Notice tone="info" title="Ticketing is managed by the SOC." className="mb-3">
              Your role ({user?.role}) can read CVEs and the dashboard. Acknowledge, ticket and false-positive
              actions are hidden.
            </Notice>
          )}
          {active === "cves" ? (
            // `useSearchParams` di CveCoreView butuh Suspense supaya halaman tetap bisa di-prerender.
            <Suspense>
              <CveCoreView />
            </Suspense>
          ) : active === "dashboard" ? (
            <CveDashboardView />
          ) : active === "ticketing" ? (
            <CveTicketingView />
          ) : active === "monitored" ? (
            <MonitoredTechPanel />
          ) : active === "alltech" ? (
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
