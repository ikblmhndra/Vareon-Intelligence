import type { Permission } from "@/lib/api/loose-types";

/** Urutan & pengelompokan sama dengan `ALL_PERMISSIONS` di `services/roles.py` (30 kunci). */
export const PERMISSION_GROUPS: readonly { heading: string; keys: readonly string[] }[] = [
  {
    heading: "NEWS AND INTELLIGENCE",
    keys: [
      "view_news", "export_data", "view_intel", "manage_intel", "view_ta", "manage_entities",
      "view_ioc", "manage_ioc", "view_cve", "manage_cve", "send_cve_email", "view_stix",
      "wisemap_access",
    ],
  },
  { heading: "OPERATIONS", keys: ["manage_rfi", "manage_pir"] },
  {
    heading: "COMMUNICATION",
    keys: ["view_newsletter", "manage_newsletter", "view_tweets", "manage_tweets"],
  },
  {
    heading: "PLATFORM ADMINISTRATION",
    keys: [
      "view_audit_log", "manage_users", "reset_password", "manage_clients", "manage_policy",
      "manage_roles", "view_ops", "manage_scraper", "manage_sources", "manage_changelog",
      "manage_api_tokens",
    ],
  },
];

/** Kelompokkan izin dari API (urutan API dijaga); grup kosong dibuang, kunci asing masuk "OTHER". */
export function groupPermissions(perms: Permission[]): { heading: string; items: Permission[] }[] {
  const known = new Set(PERMISSION_GROUPS.flatMap((g) => g.keys));
  const groups = PERMISSION_GROUPS.map((g) => ({
    heading: g.heading,
    items: perms.filter((p) => g.keys.includes(p.key)),
  }));
  groups.push({ heading: "OTHER", items: perms.filter((p) => !known.has(p.key)) });
  return groups.filter((g) => g.items.length > 0);
}
