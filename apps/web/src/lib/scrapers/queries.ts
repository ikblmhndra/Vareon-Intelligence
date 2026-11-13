import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { isClientError } from "@/lib/exec/query";
import { apiErrorMessage } from "@/lib/recap/quality";

/** Lempar galat bila respons bukan 2xx (body 502 kosong lolos `if (error)`) atau tanpa data; status
 * dibawa di `cause` supaya `isClientError` bisa menolak retry 4xx. */
export function unwrap<T>(r: { data?: T; error?: unknown; response: Response }, fallback: string): T {
  if (!r.response.ok || r.data === undefined) {
    const detail = r.error ? apiErrorMessage(r.error, r.response.status) : "";
    throw new Error(detail || fallback, { cause: r.response.status });
  }
  return r.data;
}

/** `retry` semua query halaman ops: dua kali ulang, tidak untuk 4xx. */
export const noClientRetry = (n: number, e: unknown) => n < 2 && !isClientError(e);

export function writeErrorMessage(e: unknown): string {
  if (e instanceof Error && e.cause === 403) return "You need the manage_scraper permission";
  return e instanceof Error ? e.message : String(e);
}

/** Daftar scraper; "sekarang" dibaca di dalam queryFn (bukan saat render) untuk hitung umur. */
export function useScraperList() {
  return useQuery({
    queryKey: ["scrapers", "list"],
    queryFn: async () => ({
      ...unwrap(await api.GET("/api/scraper"), "Could not load the scraper list"),
      nowMs: Date.now(),
    }),
    retry: noClientRetry,
    refetchInterval: 60_000,
  });
}

export function useScraperDetail(id: string | null) {
  return useQuery({
    queryKey: ["scrapers", id, "detail"],
    enabled: id !== null,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/scraper/{scraper_id}", { params: { path: { scraper_id: id ?? "" } } }),
        "Could not load the scraper",
      ),
    retry: noClientRetry,
  });
}

export function useEnableScraper() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/enable", { params: { path: { scraper_id: id } } }),
        "Enable failed",
      );
      return id;
    },
    onSuccess: (id) => {
      toast.success(`${id} enabled`);
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
    },
    onError: (e: Error) => toast.error(`Enable failed: ${writeErrorMessage(e)}`),
  });
}
