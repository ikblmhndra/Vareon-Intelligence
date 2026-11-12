import { cn } from "@/lib/utils";

interface SparklineProps {
  data: number[];
  className?: string;
  "aria-hidden"?: boolean;
}

/** Garis kecil tanpa sumbu (dipindah apa adanya dari `stat-box.tsx`). Warna lewat `currentColor`, jadi nada
 * diatur dari kelas token di pemanggil (default `text-info`). Dekoratif: angka sebenarnya selalu ada di teks. */
export function Sparkline({ data, className, "aria-hidden": ariaHidden = true }: SparklineProps) {
  const W = 120;
  const H = 36;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const span = Math.max(1, max - min);
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * W).toFixed(1)},${(H - 4 - ((v - min) / span) * (H - 8)).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-hidden={ariaHidden}
      className={cn("shrink-0 text-info", className)}
    >
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
