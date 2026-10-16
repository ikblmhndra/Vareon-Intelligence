"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/scrapers/status-badge";
import { ScraperRunsPanel } from "@/components/scrapers/scraper-runs-panel";
import { ScraperItemsPanel } from "@/components/scrapers/scraper-items-panel";

type ScraperDetail = components["schemas"]["ScraperDetail"];
type ScraperOption = components["schemas"]["ScraperOptionOut"];

interface Props {
  scraperId: string | null;
  onOpenChange: (open: boolean) => void;
  healthStatus?: string;
}

/** Detail scraper -- `GET /{id}` (meta default + config override) + form
 * edit config (`PUT /{id}/config`) + trigger/dry-run/enable-disable/
 * reset-dedup/reset-config + histori runs/items. Outer `Dialog` selalu
 * mounted, `ScraperDetailBody` cuma mount pas `open` DAN data siap --
 * "mount-gates-freshness" (state form lazy-init dari data yang UDAH ada,
 * bukan reset-effect), pola sama kayak `NoteForm`/`MindmapEditorForm`. */
export function ScraperDetailDialog({ scraperId, onOpenChange, healthStatus }: Props) {
  return (
    <Dialog open={scraperId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] max-w-3xl flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        {scraperId && (
          <ScraperDetailBody scraperId={scraperId} healthStatus={healthStatus} onClose={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ScraperDetailBody({
  scraperId,
  healthStatus,
  onClose,
}: {
  scraperId: string;
  healthStatus?: string;
  onClose: () => void;
}) {
  const query = useQuery({
    queryKey: ["scrapers", scraperId, "detail"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/scraper/{scraper_id}", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
  });

  return (
    <>
      <DialogHeader className="border-b border-border px-5 py-3">
        <DialogTitle className="flex items-center gap-2 font-mono text-sm text-primary">
          {scraperId}
          {healthStatus && <StatusBadge status={healthStatus} />}
        </DialogTitle>
      </DialogHeader>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {query.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
        {query.isError && <p className="py-6 text-center text-xs text-destructive">Failed to load scraper.</p>}
        {query.data && <ScraperDetailForm scraperId={scraperId} detail={query.data} onClose={onClose} />}
      </div>
    </>
  );
}

function ScraperDetailForm({
  scraperId,
  detail,
  onClose,
}: {
  scraperId: string;
  detail: ScraperDetail;
  onClose: () => void;
}) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "superadmin";
  const queryClient = useQueryClient();

  const [schedule, setSchedule] = useState(detail.config.schedule ?? "");
  const [rateLimit, setRateLimit] = useState(detail.config.rate_limit ?? "");
  const [maxItems, setMaxItems] = useState(detail.config.max_items?.toString() ?? "");
  const [pausedReason, setPausedReason] = useState(detail.config.paused_reason ?? "");
  // Pilihan opsi scraper (mis. sumber data Twitter): key -> nilai EFEKTIF saat ini.
  const [optionValues, setOptionValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(detail.options.map((o) => [o.key, o.value])),
  );
  const [dryRunResult, setDryRunResult] = useState<string | null>(null);
  const [confirmResetConfig, setConfirmResetConfig] = useState(false);
  const [confirmResetDedup, setConfirmResetDedup] = useState(false);

  function invalidateAll() {
    void queryClient.invalidateQueries({ queryKey: ["scrapers"] });
  }

  /** Cuma pilihan yang BEDA dari default kode yang disimpan (`null` = tidak ada, balik ke
   * default) -- sama polanya dengan field override lain: kosong = pakai default. */
  function optionOverrides(): Record<string, string> | null {
    const changed = detail.options.filter((o) => (optionValues[o.key] ?? o.default) !== o.default);
    return changed.length ? Object.fromEntries(changed.map((o) => [o.key, optionValues[o.key]])) : null;
  }

  const saveConfigMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.PUT("/api/scraper/{scraper_id}/config", {
        params: { path: { scraper_id: scraperId } },
        body: {
          schedule: schedule.trim() || null,
          rate_limit: rateLimit.trim() || null,
          max_items: maxItems.trim() ? Number(maxItems) : null,
          paused_reason: pausedReason.trim() || null,
          ...(detail.options.length > 0 ? { options: optionOverrides() } : {}),
        },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Config saved");
      invalidateAll();
    },
    onError: (e: Error) => toast.error(`Save failed: ${e.message}`),
  });

  const resetConfigMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/scraper/{scraper_id}/reset-config", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success("Config reset to defaults");
      setSchedule("");
      setRateLimit("");
      setMaxItems("");
      setPausedReason("");
      setOptionValues(Object.fromEntries(detail.options.map((o) => [o.key, o.default])));
      invalidateAll();
    },
    onError: (e: Error) => toast.error(`Reset failed: ${e.message}`),
  });

  const enableMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/scraper/{scraper_id}/enable", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success(`${scraperId} enabled`);
      invalidateAll();
    },
    onError: (e: Error) => toast.error(`Enable failed: ${e.message}`),
  });

  const disableMutation = useMutation({
    mutationFn: async () => {
      const { error } = await api.POST("/api/scraper/{scraper_id}/disable", {
        params: { path: { scraper_id: scraperId } },
        body: { reason: pausedReason.trim() || null },
      });
      if (error) throw error;
    },
    onSuccess: () => {
      toast.success(`${scraperId} disabled`);
      invalidateAll();
    },
    onError: (e: Error) => toast.error(`Disable failed: ${e.message}`),
  });

  const triggerMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/scraper/{scraper_id}/trigger", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) => toast.success(`Triggered — task ${data.celery_task_id.slice(0, 8)}…`),
    onError: (e: Error) => toast.error(`Trigger failed: ${e.message}`),
  });

  const dryRunMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/scraper/{scraper_id}/dry-run", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) => {
      setDryRunResult(`${data.status} — ${data.items_found} item found (${data.duration_ms}ms)`);
      if (data.errors.length) toast.error(`Dry-run errors: ${data.errors.map((e) => e.message).join("; ")}`);
    },
    onError: (e: Error) => toast.error(`Dry-run failed: ${e.message}`),
  });

  const resetDedupMutation = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.POST("/api/scraper/{scraper_id}/reset-dedup", {
        params: { path: { scraper_id: scraperId } },
      });
      if (error) throw error;
      return data;
    },
    onSuccess: (data) => toast.success(`Dedup reset — ${data.deleted} entries cleared`),
    onError: (e: Error) => toast.error(`Reset dedup failed: ${e.message}`),
  });

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-xs text-muted-foreground sm:grid-cols-3">
        <div>Source: <span className="text-foreground">{detail.source}</span></div>
        <div>Runtime: <span className="text-foreground">{detail.runtime}</span></div>
        <div>Queue: <span className="text-foreground">{detail.queue}</span></div>
        <div>Default schedule: <span className="text-foreground">{detail.default_schedule}</span></div>
        <div>Default rate limit: <span className="text-foreground">{detail.default_rate_limit}</span></div>
        <div>Default max items: <span className="text-foreground">{detail.default_max_items}</span></div>
        {detail.credential && <div>Credential: <span className="text-foreground">{detail.credential}</span></div>}
        {detail.tags.length > 0 && <div>Tags: <span className="text-foreground">{detail.tags.join(", ")}</span></div>}
      </div>

      <div className="flex flex-wrap gap-2 border-y border-border py-3">
        <Button size="sm" variant="outline" disabled={!isAdmin} onClick={() => triggerMutation.mutate()}>
          {triggerMutation.isPending ? "Triggering…" : "Trigger"}
        </Button>
        <Button size="sm" variant="outline" disabled={!isAdmin} onClick={() => dryRunMutation.mutate()}>
          {dryRunMutation.isPending ? "Running…" : "▷ Dry-run"}
        </Button>
        {detail.config.enabled ? (
          <Button size="sm" variant="outline" disabled={!isAdmin} onClick={() => disableMutation.mutate()}>
            Disable
          </Button>
        ) : (
          <Button size="sm" variant="outline" disabled={!isAdmin} onClick={() => enableMutation.mutate()}>
            Enable
          </Button>
        )}
        <Button size="sm" variant="outline" disabled={!isAdmin} onClick={() => setConfirmResetDedup(true)}>
          Reset Dedup
        </Button>
        {dryRunResult && <span className="self-center font-mono text-xs text-muted-foreground">{dryRunResult}</span>}
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold text-muted-foreground">
            Config override
          </span>
          {isAdmin && detail.config.updated_by && (
            <span className="font-mono text-xs text-muted-foreground">
              by {detail.config.updated_by} · {detail.config.updated_at?.replace("T", " ").split(".")[0]}
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              Schedule (cron) — default {detail.default_schedule}
            </Label>
            <Input
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              placeholder={detail.default_schedule}
              disabled={!isAdmin}
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              Rate limit — default {detail.default_rate_limit}
            </Label>
            <Input
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
              placeholder={detail.default_rate_limit}
              disabled={!isAdmin}
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-sm font-medium text-muted-foreground">
              Max items — default {detail.default_max_items}
            </Label>
            <Input
              type="number"
              value={maxItems}
              onChange={(e) => setMaxItems(e.target.value)}
              placeholder={String(detail.default_max_items)}
              disabled={!isAdmin}
              className="font-mono text-xs"
            />
          </div>
          {detail.options.map((option) => (
            <OptionField
              key={option.key}
              option={option}
              value={optionValues[option.key] ?? option.default}
              disabled={!isAdmin}
              onChange={(value) => setOptionValues((prev) => ({ ...prev, [option.key]: value }))}
            />
          ))}
          <div className="space-y-1 sm:col-span-2">
            <Label className="text-sm font-medium text-muted-foreground">Paused reason</Label>
            <Textarea
              value={pausedReason}
              onChange={(e) => setPausedReason(e.target.value)}
              disabled={!isAdmin}
              className="h-14 font-mono text-xs"
            />
          </div>
        </div>
        {isAdmin && (
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => saveConfigMutation.mutate()} disabled={saveConfigMutation.isPending}>
              Save Config
            </Button>
            <Button size="sm" variant="outline" onClick={() => setConfirmResetConfig(true)}>
              Reset to Defaults
            </Button>
          </div>
        )}
      </div>

      <div>
        <div className="mb-2 text-sm font-semibold text-muted-foreground">Recent Runs</div>
        <ScraperRunsPanel scraperId={scraperId} />
      </div>

      <div>
        <div className="mb-2 text-sm font-semibold text-muted-foreground">Recent Items</div>
        <ScraperItemsPanel scraperId={scraperId} />
      </div>

      <div className="flex justify-end border-t border-border pt-3">
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      <ConfirmDialog
        open={confirmResetConfig}
        onOpenChange={setConfirmResetConfig}
        title="Reset config to defaults?"
        description={`Semua override untuk "${scraperId}" (schedule/rate_limit/max_items/paused_reason${detail.options.length > 0 ? "/pilihan sumber data" : ""}) akan dihapus, balik ke default kode.`}
        onConfirm={() => resetConfigMutation.mutate()}
      />
      <ConfirmDialog
        open={confirmResetDedup}
        onOpenChange={setConfirmResetDedup}
        title="Reset dedup state?"
        description={`Semua riwayat dedup "${scraperId}" dihapus -- run berikutnya nge-treat ulang semua item sebagai baru.`}
        onConfirm={() => resetDedupMutation.mutate()}
      />
    </div>
  );
}

/** Dropdown satu opsi scraper (`ScraperMeta.options`) -- mis. "Sumber data Twitter/X". `items`
 * di `<Select>` WAJIB: tanpa itu trigger nampilin value mentah sampai popup pernah dibuka
 * (lihat apps/web/CLAUDE.md). Isi `SelectItem` satu string tunggal. */
function OptionField({
  option,
  value,
  disabled,
  onChange,
}: {
  option: ScraperOption;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const labels = Object.fromEntries(option.choices.map((c) => [c.value, c.label]));
  const unsaved = value !== option.value;
  return (
    <div className="space-y-1 sm:col-span-2">
      <Label className="text-sm font-medium text-muted-foreground">
        {option.label} — default {labels[option.default] ?? option.default}
      </Label>
      <Select items={labels} value={value} onValueChange={(v) => onChange(v ?? option.default)} disabled={disabled}>
        <SelectTrigger size="sm" className="w-full max-w-sm font-mono text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {option.choices.map((c) => (
            <SelectItem key={c.value} value={c.value} className="font-code text-xs">
              {c.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs leading-snug text-muted-foreground">{option.description}</p>
      {unsaved && (
        <p className="font-mono text-xs text-amber-500">
          Belum disimpan — klik Save Config; berlaku di run berikutnya.
        </p>
      )}
    </div>
  );
}
