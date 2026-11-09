"use client";

import { useId, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { CveTicket } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { parseAffected } from "@/lib/cve/format";
import { normalizeTicketStatus } from "@/lib/cve/tickets";
import {
  ACTIVE_EXPLOITATION_VALUES,
  RISK_ACCEPTANCE_VALUES,
  TICKET_STATUSES,
} from "@/lib/cve/labels";
import { daysUntil, fmtShortDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type CveOut = components["schemas"]["CveOut"];
type CveTicketSaveOut = components["schemas"]["CveTicketSaveOut"];
type CveTicketBody = components["schemas"]["CveTicketBody"];

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const EMAIL_ERROR = "Enter a full email address, for example name@example.com.";
const NONE = "__none__";
const PLAN_WARN_DAYS = 7;

/** Toast hasil eskalasi dari respons `PUT /ticket` (D25). `lead` = nama/email lead tim bila diketahui. */
export function escalationToast(r: CveTicketSaveOut, team: string, lead?: string): void {
  switch (r.escalation) {
    case "queued":
      toast.success(lead ? `Draft email to ${lead} requested` : "Escalation draft requested");
      break;
    case "no_lead":
      toast.warning(`Escalation saved, but ${team || "the owner team"} has no lead email, so no draft was created`);
      break;
    case "failed":
      toast.error("Ticket saved, but the escalation draft could not be queued. Try saving again later.");
      break;
    default:
      break;
  }
}

interface TicketFormProps {
  cveId: string;
  cve?: CveOut;
  ticket: CveTicket | null;
  variant: "dialog" | "panel";
  onSaved: (r: CveTicketSaveOut) => void;
  readOnly?: boolean;
  /** Dialog saja: tombol Cancel di footer. */
  onCancel?: () => void;
}

/** 422 FastAPI: `detail` berupa daftar `{loc, msg}`; true bila galatnya menunjuk ke `field`. */
function hasFieldError(error: unknown, field: string): boolean {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return Array.isArray(detail) && detail.some((d) => Array.isArray((d as { loc?: unknown[] }).loc) && (d as { loc: unknown[] }).loc.includes(field));
}

function errorText(error: unknown): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? "").filter(Boolean).join("; ");
  return "Request failed";
}

/** Form ticket bersama (dialog Create/Edit dan editor panel Ticketing, spec 2a 6.2/6.9). State controlled;
 * pemanggil memberi `key` bila `ticket` berganti. Field asal CVE (asset/version) diprefill dari data CVE selama
 * kosong di ticket, sama seperti export Excel. Bagian Closure hanya tampil saat status Resolved/Closed (D12). */
export function TicketForm({ cveId, cve, ticket, variant, onSaved, readOnly, onCancel }: TicketFormProps) {
  const queryClient = useQueryClient();
  const uid = useId();
  const isNew = !ticket?.ticket_id;

  const affected = cve ? parseAffected(cve.affected) : [];
  const [v, setV] = useState({
    affected_asset: ticket?.affected_asset || [...new Set(affected.map((a) => a.product))].join(", "),
    affected_version: ticket?.affected_version || affected.map((a) => a.constraint).filter(Boolean).join(", "),
    fixed_version: ticket?.fixed_version ?? "",
    asset_owner: ticket?.asset_owner ?? "",
    owner_email: ticket?.owner_email ?? "",
    owner_team: ticket?.owner_team ?? "",
    active_exploitation: ticket?.active_exploitation ?? "",
    remediation_date_plan: ticket?.remediation_date_plan ?? "",
    remediation_status: normalizeTicketStatus(ticket?.remediation_status),
    actual_remediation_date: ticket?.actual_remediation_date ?? "",
    escalation_required: ticket?.escalation_required ?? false,
    comments: ticket?.comments ?? "",
    risk_acceptance: ticket?.risk_acceptance ?? "",
    closure_date: ticket?.closure_date ?? "",
  });
  const [emailError, setEmailError] = useState("");
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof typeof v>(k: K, value: (typeof v)[K]) => setV((p) => ({ ...p, [k]: value }));

  const teamsQuery = useQuery({
    queryKey: ["cve", "teams"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/teams");
      if (error) throw error;
      return data.items;
    },
  });
  const teams = teamsQuery.data ?? [];

  const nextIdQuery = useQuery({
    queryKey: ["cve", "next-ticket-id"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/next-ticket-id");
      if (error) throw error;
      return data.ticket_id;
    },
    enabled: isNew && variant === "dialog",
  });

  // Nama tim dari daftar (aktif) + nilai teks bebas saat ini bila belum ada di daftar.
  const teamNames = teams.filter((t) => t.active).map((t) => t.name);
  if (v.owner_team && !teamNames.includes(v.owner_team)) teamNames.push(v.owner_team);
  const teamItems: Record<string, string> = { [NONE]: "No team", ...Object.fromEntries(teamNames.map((n) => [n, n])) };

  const closed = v.remediation_status === "Resolved" || v.remediation_status === "Closed";
  const planDays = daysUntil(v.remediation_date_plan);
  const planTone =
    planDays === null || closed
      ? null
      : planDays < 0
        ? { cls: "text-destructive-text", text: `Overdue by ${-planDays} ${planDays === -1 ? "day" : "days"}` }
        : planDays <= PLAN_WARN_DAYS
          ? { cls: "text-warning-text", text: planDays === 0 ? "Due today" : `Due in ${planDays} ${planDays === 1 ? "day" : "days"}` }
          : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (readOnly) return;
    const email = v.owner_email.trim();
    // Hanya nilai yang diubah yang dicek: email teks bebas lama yang tidak disentuh tetap boleh disimpan ulang.
    if (email && email !== (ticket?.owner_email ?? "").trim() && !EMAIL_RE.test(email)) {
      setEmailError(EMAIL_ERROR);
      return;
    }
    // Bagian Closure disembunyikan saat belum Resolved/Closed: jangan kirim nilai yang tidak terlihat.
    const body: CveTicketBody = {
      ...v,
      owner_email: email,
      ...(closed ? {} : { risk_acceptance: ticket?.risk_acceptance ?? "", actual_remediation_date: ticket?.actual_remediation_date ?? "", closure_date: ticket?.closure_date ?? "" }),
    };
    setSaving(true);
    try {
      const { data, error } = await api.PUT("/api/cve/{cve_id}/ticket", { params: { path: { cve_id: cveId } }, body });
      if (error || !data) {
        if (hasFieldError(error, "owner_email")) {
          setEmailError(EMAIL_ERROR);
          return;
        }
        throw new Error(errorText(error));
      }
      toast.success("Ticket saved.");
      const team = teams.find((t) => t.name === v.owner_team);
      escalationToast(data, v.owner_team, team?.lead_name || team?.lead_email || undefined);
      // Ticket berubah -> daftar Ticketing, dashboard (status/MTTA/MTTR), badge ACK, dan list CVE ikut basi.
      for (const key of [["cve", "tickets"], ["cve", "ticket", cveId], ["cve", "dashboard"], ["cve", "ack-statuses"], ["cve", "list"]]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      onSaved(data);
    } catch (err) {
      toast.error(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const id = (n: string) => `${uid}-${n}`;
  const ro = !!readOnly;
  const pair = "grid gap-4 lg:grid-cols-2";

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-4" noValidate>
      <div className={pair}>
        <Field label="Affected asset" htmlFor={id("asset")}>
          <Input id={id("asset")} value={v.affected_asset} readOnly={ro} onChange={(e) => set("affected_asset", e.target.value)} />
        </Field>
        <Field label="Owner team" htmlFor={id("team")}>
          <Select
            items={teamItems}
            value={v.owner_team || NONE}
            disabled={ro}
            onValueChange={(val) => val != null && set("owner_team", val === NONE ? "" : val)}
          >
            <SelectTrigger id={id("team")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>No team</SelectItem>
              {teamNames.map((n) => (
                <SelectItem key={n} value={n}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className={pair}>
        <Field label="Affected version" htmlFor={id("aver")}>
          <Input id={id("aver")} value={v.affected_version} readOnly={ro} onChange={(e) => set("affected_version", e.target.value)} />
        </Field>
        <Field label="Fixed version" htmlFor={id("fver")}>
          <Input id={id("fver")} value={v.fixed_version} readOnly={ro} onChange={(e) => set("fixed_version", e.target.value)} />
        </Field>
      </div>
      <div className={pair}>
        <Field label="Asset owner" htmlFor={id("owner")}>
          <Input id={id("owner")} value={v.asset_owner} readOnly={ro} onChange={(e) => set("asset_owner", e.target.value)} />
        </Field>
        <Field label="Owner email" htmlFor={id("email")} error={emailError}>
          <Input
            id={id("email")}
            type="email"
            value={v.owner_email}
            readOnly={ro}
            aria-invalid={!!emailError}
            aria-describedby={fieldDescribedBy(id("email"), { error: emailError })}
            onChange={(e) => {
              set("owner_email", e.target.value);
              setEmailError("");
            }}
          />
        </Field>
      </div>
      <div className={pair}>
        <Field label="Remediation plan date" htmlFor={id("plan")}>
          <Input
            id={id("plan")}
            type="date"
            value={v.remediation_date_plan}
            readOnly={ro}
            aria-describedby={planTone ? id("plan-note") : undefined}
            onChange={(e) => set("remediation_date_plan", e.target.value)}
          />
          {planTone && (
            <p id={id("plan-note")} className={cn("text-xs font-semibold", planTone.cls)}>
              {planTone.text}
            </p>
          )}
        </Field>
        <Field label="Active exploitation" htmlFor={id("exploit")}>
          <Select
            items={{ [NONE]: "Not set", ...Object.fromEntries(ACTIVE_EXPLOITATION_VALUES.map((x) => [x, x])) }}
            value={v.active_exploitation || NONE}
            disabled={ro}
            onValueChange={(val) => val != null && set("active_exploitation", val === NONE ? "" : val)}
          >
            <SelectTrigger id={id("exploit")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>Not set</SelectItem>
              {ACTIVE_EXPLOITATION_VALUES.map((x) => (
                <SelectItem key={x} value={x}>
                  {x}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className="flex flex-col gap-1.5">
        <span id={id("status")} className="text-xs font-semibold text-foreground">
          Remediation status
        </span>
        <div className="overflow-x-auto">
          {ro ? (
            <Chip kind="ticket" value={v.remediation_status} />
          ) : (
            <SegmentedControl
              aria-label="Remediation status"
              size="sm"
              options={TICKET_STATUSES.map((s) => ({ value: s, label: s }))}
              value={v.remediation_status}
              onChange={(s) => set("remediation_status", s)}
            />
          )}
        </div>
      </div>
      <Field label="Comments" htmlFor={id("comments")}>
        <Textarea id={id("comments")} rows={3} value={v.comments} readOnly={ro} onChange={(e) => set("comments", e.target.value)} />
      </Field>
      {closed && (
        <fieldset className="grid gap-4 rounded-lg bg-surface p-4">
          <legend className="px-1 text-2xs font-semibold uppercase text-muted-foreground">Closure</legend>
          <Field label="Risk acceptance" htmlFor={id("risk")}>
            <Select
              items={{ [NONE]: "Not set", ...Object.fromEntries(RISK_ACCEPTANCE_VALUES.map((x) => [x, x])) }}
              value={v.risk_acceptance || NONE}
              disabled={ro}
              onValueChange={(val) => val != null && set("risk_acceptance", val === NONE ? "" : val)}
            >
              <SelectTrigger id={id("risk")} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Not set</SelectItem>
                {RISK_ACCEPTANCE_VALUES.map((x) => (
                  <SelectItem key={x} value={x}>
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <div className={pair}>
            <Field label="Actual remediation date" htmlFor={id("actual")}>
              <Input id={id("actual")} type="date" value={v.actual_remediation_date} readOnly={ro} onChange={(e) => set("actual_remediation_date", e.target.value)} />
            </Field>
            <Field label="Closure date" htmlFor={id("closure")}>
              <Input id={id("closure")} type="date" value={v.closure_date} readOnly={ro} onChange={(e) => set("closure_date", e.target.value)} />
            </Field>
          </div>
        </fieldset>
      )}
      <div className="flex flex-col gap-1">
        <Switch
          aria-label="Escalation required"
          label="Escalation required"
          checked={v.escalation_required}
          disabled={ro}
          onCheckedChange={(c) => set("escalation_required", c)}
        />
        <p className="text-xs text-muted-foreground">Creates an email draft to the owner team&apos;s lead</p>
      </div>
      <div
        className={cn(
          "flex flex-col-reverse gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between",
          variant === "dialog" && "-mx-6 -mb-6 px-6 pb-6",
        )}
      >
        <p className="text-xs text-muted-foreground">
          {isNew ? (
            <>
              Ticket ID is assigned on save.
              {nextIdQuery.data && (
                <>
                  {" "}
                  Next: <span className="font-code">{nextIdQuery.data}</span>
                </>
              )}
            </>
          ) : ticket?.updated_at && ticket.updated_by ? (
            `Updated ${fmtShortDate(ticket.updated_at)} by ${ticket.updated_by}`
          ) : (
            ticket?.ticket_id
          )}
        </p>
        {!ro && (
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            {onCancel && (
              <Button type="button" variant="ghost" onClick={onCancel} disabled={saving}>
                Cancel
              </Button>
            )}
            <Button type="submit" loading={saving}>
              {isNew ? "Create ticket" : "Save ticket"}
            </Button>
          </div>
        )}
      </div>
    </form>
  );
}
