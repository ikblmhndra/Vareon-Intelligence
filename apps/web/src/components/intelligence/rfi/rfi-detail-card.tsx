"use client";

import Link from "next/link";
import { useId, useState } from "react";

import { RfiStatusChip } from "@/components/intelligence/rfi/rfi-list";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { RowMenu } from "@/components/ui/row-menu";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { fmtShortDate } from "@/lib/format";
import { displayId } from "@/lib/intelligence/format";
import { dueInfo, RFI_STATUS_OPTIONS, type RFIOut, type RfiStatus } from "@/lib/intelligence/rfi";

interface RfiDetailCardProps {
  rfi: RFIOut;
  /** Judul PIR tertaut ("PIR-03 {title}") bila daftar PIR sudah termuat; selain itu hanya id. */
  pirLabel: string | null;
  canManage: boolean;
  saving: boolean;
  onSave: (response: string, status: RfiStatus) => void;
  onEdit: () => void;
  onDelete: () => void;
}

function asStatus(s: string): RfiStatus {
  return s === "in_progress" || s === "closed" ? s : "open";
}

/** Panel kanan RFI terpilih (spec 2b 6.5): ringkasan, pertanyaan, PIR tertaut, kolom jawaban, status, dan
 * aksi. Draf jawaban/status disimpan lokal; pemanggil memberi `key` yang berganti saat RFI disimpan ulang
 * supaya draf mengikuti data server. Tanpa `manage_rfi` semuanya baca-saja. */
export function RfiDetailCard({ rfi, pirLabel, canManage, saving, onSave, onEdit, onDelete }: RfiDetailCardProps) {
  const uid = useId();
  const id = displayId("RFI", rfi.id);
  const [response, setResponse] = useState(rfi.response);
  const [status, setStatus] = useState<RfiStatus>(asStatus(rfi.status));
  const dirty = response !== rfi.response || status !== rfi.status;
  const due = dueInfo(rfi.due_date, rfi.status);

  return (
    <Card>
      <div className="flex flex-col gap-4 px-5">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span className="font-code text-xs font-semibold text-foreground">{id}</span>
            <RfiStatusChip status={rfi.status} />
            <div className="ml-auto">
              <RowMenu
                label={`More actions for ${id}`}
                items={[{ label: "Edit", onSelect: onEdit, hidden: !canManage }]}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Opened {fmtShortDate(rfi.created_at)} by {rfi.requester}
            {due && ` · due ${fmtShortDate(rfi.due_date)}, ${due.text}`}
          </p>
        </div>

        <h2 className="font-heading text-lg font-semibold whitespace-pre-wrap">{rfi.question}</h2>

        {rfi.linked_pir != null && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-2xs font-semibold tracking-wide text-muted-foreground">LINKED PIR</span>
            <Link
              href={`/intelligence/pir?id=${rfi.linked_pir}`}
              className="rounded-[6px] bg-panel px-2 py-0.5 font-semibold text-foreground outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {pirLabel ?? displayId("PIR", rfi.linked_pir)}
            </Link>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label htmlFor={`${uid}-response`} className="text-2xs font-semibold tracking-wide text-muted-foreground">
            RESPONSE
          </label>
          <Textarea
            id={`${uid}-response`}
            rows={5}
            value={response}
            readOnly={!canManage}
            placeholder={
              canManage ? "Draft the answer for the requester. Save it when it is ready to send." : "No response yet."
            }
            onChange={(e) => setResponse(e.target.value)}
          />
        </div>

        {canManage && (
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl aria-label="RFI status" options={RFI_STATUS_OPTIONS} value={status} onChange={setStatus} />
            <div className="ml-auto flex items-center gap-2">
              <Button variant="destructive" size="sm" disabled={saving} onClick={onDelete}>
                Delete
              </Button>
              <Button size="sm" loading={saving} disabled={!dirty} onClick={() => onSave(response, status)}>
                Save response
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
