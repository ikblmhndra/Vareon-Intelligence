"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { unwrap, writeErrorMessage } from "@/lib/scrapers/queries";

/** `POST /{id}/disable` (Fase 9 H3) -- `reason` opsional tapi diminta eksplisit di sini (bukan disable
 * diam-diam), landing di `ScraperConfig.paused_reason` buat analis lain yang lihat kenapa scraper ini mati.
 * Satu instance dipasang `ScrapersView`, dibuka dari tombol baris dan dari panel. */
export function DisableScraperDialog({
  target,
  onOpenChange,
}: {
  target: { id: string; source: string } | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  // Judul tetap terbaca selama animasi tutup (target sudah null); `open` tetap dari `target`.
  const [shown, setShown] = useState(target);
  if (target && target !== shown) setShown(target);
  // Satu instance dipakai semua baris: alasan yang dibatalkan tidak boleh terbawa ke scraper berikutnya.
  const handleOpenChange = (open: boolean) => {
    if (!open) setReason("");
    onOpenChange(open);
  };

  const mutation = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/disable", {
          params: { path: { scraper_id: id } },
          body: { reason: reason.trim() || null },
        }),
        "Disable failed",
      ),
    onSuccess: (_data, id) => {
      toast.success(`${id} disabled`);
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
      handleOpenChange(false);
    },
    onError: (e: Error) => toast.error(`Disable failed: ${writeErrorMessage(e)}`),
  });

  return (
    <Dialog open={target !== null} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle className="font-heading">Disable {shown?.source}?</DialogTitle>
          <DialogDescription>
            Beat stops scheduling it after the next restart; a run already queued is skipped. Seen items are
            kept, so enabling it later does not re-alert.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <label htmlFor="disable-scraper-reason" className="text-sm font-medium text-foreground">
            Reason (optional)
          </label>
          <Textarea
            id="disable-scraper-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="h-20"
          />
          <p className="text-xs text-muted-foreground">
            Shown on the Scrapers page next to the disabled status.
          </p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => target && mutation.mutate(target.id)}
            disabled={mutation.isPending}
          >
            Disable scraper
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
