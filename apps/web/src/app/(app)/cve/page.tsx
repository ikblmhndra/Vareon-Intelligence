"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { CveCoreView } from "@/components/cve/cve-core-view";
import { CveTicketingView } from "@/components/cve/cve-ticketing-view";
import { TechStackPanel } from "@/components/cve/techstack-panel";
import { PkgVulnView } from "@/components/cve/pkgvuln/pkgvuln-view";

const VIEWS = [
  { id: "cves", label: "CVE Tracker" },
  { id: "pkgvuln", label: "Package Vulnerabilities" },
] as const;
type View = (typeof VIEWS)[number]["id"];

const CVE_SUBVIEWS = [
  { id: "cves", label: "CVEs" },
  { id: "ticketing", label: "Ticketing" },
  { id: "techstack", label: "Tech Stack" },
] as const;
type CveSubview = (typeof CVE_SUBVIEWS)[number]["id"];

/**
 * Port `tab_cvetracker.html`+`cve.js`+`techstack.js`+`pkgvuln.js`.
 * Area terbesar tunggal Fase 8 (Grup E) -- 2 level switch: view
 * (CVEs|Package Vulnerabilities, `cveSwitchView`) dan, di dalam CVEs,
 * sub-view (CVEs|Tech Stack, `cveSwitchTSVSubview`). Backend (ticket
 * workflow, 3 lookup eksternal, techstack, pkgvuln) SUDAH lengkap
 * diporting sejak Fase 7 -- ini murni build frontend.
 */
export default function CveTrackerPage() {
  const [view, setView] = useState<View>("cves");
  const [subview, setSubview] = useState<CveSubview>("cves");

  return (
    <div>
      <div className="mb-4 flex gap-1.5 border-b border-border pb-3 overflow-x-auto">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            onClick={() => setView(v.id)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
              view === v.id
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {v.label}
          </button>
        ))}
      </div>

      {view === "cves" ? (
        <div>
          <div className="mb-3 flex gap-1.5 overflow-x-auto">
            {CVE_SUBVIEWS.map((s) => (
              <button
                key={s.id}
                onClick={() => setSubview(s.id)}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors duration-200",
                  subview === s.id
                    ? "border-primary/30 bg-primary/10 text-primary"
                    : "border-border bg-surface text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
          {subview === "cves" ? <CveCoreView /> : subview === "ticketing" ? <CveTicketingView /> : <TechStackPanel />}
        </div>
      ) : (
        <PkgVulnView />
      )}
    </div>
  );
}
