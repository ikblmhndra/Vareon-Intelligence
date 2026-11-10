"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { DateField } from "@/components/ui/date-field";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { displayId } from "@/lib/intelligence/format";
import { usePirs } from "@/lib/intelligence/pir";
import { invalidateRfis, RFI_STATUS_OPTIONS, type RFIOut, type RfiStatus } from "@/lib/intelligence/rfi";

interface RfiFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `null`/kosong = buat baru; terisi = ubah (menambah Status dan Response, D19). */
  rfi?: RFIOut | null;
  /** RFI hasil simpan, supaya halaman bisa membuka tab status dan memilihnya. */
  onSaved?: (saved: RFIOut) => void;
}

const NONE = "none";

/** Pesan galat API yang bisa dibaca (FastAPI `detail` string atau daftar galat validasi). */
function apiMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d as { msg?: string }).msg)
      .filter(Boolean)
      .join("; ");
  }
  return "Could not save the RFI. Try again.";
}

/** Dialog buat/ubah RFI (spec 2b 6.5, D19): pertanyaan, peminta, jatuh tempo, dan PIR tertaut tetap bisa
 * diubah setelah dibuat; mode ubah menambah Status dan Response. Isian tidak dibuang saat API menolak:
 * galatnya tampil di dalam dialog. Pemanggil me-remount (`key`) per pembukaan supaya isian segar. */
export function RfiFormDialog({ open, onOpenChange, rfi, onSaved }: RfiFormDialogProps) {
  const isEdit = Boolean(rfi);
  const uid = useId();
  const queryClient = useQueryClient();
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const requesterRef = useRef<HTMLInputElement>(null);
  const pirs = usePirs();

  const [question, setQuestion] = useState(rfi?.question ?? "");
  const [requester, setRequester] = useState(rfi?.requester ?? "");
  const [dueDate, setDueDate] = useState<string | null>(rfi?.due_date ?? null);
  const [linkedPir, setLinkedPir] = useState(rfi?.linked_pir != null ? String(rfi.linked_pir) : NONE);
  const [status, setStatus] = useState<RfiStatus>(
    rfi?.status === "in_progress" || rfi?.status === "closed" ? rfi.status : "open",
  );
  const [response, setResponse] = useState(rfi?.response ?? "");
  const [questionError, setQuestionError] = useState<string | undefined>();
  const [requesterError, setRequesterError] = useState<string | undefined>();
  const [saving, setSaving] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const items: Record<string, string> = { [NONE]: "None" };
  for (const p of pirs.data ?? []) items[String(p.id)] = `${displayId("PIR", p.id)} ${p.title}`;
  // PIR tertaut yang belum ada di daftar (masih memuat) tetap punya label, bukan angka mentah.
  if (!(linkedPir in items)) items[linkedPir] = displayId("PIR", Number(linkedPir));

  async function submit(e: FormEvent) {
    e.preventDefault();
    const missingQuestion = !question.trim();
    const missingRequester = !requester.trim();
    setQuestionError(missingQuestion ? "Write the question the requester wants answered." : undefined);
    setRequesterError(missingRequester ? "Say who is asking, for example CISO." : undefined);
    if (missingQuestion || missingRequester) {
      (missingQuestion ? questionRef : requesterRef).current?.focus();
      return;
    }
    setSaving(true);
    setApiError(null);
    // Field ber-default di backend tetap dikirim: tipe hasil openapi-typescript mewajibkannya.
    const base = {
      question: question.trim(),
      requester: requester.trim(),
      due_date: dueDate,
      linked_pir: linkedPir === NONE ? null : Number(linkedPir),
    };
    try {
      const res =
        isEdit && rfi
          ? await api.PUT("/api/rfi/{rfi_id}", {
              params: { path: { rfi_id: rfi.id } },
              body: { ...base, status, response: response.trim() },
            })
          : await api.POST("/api/rfi", { body: { ...base, status: "open", response: "" } });
      if (res.error || !res.data) {
        setApiError(apiMessage(res.error));
        return;
      }
      toast.success(isEdit ? "RFI updated." : "RFI created.");
      invalidateRfis(queryClient);
      onSaved?.(res.data);
      onOpenChange(false);
    } catch {
      setApiError("Could not reach the server. Try again.");
    } finally {
      setSaving(false);
    }
  }

  const id = (name: string) => `${uid}-${name}`;
  const hint = "One specific question, so the answer can be short.";

  return (
    <Dialog open={open} onOpenChange={(o) => !saving && onOpenChange(o)}>
      <DialogContent className="max-h-[90vh] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading">
            {isEdit && rfi ? `Edit ${displayId("RFI", rfi.id)}` : "New RFI"}
          </DialogTitle>
          <DialogDescription>A specific question from a stakeholder, tracked until it has an answer.</DialogDescription>
        </DialogHeader>

        <form noValidate onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
          <Field label="Question" htmlFor={id("question")} hint={hint} error={questionError}>
            <Textarea
              ref={questionRef}
              id={id("question")}
              rows={3}
              value={question}
              aria-invalid={!!questionError}
              aria-describedby={fieldDescribedBy(id("question"), { hint, error: questionError })}
              onChange={(e) => {
                setQuestion(e.target.value);
                if (questionError && e.target.value.trim()) setQuestionError(undefined);
              }}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Requester" htmlFor={id("requester")} error={requesterError}>
              <Input
                ref={requesterRef}
                id={id("requester")}
                value={requester}
                aria-invalid={!!requesterError}
                aria-describedby={fieldDescribedBy(id("requester"), { error: requesterError })}
                onChange={(e) => {
                  setRequester(e.target.value);
                  if (requesterError && e.target.value.trim()) setRequesterError(undefined);
                }}
              />
            </Field>
            <Field label="Due date" htmlFor={id("due")}>
              <DateField id={id("due")} value={dueDate} onChange={setDueDate} optional />
            </Field>
          </div>
          <Field label="Linked PIR (optional)" htmlFor={id("pir")}>
            <Select items={items} value={linkedPir} onValueChange={(v) => v != null && setLinkedPir(v)}>
              <SelectTrigger id={id("pir")} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(items).map(([value, label]) => (
                  <SelectItem key={value} value={value}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {isEdit && (
            <>
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-foreground">Status</span>
                <SegmentedControl
                  aria-label="Status"
                  options={RFI_STATUS_OPTIONS}
                  value={status}
                  onChange={setStatus}
                  className="self-start"
                />
              </div>
              <Field label="Response" htmlFor={id("response")}>
                <Textarea
                  id={id("response")}
                  rows={4}
                  value={response}
                  onChange={(e) => setResponse(e.target.value)}
                />
              </Field>
            </>
          )}

          {apiError && (
            <p role="alert" className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive-text">
              {apiError}
            </p>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" disabled={saving} onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {saving ? (isEdit ? "Saving…" : "Creating…") : isEdit ? "Save" : "Create RFI"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
