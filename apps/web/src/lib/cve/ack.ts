"use client";

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { AckStatusMap } from "@/lib/api/loose-types";

/** `GET /api/cve/ack-statuses`: `{cve_id: username}` untuk CVE yang sudah di-acknowledge. */
export function useCveAckStatuses() {
  return useQuery({
    queryKey: ["cve", "ack-statuses"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/ack-statuses");
      if (error) throw error;
      return data as AckStatusMap;
    },
  });
}

/** Aksi pada CVE (acknowledge, FP, ticket) membuat daftar, tile, badge ACK, ticket, dan dashboard basi. */
export function invalidateCveViews(queryClient: QueryClient, cveId?: string) {
  const keys: unknown[][] = [
    ["cve", "list"],
    ["cve", "stats"],
    ["cve", "ack-statuses"],
    ["cve", "tickets"],
    ["cve", "dashboard"],
  ];
  if (cveId) keys.push(["cve", "ticket", cveId]);
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
}
