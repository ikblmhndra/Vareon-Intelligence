"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { ExecDashboardV2 } from "@/lib/api/loose-types";
import { Skeleton } from "@/components/ui/skeleton";

const DAYS = 30;
const UNSPECIFIED_SECTOR = "General";

/** Band burgundy "Need Attention" di atas Dashboard (Arah A): satu titik
 * fokus berisi hal yang paling mendesak, dibaca dari dashboard exec + stats CVE. */
export function AttentionBand() {
  const exec = useQuery({
    queryKey: ["attention", "exec", DAYS],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/exec/dashboard-v2", {
        params: { query: { days: DAYS, incident_only: true, confirmed_only: false } },
      });
      if (error) throw error;
      return data as unknown as ExecDashboardV2;
    },
  });
  const cve = useQuery({
    queryKey: ["attention", "cve-stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/stats", { params: { query: {} } });
      if (error) throw error;
      return data as unknown as { critical?: number };
    },
  });

  if (exec.isPending || cve.isPending) return <Skeleton className="h-36 w-full rounded-3xl" />;
  if (exec.isError && cve.isError) return null;

  // "General" = artikel tanpa sektor spesifik (62% artikel di prod), bukan sektor. Peringkat
  // `sector_risk_scores` murni volume bulan terakhir (komponen trend/spike butuh >=3-4 bucket
  // bulan, jendela 30 hari paling banyak dua), jadi tanpa penyaringan ini yang menang selalu "General".
  const top = exec.data?.sector_risk_scores.find((s) => s.sector !== UNSPECIFIED_SECTOR);
  // Skor itu cuma volume relatif terhadap sektor terbesar (selalu "General" -> leader 50/100),
  // bukan sinyal risiko. Tampilkan jumlah insiden sektornya saja.
  const topIncidents = top
    ? exec.data?.sector_trend.find((s) => s.sector === top.sector)?.data.reduce((a, b) => a + b, 0)
    : undefined;

  return (
    <section
      aria-label="Need Attention"
      className="grid gap-6 rounded-3xl bg-hero bg-[image:radial-gradient(40rem_16rem_at_100%_0%,var(--hero-glow),transparent_70%)] p-6 text-hero-foreground shadow-md sm:p-8 md:grid-cols-[1.4fr_1fr_1fr_1fr] md:items-center"
    >
      <div>
        <div className="text-xs font-semibold tracking-widest text-hero-eyebrow uppercase">Need Attention</div>
        <div className="mt-2 text-2xl leading-tight font-bold">
          {top ? `Sector ${top.sector} leads in risk` : "Current Risk Summary"}
        </div>
        <div className="mt-1 text-sm text-hero-muted">Period {DAYS} days</div>
      </div>
      <Metric value={cve.data?.critical} label="Critical CVEs (CVSS ≥ 9)" accent />
      <Metric value={topIncidents} label={top ? `Incidents in ${top.sector}` : "Incidents in top sector"} />
      <Metric value={exec.data?.total_incidents} label="Incidents" />
    </section>
  );
}

/** Angka pertama (`accent`) satu langkah lebih besar; dua lainnya diberi garis pemisah tipis di layar lebar,
 * supaya band terbaca sebagai satu pesan utama plus dua pendukung, bukan tiga angka sama besar. */
function Metric({ value, label, suffix, accent }: { value: number | undefined; label: string; suffix?: string; accent?: boolean }) {
  return (
    <div className="md:border-l md:border-hero-foreground/15 md:pl-6">
      <div
        className={`leading-none font-extrabold tracking-tight tabular-nums ${accent ? "text-5xl text-hero-accent" : "text-4xl"}`}
      >
        {value === undefined ? "—" : value.toLocaleString()}
        {value !== undefined && suffix && <span className="text-xl font-semibold text-hero-muted">{suffix}</span>}
      </div>
      <div className="mt-2 text-sm text-hero-muted">{label}</div>
    </div>
  );
}
