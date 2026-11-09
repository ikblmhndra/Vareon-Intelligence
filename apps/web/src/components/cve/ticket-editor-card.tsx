"use client";

import { TicketForm } from "@/components/cve/ticket-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CveTicket } from "@/lib/api/loose-types";
import { fmtShortDate } from "@/lib/format";

interface TicketEditorCardProps {
  ticket: CveTicket & { tech?: string };
  className?: string;
}

/** Kartu editor ticket di kanan Ticketing (spec 2a 6.2): judul = ID ticket, subjudul "{CVE} - {tech} - opened {tgl}".
 * Chip ESCALATION dan toast eskalasi sudah ditangani `TicketForm` varian panel. `key` mengikuti `updated_at` supaya form terisi ulang dari
 * data tersimpan; pilihan baris tetap karena `ticket_id` tidak berubah. */
export function TicketEditorCard({ ticket, className }: TicketEditorCardProps) {
  const subtitle = [ticket.cve_id, ticket.tech, `opened ${fmtShortDate(ticket.opened_at || ticket.created_at)}`]
    .filter(Boolean)
    .join(" - ");
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>
          <h2 className="font-code">{ticket.ticket_id}</h2>
        </CardTitle>
        <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
      </CardHeader>
      <CardContent>
        <TicketForm
          key={`${ticket.ticket_id}:${ticket.updated_at}`}
          cveId={ticket.cve_id}
          ticket={ticket}
          variant="panel"
          onSaved={() => undefined}
        />
      </CardContent>
    </Card>
  );
}
