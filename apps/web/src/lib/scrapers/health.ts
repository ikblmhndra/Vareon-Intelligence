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
