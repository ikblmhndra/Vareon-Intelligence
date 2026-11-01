import type { EntityChipItem } from "@/components/entities/entity-chip";
import { countryName } from "@/lib/countries";
import type { components } from "@/lib/api/schema";

type Article = components["schemas"]["ArticleOut"];
type Ref = components["schemas"]["ArticleEntityRef"];

/** Salinan antrean newsletter di localStorage bisa lebih tua dari field `entities`. */
function refs(a: Pick<Article, "entities">): Ref[] {
  return a.entities ?? [];
}

function byName(a: Pick<Article, "entities">, types: string[], name: string): number | undefined {
  const n = name.toLowerCase();
  return refs(a).find((r) => types.includes(r.type) && r.name.toLowerCase() === n)?.id;
}

/** Aktor artikel -> chip; id dicari dari `entities` lewat (intrusion-set, nama), tanpa id = resolve by name. */
export function actorChips(a: Article): EntityChipItem[] {
  return (a.threat_actors ?? []).map((name) => ({
    type: "intrusion-set",
    name,
    id: byName(a, ["intrusion-set"], name),
  }));
}

export function malwareChips(a: Article): EntityChipItem[] {
  return (a.malware ?? []).map((m) => {
    const type = m.kind === "tool" ? "tool" : "malware";
    return { type, name: m.name, id: byName(a, [type], m.name) };
  });
}

export function sectorChips(a: Article): EntityChipItem[] {
  return (a.impacted_industries ?? []).map((name) => ({
    type: "identity",
    name,
    id: byName(a, ["identity"], name),
  }));
}

/** Teknik: id dicari dari `external_id` = id TTP; label = "T1566 Phishing" bila nama ada. */
export function techniqueChips(a: Article, withName = false): EntityChipItem[] {
  return (a.ttps ?? []).map((t) => ({
    type: "attack-pattern",
    name: t.id,
    id: refs(a).find((r) => r.type === "attack-pattern" && r.external_id === t.id)?.id,
    label: withName && t.name ? `${t.id} ${t.name}` : t.id,
  }));
}

/** Negara: kode ISO di ArticleOut; id dari `external_id` (+ role bila field spesifik), label nama negara. */
export function countryChip(a: Pick<Article, "entities">, code: string, role?: string): EntityChipItem {
  const r = refs(a).filter((e) => e.type === "location" && e.external_id === code);
  const hit = (role ? r.find((e) => e.role === role) : undefined) ?? r[0];
  return { type: "location", name: code, id: hit?.id, label: countryName(code) };
}
