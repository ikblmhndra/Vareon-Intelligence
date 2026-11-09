import type { components } from "@/lib/api/schema";

// Label tampilan CVE Tracker (spec 2a). Nilai kunci = kode mesin dari API.

export const CHECK_SOURCE_LABEL = {
  new_cve: "NVD / Tenable feed",
  mirror: "CVE List V5 mirror",
} as const;

export type FpReason = components["schemas"]["FalsePositiveBody"]["reason"];

export const FP_REASON_LABEL: Record<FpReason, string> = {
  not_in_stack: "Product not in our stack",
  version_not_affected: "Version not affected",
  component_not_exposed: "Component not exposed",
  duplicate: "Duplicate",
  other: "Other",
};

export const TICKET_STATUSES = [
  "Open",
  "In Progress",
  "Resolved",
  "Risk Accepted",
  "Closed",
] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

export const ACTIVE_EXPLOITATION_VALUES = [
  "Active Exploitation",
  "Limited Exploitation",
  "No Known Exploitation",
  "Unknown/Under Investigation",
] as const;

export const RISK_ACCEPTANCE_VALUES = [
  "Risk Acceptance",
  "Risk Mitigation",
  "Risk Transfer",
  "No Risk (Not Affected)",
] as const;

export const HOSTING_LABEL = { on_prem: "on-prem", cloud: "cloud", saas: "SaaS" } as const;

/** Label sumber PoC untuk chip. Data backend: Exploit-DB ditulis `source="exploit-db"` (hyphen), PoC GitHub
 * menaruh LOGIN PEMILIK repo di `source` (jadi dikenali dari URL), dan belum ada PoC Nuclei di backend
 * (poc_type hanya "poc" | "exploit"); cabang Nuclei dari URL `nuclei-templates` disiapkan untuk nanti.
 * Selain itu: `source` mentah. */
export function pocSourceLabel(poc: { source?: string; url?: string; poc_type?: string }): string {
  const url = (poc.url ?? "").toLowerCase();
  if (poc.source === "exploit-db" || url.includes("exploit-db.com")) return "Exploit-DB";
  if (url.includes("nuclei-templates")) return "Nuclei";
  if (url.includes("github.com")) return "GitHub";
  return poc.source ?? "";
}
