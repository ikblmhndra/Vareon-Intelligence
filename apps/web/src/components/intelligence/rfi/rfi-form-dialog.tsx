"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";

type RFIOut = components["schemas"]["RFIOut"];

const STATUSES = ["open", "in_progress", "closed"];

function nativeSelectClass() {
  return "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-focus dark:bg-input/30";
}

interface RfiFormDialogProps {
  rfi?: RFIOut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

/** Port modal Add/Edit RFI (`pir.js:383-431`, `openRfiModal`/`saveRfi`).
 * `linked_pir` dropdown populate dari `GET /api/pir` (`_rfiLoadPirOptions`). */
export function RfiFormDialog({ rfi, open, onClose, onSaved }: RfiFormDialogProps) {
  const isEdit = Boolean(rfi);
  const [requester, setRequester] = useState(rfi?.requester ?? "");
  const [question, setQuestion] = useState(rfi?.question ?? "");
  const [dueDate, setDueDate] = useState(rfi?.due_date ?? "");
  const [status, setStatus] = useState(rfi?.status ?? "open");
  const [response, setResponse] = useState(rfi?.response ?? "");
  const [linkedPir, setLinkedPir] = useState(rfi?.linked_pir != null ? String(rfi.linked_pir) : "");
  const [saving, setSaving] = useState(false);

  const pirsQuery = useQuery({
    queryKey: ["intelligence", "pirs-for-rfi"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir");
      if (error) throw error;
      return data;
    },
    enabled: open,
  });

  async function submit() {
    if (!requester.trim() || !question.trim()) {
      toast.error("Requester and Question are required");
      return;
    }
    setSaving(true);
    try {
      const body = {
        requester: requester.trim(),
        question: question.trim(),
        status,
        response: response.trim(),
        due_date: dueDate || null,
        linked_pir: linkedPir ? Number(linkedPir) : null,
      };
      if (isEdit && rfi) {
        const { error } = await api.PUT("/api/rfi/{rfi_id}", { params: { path: { rfi_id: rfi.id } }, body });
        if (error) throw new Error(JSON.stringify(error));
        toast.success("RFI updated.");
      } else {
        const { error } = await api.POST("/api/rfi", { body });
        if (error) throw new Error(JSON.stringify(error));
        toast.success("RFI created.");
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(`Error: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit RFI" : "New RFI"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Requester</Label>
            <Input value={requester} onChange={(e) => setRequester(e.target.value)} className="text-xs" />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Question</Label>
            <Textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} className="text-xs" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Due Date</Label>
              <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="text-xs" />
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Status</Label>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className={nativeSelectClass()}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Linked PIR</Label>
            <select value={linkedPir} onChange={(e) => setLinkedPir(e.target.value)} className={nativeSelectClass()}>
              <option value="">— None —</option>
              {(pirsQuery.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  [{p.priority}] {p.title}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Response</Label>
            <Textarea value={response} onChange={(e) => setResponse(e.target.value)} rows={3} className="text-xs" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving} onClick={() => void submit()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
