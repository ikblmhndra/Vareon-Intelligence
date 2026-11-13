"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Textarea } from "@/components/ui/textarea";
import { unwrap, useScraperDetail, writeErrorMessage } from "@/lib/scrapers/queries";

type ScraperDetail = components["schemas"]["ScraperDetail"];
type ScraperOption = components["schemas"]["ScraperOptionOut"];

/** Dialog edit config (`PUT /{id}/config`, `POST /{id}/reset-config`). `Dialog` luar selalu terpasang,
 * formnya hanya saat `open` DAN data siap -- "mount-gates-freshness": state form diinisialisasi dari data
 * yang sudah ada (bukan reset-effect), jadi membuka ulang setelah simpan selalu menampilkan nilai tersimpan. */
export function ScraperConfigDialog({
  id,
  open,
  onOpenChange,
}: {
  id: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Null saat tertutup: id tak dikenal atau daftar belum siap tidak boleh memicu GET /api/scraper/{id}.
  const detail = useScraperDetail(open ? id : null);
  return (
    <Dialog open={open && id !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        {open && id && detail.data ? (
          <ConfigForm id={id} detail={detail.data} onClose={() => onOpenChange(false)} />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle className="font-heading">Edit config</DialogTitle>
              <DialogDescription>Loading the stored overrides.</DialogDescription>
            </DialogHeader>
            {detail.isError ? (
              <StatePanel
                variant="error"
                title="Could not load the scraper"
                action={
                  <Button variant="outline" size="sm" onClick={() => void detail.refetch()}>
                    Retry
                  </Button>
                }
              />
            ) : (
              <Skeleton className="h-48 w-full" />
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConfigForm({ id, detail, onClose }: { id: string; detail: ScraperDetail; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [schedule, setSchedule] = useState(detail.config.schedule ?? "");
  const [rateLimit, setRateLimit] = useState(detail.config.rate_limit ?? "");
  const [maxItems, setMaxItems] = useState(detail.config.max_items?.toString() ?? "");
  const [pausedReason, setPausedReason] = useState(detail.config.paused_reason ?? "");
  // Pilihan opsi scraper: key -> nilai EFEKTIF saat ini.
  const [optionValues, setOptionValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(detail.options.map((o) => [o.key, o.value])),
  );
  const [confirmReset, setConfirmReset] = useState(false);

  /** Cuma pilihan yang BEDA dari default kode yang disimpan (`null` = tidak ada, balik ke default). */
  function optionOverrides(): Record<string, string> | null {
    const changed = detail.options.filter((o) => (optionValues[o.key] ?? o.default) !== o.default);
    return changed.length ? Object.fromEntries(changed.map((o) => [o.key, optionValues[o.key]])) : null;
  }

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/scraper/{scraper_id}/config", {
          params: { path: { scraper_id: id } },
          body: {
            schedule: schedule.trim() || null,
            rate_limit: rateLimit.trim() || null,
            max_items: maxItems.trim() ? Number(maxItems) : null,
            paused_reason: pausedReason.trim() || null,
            ...(detail.options.length > 0 ? { options: optionOverrides() } : {}),
          },
        }),
        "Save failed",
      ),
    onSuccess: () => {
      toast.success("Config saved");
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
      onClose();
    },
    onError: (e: Error) => toast.error(`Save failed: ${writeErrorMessage(e)}`),
  });

  const reset = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/scraper/{scraper_id}/reset-config", { params: { path: { scraper_id: id } } }),
        "Reset failed",
      ),
    onSuccess: () => {
      toast.success("Config reset to defaults");
      void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
      onClose();
    },
    onError: (e: Error) => toast.error(`Reset failed: ${writeErrorMessage(e)}`),
  });

  const busy = save.isPending || reset.isPending;
  const fid = (k: string) => `scraper-config-${k}`;
  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-heading">Edit config · {detail.source}</DialogTitle>
        <DialogDescription>
          Blank fields use the code default. Only the values you set are stored as overrides for{" "}
          <span className="font-code">{id}</span>.
        </DialogDescription>
      </DialogHeader>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <FieldLabel htmlFor={fid("schedule")}>Schedule (cron)</FieldLabel>
          <Input
            id={fid("schedule")}
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            placeholder={detail.default_schedule}
            className="font-code text-xs"
          />
          <p className="text-xs text-muted-foreground">A schedule change takes effect after beat restarts.</p>
        </div>
        <div className="space-y-1.5">
          <FieldLabel htmlFor={fid("rate")}>Rate limit</FieldLabel>
          <Input
            id={fid("rate")}
            value={rateLimit}
            onChange={(e) => setRateLimit(e.target.value)}
            placeholder={detail.default_rate_limit}
            className="font-code text-xs"
          />
        </div>
        <div className="space-y-1.5">
          <FieldLabel htmlFor={fid("max")}>Max items</FieldLabel>
          <Input
            id={fid("max")}
            type="number"
            value={maxItems}
            onChange={(e) => setMaxItems(e.target.value)}
            placeholder={String(detail.default_max_items)}
            className="font-code text-xs"
          />
        </div>
        {detail.options.map((option) => (
          <OptionField
            key={option.key}
            option={option}
            htmlId={fid(`opt-${option.key}`)}
            value={optionValues[option.key] ?? option.default}
            onChange={(value) => setOptionValues((prev) => ({ ...prev, [option.key]: value }))}
          />
        ))}
        <div className="space-y-1.5 sm:col-span-2">
          <FieldLabel htmlFor={fid("paused")}>Paused reason</FieldLabel>
          <Textarea
            id={fid("paused")}
            value={pausedReason}
            onChange={(e) => setPausedReason(e.target.value)}
            className="h-16 text-xs"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => setConfirmReset(true)} disabled={busy}>
          Reset to defaults
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={busy}>
          Save config
        </Button>
      </DialogFooter>
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset config to defaults?"
        description={`All overrides for ${id} (schedule, rate limit, max items, paused reason${detail.options.length > 0 ? ", options" : ""}) are removed and the code defaults apply again.`}
        confirmLabel="Reset to defaults"
        onConfirm={() => reset.mutate()}
      />
    </>
  );
}

function FieldLabel({ htmlFor, children }: { htmlFor: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-foreground">
      {children}
    </label>
  );
}

/** Dropdown satu opsi scraper (`ScraperMeta.options`). `items` di `<Select>` WAJIB: tanpa itu trigger
 * menampilkan value mentah sampai popup pernah dibuka (apps/web/CLAUDE.md); `SelectItem` satu string. */
function OptionField({
  option,
  htmlId,
  value,
  onChange,
}: {
  option: ScraperOption;
  htmlId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const labels = Object.fromEntries(option.choices.map((c) => [c.value, c.label]));
  return (
    <div className="space-y-1.5 sm:col-span-2">
      <FieldLabel htmlFor={htmlId}>{option.label}</FieldLabel>
      <Select items={labels} value={value} onValueChange={(v) => onChange(v ?? option.default)}>
        <SelectTrigger id={htmlId} size="sm" className="w-full max-w-sm text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {option.choices.map((c) => (
            <SelectItem key={c.value} value={c.value} className="text-xs">
              {c.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs leading-snug text-muted-foreground">{option.description}</p>
    </div>
  );
}
