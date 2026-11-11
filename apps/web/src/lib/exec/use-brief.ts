"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { isClientError } from "@/lib/exec/query";
import type { components } from "@/lib/api/schema";

type ExecBriefFilters = components["schemas"]["ExecBriefFilters"];

const retry = (n: number, e: unknown) => n < 2 && !isClientError(e);

/** Brief tersimpan untuk satu tanggal (`null` = bawaan server: hari ini, atau yang terbaru). */
export function useBrief(selectedDate: string | null) {
  return useQuery({
    queryKey: ["exec", "brief", selectedDate ?? "default"],
    retry,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/exec/brief", {
        params: { query: selectedDate ? { date: selectedDate } : {} },
      });
      if (error) throw new Error(`exec brief gagal (${response.status})`, { cause: response.status });
      return data;
    },
  });
}

export function useBriefDates() {
  return useQuery({
    queryKey: ["exec", "brief-dates"],
    retry,
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/exec/brief/dates");
      if (error) throw new Error(`exec brief dates gagal (${response.status})`, { cause: response.status });
      return data;
    },
  });
}

/** Buat ulang brief hari ini. Ketiga query param dikirim eksplisit (openapi-typescript menandai param
 * ber-default sebagai wajib). Detail 502 dari server jadi `Error.message`; baris lama tidak disentuh. */
export function useGenerateBrief() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (f: ExecBriefFilters) => {
      const { data, error, response } = await api.POST("/api/exec/brief", {
        params: { query: { days: f.days, incident_only: f.incident_only, confirmed_only: f.confirmed_only } },
      });
      if (error) {
        const detail = (error as { detail?: unknown }).detail;
        throw new Error(typeof detail === "string" ? detail : "Brief generation failed. Try again later.", {
          cause: response.status,
        });
      }
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ["exec", "brief"] }),
        qc.invalidateQueries({ queryKey: ["exec", "brief-dates"] }),
      ]);
    },
  });
}
