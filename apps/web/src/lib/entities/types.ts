import {
  Building2,
  Bug,
  Crosshair,
  Flag,
  Globe,
  Landmark,
  ShieldAlert,
  Skull,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/** Tipe entity (STIX 2.1) yang dikenal API `/api/entities`. */
export type EntityType =
  | "intrusion-set"
  | "malware"
  | "tool"
  | "attack-pattern"
  | "vulnerability"
  | "campaign"
  | "identity"
  | "location";

/** Tab di daftar entity, urutan sesuai spec. `identity` dibelah lewat `identity_class`. */
export const ENTITY_TABS: readonly {
  key: string;
  label: string;
  types: EntityType[];
  identityClass?: "class" | "organization";
}[] = [
  { key: "actors", label: "Actors", types: ["intrusion-set"] },
  { key: "malware", label: "Malware & tools", types: ["malware", "tool"] },
  { key: "techniques", label: "Techniques", types: ["attack-pattern"] },
  { key: "vulnerabilities", label: "Vulnerabilities", types: ["vulnerability"] },
  { key: "campaigns", label: "Campaigns", types: ["campaign"] },
  { key: "sectors", label: "Sectors", types: ["identity"], identityClass: "class" },
  { key: "countries", label: "Countries", types: ["location"] },
  { key: "victims", label: "Victims", types: ["identity"], identityClass: "organization" },
];

/** Label, ikon, dan warna token per tipe; `identity` + `identityClass=organization` = korban. */
export function entityTypeMeta(
  type: string,
  identityClass?: string | null,
): { label: string; Icon: LucideIcon; colorClass: string } {
  switch (type) {
    case "intrusion-set":
      return { label: "Actor", Icon: Skull, colorClass: "text-chart-4" };
    case "malware":
      return { label: "Malware", Icon: Bug, colorClass: "text-chart-3" };
    case "tool":
      return { label: "Tool", Icon: Wrench, colorClass: "text-chart-3" };
    case "attack-pattern":
      return { label: "Technique", Icon: Crosshair, colorClass: "text-chart-1" };
    case "vulnerability":
      return { label: "Vulnerability", Icon: ShieldAlert, colorClass: "text-severity-critical-text" };
    case "campaign":
      return { label: "Campaign", Icon: Flag, colorClass: "text-chart-9" };
    case "identity":
      return identityClass === "organization"
        ? { label: "Victim", Icon: Building2, colorClass: "text-chart-2" }
        : { label: "Sector", Icon: Landmark, colorClass: "text-chart-2" };
    case "location":
      return { label: "Country", Icon: Globe, colorClass: "text-chart-5" };
    default:
      return { label: type, Icon: Flag, colorClass: "text-muted-foreground" };
  }
}

/**
 * Tujuan klik chip: ada id = langsung ke halaman entity; hanya nama = lewat resolve yang
 * mencari id-nya lalu redirect. `URLSearchParams` meng-encode nama aneh (`#play`, `A/B`).
 */
export function entityHref(ref: { id?: number | null; type: string; name: string }): string {
  if (ref.id != null) return `/intelligence/entities/${ref.id}`;
  return `/intelligence/entities/resolve?${new URLSearchParams({ type: ref.type, name: ref.name })}`;
}
