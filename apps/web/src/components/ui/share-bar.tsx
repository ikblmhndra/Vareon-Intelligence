import { cn } from "@/lib/utils";

// Kelas ditulis utuh supaya Tailwind menemukannya; urutan = seri `--chart-1..10` yang sama dengan grafik.
const SEGMENT = [
  "bg-chart-1",
  "bg-chart-2",
  "bg-chart-3",
  "bg-chart-4",
  "bg-chart-5",
  "bg-chart-6",
  "bg-chart-7",
  "bg-chart-8",
  "bg-chart-9",
  "bg-chart-10",
] as const;

interface ShareBarProps {
  items: { label: string; value: number }[];
  "aria-label"?: string;
}

/** Satu batang 100 % bertumpuk (pengganti doughnut). Warna dari token seri grafik, jadi ikut tema gelap.
 * `role="img"` + `aria-label` memuat "{label} {pct}%" tiap segmen; legenda dirender pemanggil. */
export function ShareBar({ items, "aria-label": ariaLabel }: ShareBarProps) {
  const total = items.reduce((a, b) => a + Math.max(0, b.value), 0);
  const pct = (v: number) => (total > 0 ? Math.round((Math.max(0, v) / total) * 100) : 0);
  const summary = items.map((i) => `${i.label} ${pct(i.value)}%`).join(", ");
  return (
    <div
      role="img"
      aria-label={ariaLabel ? `${ariaLabel}: ${summary}` : summary}
      className="flex h-3 w-full gap-px overflow-hidden rounded-full bg-surface"
    >
      {total > 0 &&
        items.map((it, i) =>
          it.value > 0 ? (
            <span
              key={it.label}
              className={cn("h-full", SEGMENT[i % SEGMENT.length])}
              style={{ width: `${(it.value / total) * 100}%` }}
            />
          ) : null,
        )}
    </div>
  );
}
