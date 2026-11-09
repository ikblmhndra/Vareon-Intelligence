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

// `cve-detail-modal.tsx` belum punya peta sumber PoC (menampilkan `p.source` mentah), jadi ini peta
// baru; sumber yang tidak dikenal tetap ditampilkan apa adanya oleh pemanggil.
export const POC_SOURCE_LABEL: Record<string, string> = {
  github: "GitHub",
  exploit_db: "Exploit-DB",
};
