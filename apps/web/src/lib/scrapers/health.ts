import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";

/** Satu query kesehatan armada scraper (`GET /api/scraper/health`), dipakai `SchedulerStatus`,
 * `HealthSummaryBar`, dan `ScrapersTable`. Dulu `queryFn` yang sama disalin tiga kali; queryKey yang
 * sama tetap membuat TanStack men-dedupe fetch-nya. */
export function useScraperHealth() {
  return useQuery({
    queryKey: ["scrapers", "health"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/scraper/health");
      if (error) throw error;
      return data;
    },
    refetchInterval: 60_000,
  });
}

/** Urutan tampil masalah scraper: yang rusak dulu, `stale` (belum pernah jalan) terakhir. Kalau abjad,
 * puluhan scraper yang belum pernah jalan menutupi yang benar-benar gagal. */
const PROBLEM_ORDER: Record<string, number> = { dead: 0, degraded: 1, zero_yield: 2, stale: 3 };

export function byProblemSeverity<T extends { id: string; status: string }>(problems: readonly T[]): T[] {
  return [...problems].sort(
    (a, b) => (PROBLEM_ORDER[a.status] ?? 9) - (PROBLEM_ORDER[b.status] ?? 9) || a.id.localeCompare(b.id),
  );
}
