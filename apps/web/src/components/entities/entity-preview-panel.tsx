"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { otherAliases } from "@/components/entities/entity-action-utils";
import { heroLinkClass, HeroPanel } from "@/components/ui/hero-panel";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { entityTypeMeta } from "@/lib/entities/types";
import { fmtMonthYear, fmtShortDate } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";

type EntityListItem = components["schemas"]["EntityListItem"];

/** Isi halaman entity, statis: pratinjau hanya menunjuk, tidak menghitung. */
const ON_THE_PAGE = [
  "Overview",
  "Relationships",
  "Stories",
  "Indicators",
  "CVEs",
  "Timeline",
  "ATT&CK",
  "Hunt",
] as const;

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-hero-panel px-3 py-2">
      <p className="text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">{label}</p>
      <p className="font-heading text-lg font-semibold text-hero-foreground">{value}</p>
    </div>
  );
}

/**
 * Pratinjau entity terpilih di daftar (spec 2b 6.7). Angka dan alias dari baris daftar (sudah ada);
 * detail `GET /api/entities/{id}` hanya untuk ringkasan profil AI dan kelas identity. Kunci query
 * `["entity", id]` dan bentuk hasilnya sama dengan `EntityView`, jadi cache dipakai bersama.
 */
export function EntityPreviewPanel({ item }: { item: EntityListItem }) {
  const detail = useQuery({
    queryKey: ["entity", item.id],
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities/{entity_id}", {
        params: { path: { entity_id: item.id } },
      });
      if (data) return data;
      if (response.status === 404) return null;
      throw new Error(`entity gagal (${response.status})`, { cause: response.status });
    },
  });
  const d = detail.data ?? null;
  const meta = entityTypeMeta(item.type, d?.identity_class);
  const aliases = otherAliases(item.aliases, item.name, item.external_id);
  const isActor = item.type === "intrusion-set";

  return (
    <HeroPanel
      kicker={`${meta.label}${item.external_id ? ` · ${item.external_id}` : ""}`}
      title={item.name}
      footer={
        <Link href={`/intelligence/entities/${item.id}`} className={heroLinkClass}>
          Open entity page →
        </Link>
      }
    >
      {aliases.length > 0 && <p>Also known as {aliases.join(", ")}</p>}

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Tile label="Mentions 30 d" value={String(item.mentions_30d)} />
        <Tile label="90 d" value={String(item.mentions_90d)} />
        <Tile label="First seen" value={fmtMonthYear(item.first_seen)} />
      </div>

      {isActor && (
        <div className="mt-3">
          <p className="text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">
            AI profile{d?.profile_generated_at ? ` · generated ${fmtShortDate(d.profile_generated_at)}` : ""}
          </p>
          {detail.isPending ? (
            <Skeleton role="status" aria-label="Loading profile" className="mt-2 h-4 w-3/4" />
          ) : d?.profile_summary ? (
            <p className="mt-1 text-hero-foreground">{d.profile_summary}</p>
          ) : (
            <p className="mt-1">No AI profile yet</p>
          )}
        </div>
      )}

      <p className="mt-3 text-xs">
        {item.source} · first seen {fmtShortDate(item.first_seen)}
      </p>

      <div className="mt-3">
        <p className="text-2xs font-bold tracking-[0.12em] text-hero-eyebrow uppercase">On the entity page</p>
        <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
          {ON_THE_PAGE.map((s) => (
            <li key={s} className="before:mr-1.5 before:content-['•']">
              {s}
            </li>
          ))}
        </ul>
      </div>
    </HeroPanel>
  );
}
