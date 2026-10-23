"use client";

import { InfoIcon, TriangleAlertIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { PreviewDialogState } from "@/components/newsletter/types";

interface Props {
  state: PreviewDialogState;
  onOpenChange: (open: boolean) => void;
  onSendDraft: () => void;
  sending: boolean;
  onResendSaved: (id: number, label: string) => void;
  resending: boolean;
}

/** Port `#modal-overlay`/`#preview-iframe` (`newsletter.html:401-416`) --
 * dipakai DUA mode: "compose" (hasil `POST /preview` dari composition
 * yang lagi disusun, footer "Create Outlook draft") dan "saved" (hasil
 * `GET /{id}/html` dari histori, footer "Resend") -- port
 * `openPreview()`/`previewSaved()` yang keduanya numpang modal yang
 * SAMA di legacy.
 *
 * Mode compose adalah satu-satunya jalan membuat draft (ROADMAP #22, PR 9): preview dulu, peringatan
 * (ukuran email dari server, penanda CVE dari composer) tampil DI ATAS pratinjau, baru draft. Tombol
 * draft mati sampai pratinjau berhasil dimuat, supaya tidak ada draft yang dibuat dari preview yang
 * gagal atau belum terlihat. */
export function NewsletterPreviewDialog({ state, onOpenChange, onSendDraft, sending, onResendSaved, resending }: Props) {
  const title = `${state.mode === "saved" ? "SAVED NEWSLETTER" : "NEWSLETTER PREVIEW"}${state.label ? ` — ${state.label}` : ""}`;
  const compose = state.mode === "compose";
  const hasNotices = compose && (state.warnings.length > 0 || state.metadataTitles.length > 0);
  return (
    <Dialog open={state.open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b border-border px-4 py-3">
          <DialogTitle className="font-mono text-xs tracking-widest text-primary">{title}</DialogTitle>
        </DialogHeader>

        {hasNotices && (
          <div className="max-h-[30vh] space-y-2 overflow-y-auto border-b border-border bg-surface px-4 py-3 text-xs">
            {state.warnings.map((w) => (
              <p key={w} role="alert" className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-warning-text">
                <TriangleAlertIcon aria-hidden className="mt-0.5 size-3.5 shrink-0" /> <span>{w}</span>
              </p>
            ))}
            {state.metadataTitles.length > 0 && (
              <div className="flex items-start gap-2 rounded-md border border-border px-3 py-2 text-muted-foreground">
                <InfoIcon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-info" />
                <div>
                  {state.metadataTitles.length} summar{state.metadataTitles.length === 1 ? "y was" : "ies were"} written from
                  metadata only because the page could not be read. Check {state.metadataTitles.length === 1 ? "it" : "them"}:
                  <ul className="mt-1 list-disc pl-5">
                    {state.metadataTitles.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="h-[60vh] min-h-0 shrink overflow-hidden bg-white">
          {state.html === null ? (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">Loading…</div>
          ) : (
            <iframe title="Newsletter preview" sandbox="allow-same-origin" srcDoc={state.html} className="h-full w-full border-0" />
          )}
        </div>
        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-4 py-3">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {compose ? (
            <Button size="sm" onClick={onSendDraft} disabled={sending || !state.body || state.html === null}>
              {sending ? "Creating draft…" : state.warnings.length > 0 ? "Create draft anyway" : "Create Outlook draft"}
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={resending || state.savedId == null}
              onClick={() => state.savedId != null && onResendSaved(state.savedId, state.label)}
            >
              {resending ? "Resending…" : "Resend"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
