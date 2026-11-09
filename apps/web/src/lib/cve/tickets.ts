"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { CveTicket } from "@/lib/api/loose-types";
import type { TicketStatus } from "@/lib/cve/labels";

/** `GET /api/cve/tickets`: ticket + ringkasan CVE-nya (field tambahan dibaca view yang butuh). */
export function useCveTickets(params?: { search?: string; status?: string }) {
  const search = params?.search;
  const status = params?.status;
  return useQuery({
    queryKey: ["cve", "tickets", search ?? "", status ?? ""],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/tickets", {
        params: { query: { search: search || undefined, status: status || undefined } },
      });
      if (error) throw error;
      return data as unknown as { tickets: CveTicket[]; total: number };
    },
  });
}

/** Satu ticket per CVE (kunci `cve_id`). */
export function ticketsByCve(tickets: CveTicket[]): Map<string, CveTicket> {
  return new Map(tickets.map((t) => [t.cve_id, t]));
}

/** Status ticket; kosong = "Open" (ticket baru belum diubah analis). */
export function ticketStatusOf(t: CveTicket): TicketStatus {
  return (t.remediation_status || "Open") as TicketStatus;
}
