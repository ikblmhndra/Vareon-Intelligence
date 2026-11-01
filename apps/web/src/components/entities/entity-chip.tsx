"use client";

import { useState } from "react";
import Link from "next/link";

import { entityHref, entityTypeMeta } from "@/lib/entities/types";
import { cn } from "@/lib/utils";

export type EntityChipItem = { type: string; name: string; id?: number | null; label?: string };

/** Teks yang diawali id (T1566.001, CVE-2024-3400) ditampilkan dengan font kode. */
const ID_PREFIX = /^(T\d{4}(\.\d{3})?|CVE-\d{4}-\d+)\b/i;

/** Label chip untuk EntityRef: teknik dengan external_id tampil "T1566 Phishing" (id font-code, nama biasa). */
export function refLabel(ref: { type: string; name: string; external_id?: string | null }) {
  return ref.type === "attack-pattern" && ref.external_id ? `${ref.external_id} ${ref.name}` : undefined;
}

/**
 * Satu komponen untuk semua nama entity: ikon + warna per tipe, satu baris, label terpotong
 * dengan elipsis, nama lengkap di `aria-label`. `label` menimpa teks tampilan (mis. "T1566 Phishing").
 */
export function EntityChip({
  type,
  name,
  id,
  label,
  className,
}: EntityChipItem & { className?: string }) {
  // `type` boleh daftar ("malware,tool", untuk resolve): ikon/label dari tipe pertama.
  const meta = entityTypeMeta(type.split(",")[0]);
  const text = label ?? name;
  // Hanya id di depan ("T1566", "CVE-...") yang font-code; sisa teks (nama teknik) tetap biasa.
  const idMatch = ID_PREFIX.exec(text);
  const idPart = idMatch ? idMatch[0] : null;
  const rest = idPart ? text.slice(idPart.length) : text;
  const wholeCode = !idPart && type === "vulnerability";
  return (
    <Link
      href={entityHref({ id, type, name })}
      aria-label={`${meta.label} ${text}`}
      title={text}
      className={cn(
        "inline-flex h-6 min-h-6 max-w-64 min-w-0 items-center gap-1.5 rounded-lg border border-border bg-background px-2 text-xs whitespace-nowrap text-foreground transition-colors outline-none hover:border-primary focus-visible:ring-3 focus-visible:ring-focus",
        className,
      )}
    >
      <meta.Icon aria-hidden className={cn("size-3.5 shrink-0", meta.colorClass)} />
      <span className={cn("min-w-0 truncate", wholeCode && "font-code")}>
        {idPart && <span className="font-code">{idPart}</span>}
        {rest}
      </span>
    </Link>
  );
}

/** Daftar chip; sisa di atas `max` disembunyikan di balik tombol "+N more" yang membuka di tempat. */
export function EntityChipList({ items, max = 6 }: { items: EntityChipItem[]; max?: number }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? items : items.slice(0, max);
  const hidden = items.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((it) => (
        <EntityChip key={`${it.type}:${it.id ?? ""}:${it.name}`} {...it} />
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          aria-label={`Show ${hidden} more entities`}
          className="inline-flex h-6 min-h-6 items-center rounded-lg px-2 text-xs font-medium text-primary-text outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
        >
          +{hidden} more
        </button>
      )}
    </div>
  );
}
