import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface StatBoxProps {
  label: string;
  value: number | string | undefined;
  sub: ReactNode;
  className?: string;
  /** Deret angka untuk sparkline kecil di kanan nilai. */
  spark?: number[];
  /** Tanpa permukaan sendiri: dipakai di dalam panel KPI yang sudah raised (satu kotak, bukan lima). */
  flat?: boolean;
}

/** Port `.dash-stat-box` dari `newsroom.html`/`custom.css` lama. */
export function StatBox({ label, value, sub, className, spark, flat }: StatBoxProps) {
  return (
    <div className={cn("px-5 py-4", !flat && "surface-raised rounded-2xl", className)}>
      <div className="text-sm font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-end justify-between gap-3">
        {/* Nilai teks panjang (mis. nama sektor "Information Technology & Software") tidak muat di text-4xl. */}
        <div
          className={cn(
            "font-heading font-bold tracking-tight text-foreground tabular-nums",
            typeof value === "string" && value.length > 12 ? "min-w-0 text-xl leading-tight break-words" : "text-4xl",
          )}
        >
          {typeof value === "number" ? value.toLocaleString() : (value ?? "—")}
        </div>
        {spark && spark.length > 1 && <Sparkline data={spark} />}
      </div>
      <div className="mt-1 text-sm text-muted-foreground">{sub}</div>
    </div>
  );
}

/** Selisih vs periode sebelumnya buat `StatBox.sub`. `prev` null/undefined (all-time:
 * gak ada periode sebelumnya) -> gak render apa-apa. Netral (bukan merah/hijau):
 * naik/turun jumlah artikel gak otomatis baik atau buruk. */
export function Delta({ value, prev, label }: { value: number; prev: number | null | undefined; label: string }) {
  if (prev == null) return null;
  const diff = value - prev;
  let text: string;
  if (diff === 0) text = `no change vs prev ${label}`;
  else {
    const arrow = diff > 0 ? "▲" : "▼";
    // Pembanding kecil (< 10) -> selisih absolut: "▲ 28400%" dari 3 artikel ke 855 menyesatkan.
    const amount =
      prev < 10 ? `${diff > 0 ? "+" : "-"}${Math.abs(diff).toLocaleString()}` : `${Math.abs(Math.round((diff / prev) * 100))}%`;
    text = `${arrow} ${amount} vs prev ${label}`;
  }
  return <span> · {text}</span>;
}

/** Judul section (`.dash-section-label` lama). `<h2>`: di bawah `<h1>` PageHeader. */
export function DashboardSectionLabel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={cn(
        "mt-10 mb-4 font-heading text-xl font-bold tracking-tight text-foreground",
        className,
      )}
    >
      {children}
    </h2>
  );
}

/** Kartu pembungkus satu chart (`.chart-card` lama). `className` untuk posisi di grid (col-span). */
export function ChartCard({
  title,
  height,
  note,
  children,
  className,
}: {
  title: string;
  height: number;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("surface-raised rounded-2xl p-5", className)}>
      <CardHeader title={title} note={note} />
      <div style={{ height }}>{children}</div>
    </div>
  );
}

/** Kartu untuk konten berukuran bebas (peta, daftar) -- tanpa tinggi tetap. `flat` = daftar
 * tanpa kotak (hierarki: chart/peta raised, daftar angka datar) dengan padding sama supaya judulnya sejajar. */
export function MapCard({
  title,
  note,
  children,
  className,
  flat,
}: {
  title: string;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
  flat?: boolean;
}) {
  return (
    <div className={cn("p-5", !flat && "surface-raised rounded-2xl", className)}>
      <CardHeader title={title} note={note} />
      {children}
    </div>
  );
}

/** `note` = catatan penyebut ("dari N artikel") di bawah judul kartu. */
function CardHeader({ title, note }: { title: string; note?: ReactNode }) {
  return (
    <div className="mb-3">
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {note && <div className="mt-0.5 text-xs text-muted-foreground">{note}</div>}
    </div>
  );
}

function Sparkline({ data }: { data: number[] }) {
  const W = 120;
  const H = 36;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = Math.max(1, max - min);
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * W).toFixed(1)},${(H - 4 - ((v - min) / span) * (H - 8)).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden className="shrink-0 text-info">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
