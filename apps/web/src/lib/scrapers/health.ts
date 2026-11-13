import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { noClientRetry, unwrap } from "@/lib/scrapers/queries";

/** Satu query kesehatan armada scraper (`GET /api/scraper/health`), dipakai `SchedulerStatus`,
 * `HealthSummaryBar`, dan `ScrapersTable`. Dulu `queryFn` yang sama disalin tiga kali; queryKey yang
 * sama tetap membuat TanStack men-dedupe fetch-nya. */
export function useScraperHealth() {
  return useQuery({
    queryKey: ["scrapers", "health"],
    queryFn: async () => {
      return unwrap(await api.GET("/api/scraper/health"), "Could not load scraper health");
    },
    retry: noClientRetry,
    refetchInterval: 60_000,
  });
}

/** Umur tick scheduler untuk kalimat ("never", "45 s", "12 min", "3 h 5 min"); pemanggil menambah "ago". */
export function tickAge(ageS: number | null): string {
  if (ageS === null) return "never";
  if (ageS < 90) return `${Math.round(ageS)} s`;
  const min = Math.round(ageS / 60);
  if (min < 120) return `${min} min`;
  return `${Math.floor(min / 60)} h ${min % 60} min`;
}

/** Urutan tampil masalah scraper: yang rusak dulu, `stale` (belum pernah jalan) terakhir. Kalau abjad,
 * puluhan scraper yang belum pernah jalan menutupi yang benar-benar gagal. */
const PROBLEM_ORDER: Record<string, number> = { dead: 0, degraded: 1, zero_yield: 2, stale: 3 };

export function byProblemSeverity<T extends { id: string; status: string }>(problems: readonly T[]): T[] {
  return [...problems].sort(
    (a, b) => (PROBLEM_ORDER[a.status] ?? 9) - (PROBLEM_ORDER[b.status] ?? 9) || a.id.localeCompare(b.id),
  );
}
