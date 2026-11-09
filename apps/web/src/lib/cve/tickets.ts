"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { CveTicket } from "@/lib/api/loose-types";
import type { TicketStatus } from "@/lib/cve/labels";

/** `GET /api/cve/tickets`: ticket + ringkasan CVE-nya (field tambahan dibaca view yang butuh). */
export function useCveTickets(params?: { search?: string; status?: string; includeFp?: boolean }) {
  const search = params?.search;
  const status = params?.status;
  const includeFp = params?.includeFp ?? false;
  return useQuery({
    queryKey: ["cve", "tickets", search ?? "", status ?? "", includeFp],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/tickets", {
        params: {
          query: { search: search || undefined, status: status || undefined, include_fp: includeFp || undefined },
        },
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

/** Alias status lama di data tersimpan (impor/Excel lama), sama dengan `_STATUS_ALIASES` di
 * `cve_dashboard.py` (kunci huruf kecil). Pemetaan ke 5 status baku: Pending -> Open, Completed -> Resolved,
 * Not Affected/Not Applicable -> Closed. */
const STATUS_ALIASES: Record<string, TicketStatus> = {
  open: "Open",
  pending: "Open",
  "in progress": "In Progress",
  "risk accepted": "Risk Accepted",
  resolved: "Resolved",
  completed: "Resolved",
  closed: "Closed",
  "not affected": "Closed",
  "not applicable": "Closed",
};

/** Status baku dari nilai tersimpan (tanpa membedakan huruf besar/kecil); kosong atau tak dikenal = "Open". */
export function normalizeTicketStatus(raw: string | null | undefined): TicketStatus {
  return STATUS_ALIASES[(raw ?? "").trim().toLowerCase()] ?? "Open";
}

/** Status ticket; kosong = "Open" (ticket baru belum diubah analis), alias lama dinormalkan. */
export function ticketStatusOf(t: CveTicket): TicketStatus {
  return normalizeTicketStatus(t.remediation_status);
}
