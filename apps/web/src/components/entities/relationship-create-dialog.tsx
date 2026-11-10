"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityChip } from "@/components/entities/entity-chip";
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
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { entityTypeMeta } from "@/lib/entities/types";

/** Nilai `relationship_type` yang diterima `POST /api/relationships`. */
export const RELATIONSHIP_TYPES = [
  "uses",
  "targets",
  "attributed-to",
  "exploits",
  "indicates",
  "variant-of",
  "located-at",
  "related-to",
  "subtechnique-of",
] as const;

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  RELATIONSHIP_TYPES.map((t) => [t, t]),
);

export type RelationshipEnd = { id: number; type: string; name: string };

/** `detail` API bisa string (409/404) atau daftar error validasi (422); tampilkan apa adanya. */
function errorDetail(err: unknown): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; ");
  }
  return "Could not create the relationship.";
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Ujung sumber: entity pada halaman ini. */
  source: RelationshipEnd;
  /** Ujung target terisi (mis. dari "Relate"); kosong = analis mencari entity lewat kotak cari. */
  target?: RelationshipEnd | null;
  /** Dipanggil sesudah berhasil, untuk memuat ulang daftar milik pemanggil. */
  onCreated?: () => void;
}

/** Cari target: kotak cari + daftar hasil `/api/entities?q=`; minimal 2 huruf agar tidak menarik semua entity. */
function TargetPicker({
  value,
  onChange,
  excludeId,
}: {
  value: RelationshipEnd | null;
  onChange: (v: RelationshipEnd | null) => void;
  excludeId: number;
}) {
  const [q, setQ] = useState("");
  const term = q.trim();
  const results = useQuery({
    queryKey: ["entities", "relationship-target", term],
    enabled: value == null && term.length >= 2,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities", {
        params: { query: { q: term, limit: 8 } },
      });
      if (error || !data) throw new Error("search failed");
      return data.items;
    },
  });

  if (value) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <EntityChip type={value.type} name={value.name} id={value.id} />
        <Button type="button" variant="ghost" size="sm" onClick={() => onChange(null)} className="max-sm:h-11">
          Change
        </Button>
      </div>
    );
  }
  const items = (results.data ?? []).filter((e) => e.id !== excludeId);
  return (
    <div className="space-y-2">
      <Input
        id="rel-target-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search name or alias"
        aria-label="Search target entity"
        className="text-xs max-sm:h-11"
      />
      {term.length >= 2 && results.isError && (
        <p role="alert" className="text-xs text-destructive-text">
          Could not search entities.
        </p>
      )}
      {term.length >= 2 && results.isSuccess && items.length === 0 && (
        <p className="text-xs text-muted-foreground">No entity matches.</p>
      )}
      {items.length > 0 && (
        <ul className="max-h-40 space-y-1 overflow-y-auto" aria-label="Matching entities">
          {items.map((e) => {
            const meta = entityTypeMeta(e.type);
            return (
              <li key={e.id}>
                <button
                  type="button"
                  onClick={() => onChange({ id: e.id, type: e.type, name: e.name })}
                  className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-xs outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-focus max-sm:min-h-11"
                >
                  <meta.Icon aria-hidden className={`size-3.5 shrink-0 ${meta.colorClass}`} />
                  <span className="min-w-0 truncate">{e.name}</span>
                  <span className="ml-auto shrink-0 text-2xs text-muted-foreground">{meta.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Dialog "Make relationship" (`manage_entities`). State form di-reset lewat `key` dari pemanggil. */
export function RelationshipCreateDialog({ open, onClose, source, target: initialTarget, onCreated }: Props) {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<RelationshipEnd | null>(initialTarget ?? null);
  const [type, setType] = useState<string>("related-to");
  const [confidence, setConfidence] = useState("75");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    const conf = Number(confidence);
    if (!target) {
      setError("Pick the entity at the other end.");
      return;
    }
    if (!Number.isInteger(conf) || conf < 0 || conf > 100) {
      setError("Confidence must be a whole number from 0 to 100.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/relationships", {
        body: {
          source_id: source.id,
          relationship_type: type,
          target_id: target.id,
          confidence: conf,
          description: description.trim() || null,
        },
      });
      if (err || !data) {
        setError(errorDetail(err));
        return;
      }
      toast.success("Relationship created.");
      void queryClient.invalidateQueries({ queryKey: ["entity-relationships"] });
      onCreated?.();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-lg overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Make relationship</DialogTitle>
          <DialogDescription>Published to TAXII as an analyst relationship.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <EntityChip type={source.type} name={source.name} id={source.id} />
            <div className="flex flex-col gap-1">
              <Label htmlFor="rel-type" className="sr-only">
                Relationship type
              </Label>
              <Select items={TYPE_LABELS} value={type} onValueChange={(v) => v && setType(v)}>
                <SelectTrigger id="rel-type" className="w-40 text-xs max-sm:h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RELATIONSHIP_TYPES.map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium text-muted-foreground">Target</span>
            <TargetPicker value={target} onChange={setTarget} excludeId={source.id} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-confidence" className="text-sm font-medium text-muted-foreground">
              Confidence (0-100)
            </Label>
            <Input
              id="rel-confidence"
              type="number"
              inputMode="numeric"
              min={0}
              max={100}
              value={confidence}
              onChange={(e) => setConfidence(e.target.value)}
              className="w-28 font-code text-xs max-sm:h-11"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-note" className="text-sm font-medium text-muted-foreground">
              Note (optional)
            </Label>
            <Textarea
              id="rel-note"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="text-xs"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive-text">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose} className="max-sm:h-11">
              Cancel
            </Button>
            <Button type="submit" loading={saving} className="max-sm:h-11">
              {saving ? "Creating…" : "Create relationship"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
