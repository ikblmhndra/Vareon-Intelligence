"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Notice } from "@/components/ui/notice";
import type { PreviewDialogState } from "@/components/newsletter/types";
import { useCan } from "@/lib/auth/permissions";

interface Props {
  state: PreviewDialogState;
  onOpenChange: (open: boolean) => void;
  onSendDraft: () => void;
  sending: boolean;
  onResendSaved: (id: number, label: string) => void;
  resending: boolean;
}

/** Jumlah artikel yang ditempatkan di request yang di-preview (semua slot id). */
function placedInBody(body: PreviewDialogState["body"]): number {
  if (!body) return 0;
  return [
    body.highlights,
    body.apac_full,
    body.apac_compact,
    body.global_news_full,
    body.global_news_compact,
    body.indonesia_full,
    body.indonesia_compact,
  ].reduce((n, ids) => n + (ids?.length ?? 0), 0);
}

/** Dialog pratinjau, dipakai DUA mode: "compose" (hasil `POST /preview` dari composition yang
 * lagi disusun, footer "Create Outlook draft") dan "saved" (hasil `GET /{id}/html` dari histori,
 * footer "Resend").
 *
 * Mode compose adalah satu-satunya jalan membuat draft (ROADMAP #22, PR 9): preview dulu, peringatan
 * (ukuran email dari server, penanda CVE dari composer) tampil DI ATAS pratinjau, baru draft. Tombol
 * draft mati sampai pratinjau berhasil dimuat, supaya tidak ada draft yang dibuat dari preview yang
 * gagal atau belum terlihat. `origin` menentukan penekanan: dari "Preview" fokus awal ke Close dan
 * tombol draft outline (hanya melihat); dari "Generate edition" tombol draft utama dan difokuskan
 * begitu pratinjau termuat (C12). */
export function NewsletterPreviewDialog({ state, onOpenChange, onSendDraft, sending, onResendSaved, resending }: Props) {
  const can = useCan();
  const closeRef = useRef<HTMLButtonElement>(null);
  const draftRef = useRef<HTMLButtonElement>(null);
  const compose = state.mode === "compose";
  const generate = compose && state.origin === "generate";
  const loaded = state.html !== null;
  const ready = loaded && !!state.body;

  useEffect(() => {
    if (state.open && generate && ready) draftRef.current?.focus();
  }, [state.open, generate, ready]);

  const hasNotices = compose && (state.warnings.length > 0 || state.metadataTitles.length > 0);
  const titleLabel = state.label ? ` · ${state.label} edition` : "";
  const toCheck = state.metadataTitles.length;

  return (
    <Dialog open={state.open} onOpenChange={onOpenChange}>
      <DialogContent
        initialFocus={compose && !generate ? closeRef : undefined}
        className="flex max-h-[90vh] flex-col gap-3 overflow-hidden sm:max-w-3xl"
      >
        <DialogHeader>
          <DialogTitle>{`${state.mode === "saved" ? "Saved" : "Preview"}${titleLabel}`}</DialogTitle>
          <DialogDescription>The email as the recipient will see it. Paywalled summaries are flagged.</DialogDescription>
        </DialogHeader>

        {hasNotices && (
          <div role={state.warnings.length > 0 ? "alert" : undefined} className="max-h-[30vh] overflow-y-auto">
            <Notice
              tone={state.warnings.length > 0 ? "warning" : "info"}
              title={state.warnings.length > 0 ? "Check before creating the draft" : "Summaries to check"}
            >
              <div className="space-y-2">
                {state.warnings.map((w) => (
                  <p key={w}>{w}</p>
                ))}
                {toCheck > 0 && (
                  <div>
                    {toCheck} summar{toCheck === 1 ? "y was" : "ies were"} written from metadata only because the page could not be
                    read. Check {toCheck === 1 ? "it" : "them"}:
                    <ul className="mt-1 list-disc pl-5">
                      {state.metadataTitles.map((t) => (
                        <li key={t}>{t}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Notice>
          </div>
        )}

        <div className="h-[60vh] min-h-0 shrink overflow-hidden rounded-lg border border-border bg-white">
          {state.html === null ? (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading…</div>
          ) : (
            <iframe title="Newsletter preview" sandbox="allow-same-origin" srcDoc={state.html} className="h-full w-full border-0" />
          )}
        </div>

        <DialogFooter className="items-center sm:justify-between">
          <p className="font-code text-xs text-muted-foreground">
            {compose && state.body ? `${placedInBody(state.body)} articles · ${toCheck} summary to check` : ""}
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row">
            <Button ref={closeRef} variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            {!can("manage_newsletter") ? null : compose ? (
              <Button
                ref={draftRef}
                variant={generate ? "default" : "outline"}
                onClick={onSendDraft}
                loading={sending}
                disabled={!ready}
              >
                {sending ? "Creating draft…" : state.warnings.length > 0 ? "Create draft anyway" : "Create Outlook draft"}
              </Button>
            ) : (
              <Button
                loading={resending}
                disabled={state.savedId == null}
                onClick={() => state.savedId != null && onResendSaved(state.savedId, state.label)}
              >
                {resending ? "Resending…" : "Resend"}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
