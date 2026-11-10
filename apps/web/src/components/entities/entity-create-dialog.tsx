"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { entityTypeMeta } from "@/lib/entities/types";

/** Pilihan tipe di form; `identity` dibelah jadi sektor (class) dan korban (organization). */
const TYPE_OPTIONS: { value: string; type: string; identityClass?: string }[] = [
  { value: "intrusion-set", type: "intrusion-set" },
  { value: "malware", type: "malware" },
  { value: "tool", type: "tool" },
  { value: "attack-pattern", type: "attack-pattern" },
  { value: "vulnerability", type: "vulnerability" },
  { value: "campaign", type: "campaign" },
  { value: "identity:class", type: "identity", identityClass: "class" },
  { value: "identity:organization", type: "identity", identityClass: "organization" },
  { value: "location", type: "location" },
];

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  TYPE_OPTIONS.map((o) => [o.value, entityTypeMeta(o.type, o.identityClass).label]),
);

/** `detail` API bisa string (409) atau daftar error validasi (422); tampilkan apa adanya. */
function errorDetail(err: unknown): string {
  const detail = (err as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d as { msg?: string }).msg ?? JSON.stringify(d)).join("; ");
  }
  return "Could not create the entity.";
}

interface Props {
  open: boolean;
  onClose: () => void;
  /** Tipe awal (nilai `?type=` atau tipe tab aktif); `identity` polos jatuh ke sektor. */
  initialType: string;
  initialName: string;
}

/** Dialog "New entity" (`manage_entities`). State form di-reset lewat `key` dari pemanggil. */
export function EntityCreateDialog({ open, onClose, initialType, initialName }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const startType =
    TYPE_OPTIONS.find((o) => o.value === initialType)?.value ??
    (initialType === "identity" ? "identity:class" : "intrusion-set");
  const [typeValue, setTypeValue] = useState(startType);
  const [name, setName] = useState(initialName);
  const [aliases, setAliases] = useState("");
  const [description, setDescription] = useState("");
  const [externalId, setExternalId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const opt = TYPE_OPTIONS.find((o) => o.value === typeValue) ?? TYPE_OPTIONS[0];
  const needsExternalId = opt.type === "attack-pattern";

  async function submit() {
    if (!name.trim()) {
      setError("Name is required.");
      return;
    }
    if (needsExternalId && !externalId.trim()) {
      setError("A technique needs an ATT&CK ID (for example T1566.001).");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/entities", {
        body: {
          type: opt.type,
          name: name.trim(),
          aliases: aliases.split(",").map((s) => s.trim()).filter(Boolean),
          description: description.trim() || null,
          external_id: externalId.trim() || null,
          identity_class: opt.identityClass ?? null,
        },
      });
      if (err || !data) {
        setError(errorDetail(err));
        return;
      }
      toast.success(`"${data.name}" created.`);
      void queryClient.invalidateQueries({ queryKey: ["entities"] });
      onClose();
      router.push(`/intelligence/entities/${data.id}`);
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
          <DialogTitle>New entity</DialogTitle>
          <DialogDescription>Add an entity to the registry; it can be watched and linked to articles later.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-new-type" className="text-sm font-medium text-muted-foreground">
              Type
            </Label>
            <Select items={TYPE_LABELS} value={typeValue} onValueChange={(v) => v && setTypeValue(v)}>
              <SelectTrigger id="entity-new-type" className="w-full text-xs max-sm:h-11">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value} className="text-xs">
                    {TYPE_LABELS[o.value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-new-name" className="text-sm font-medium text-muted-foreground">
              Name
            </Label>
            <Input
              id="entity-new-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="text-xs max-sm:h-11"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-new-ext" className="text-sm font-medium text-muted-foreground">
              {needsExternalId ? "ATT&CK ID (required)" : "External ID (optional)"}
            </Label>
            <Input
              id="entity-new-ext"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
              placeholder={needsExternalId ? "T1566.001" : undefined}
              className="font-code text-xs max-sm:h-11"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-new-aliases" className="text-sm font-medium text-muted-foreground">
              Aliases (comma separated)
            </Label>
            <Input
              id="entity-new-aliases"
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              className="text-xs max-sm:h-11"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="entity-new-desc" className="text-sm font-medium text-muted-foreground">
              Description
            </Label>
            <Textarea
              id="entity-new-desc"
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
              {saving ? "Creating…" : "Create entity"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
