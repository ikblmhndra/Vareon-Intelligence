"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { tabPillClass } from "@/components/ui/tab-pills";

/** Port `intelSwitchView()` (`intel.js:5-10`) -- legacy nge-switch 11
 * sub-view lewat 1 shell (`['clusters','scores','spikes','mitre',
 * 'attackdb','pir','rfi','threatroom','iocmgmt','campaigns','riskmatrix']`).
 * Keputusan arsitektur Fase 8 #2: `/intelligence` jadi sub-route Next.js
 * BENERAN (deep-link+code-split), bukan client-state tab switcher --
 * nav di bawah cuma nampilin sub-route yang UDAH dibangun (G1: Risk
 * Matrix/Source Reliability/Early Warning), nambah entry tiap G2-G7
 * landing, bukan placeholder buat 8 sub-view yang belum ada. */
const NAV_ITEMS = [
  { href: "/intelligence/risk-matrix", label: "Risk Matrix" },
  { href: "/intelligence/source-reliability", label: "Source Reliability" },
  { href: "/intelligence/early-warning", label: "Early Warning" },
  { href: "/intelligence/pir", label: "PIR" },
  { href: "/intelligence/rfi", label: "RFI" },
  { href: "/intelligence/mitre", label: "MITRE Heatmap" },
  { href: "/intelligence/attack-db", label: "ATT&CK DB" },
  { href: "/intelligence/ioc-management", label: "IOC Management" },
  { href: "/intelligence/threat-actor-room", label: "Threat Actor Room" },
  { href: "/intelligence/campaign-clusters", label: "Campaign Clusters" },
] as const;

export function IntelligenceNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Intelligence sections" className="mb-4 flex gap-1.5 border-b border-border pb-3 overflow-x-auto">
      {NAV_ITEMS.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          aria-current={pathname === item.href ? "page" : undefined}
          className={tabPillClass(pathname === item.href)}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
