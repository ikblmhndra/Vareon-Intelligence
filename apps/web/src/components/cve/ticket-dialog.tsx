"use client";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { CveTicket } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";

import { TicketForm } from "./ticket-form";

type CveOut = components["schemas"]["CveOut"];

interface TicketDialogProps {
  cve: CveOut;
  ticket: CveTicket | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Dialog "Create/Edit ticket for {CVE}" (spec 2a 6.9): memakai `TicketForm` varian dialog; footer-nya (Cancel +
 * Create/Save ticket, "Ticket ID is assigned on save.") dirender form itu sendiri. */
export function TicketDialog({ cve, ticket, open, onOpenChange }: TicketDialogProps) {
  const isNew = !ticket?.ticket_id;
  const sev = cve.cve_severity ? `${cve.cve_severity.toUpperCase()} ${cve.cve_score}` : String(cve.cve_score);
  const subtitle = [cve.tech, sev, cve.cisa_kev ? "on CISA KEV" : null].filter(Boolean).join(" - ");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isNew ? "Create ticket for " : "Edit ticket for "}
            <span className="font-code">{cve.cve_id}</span>
          </DialogTitle>
          <DialogDescription>{subtitle}</DialogDescription>
        </DialogHeader>
        <TicketForm
          cveId={cve.cve_id}
          cve={cve}
          ticket={ticket}
          variant="dialog"
          onCancel={() => onOpenChange(false)}
          onSaved={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}
