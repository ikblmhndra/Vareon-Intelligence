"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { components } from "@/lib/api/schema";
import type { SrActionResult } from "@/lib/api/loose-types";

type SREntry = components["schemas"]["SREntryOut"];

interface SrEntryDialogProps {
  mode: "add" | "edit";
  entry?: SREntry | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

function nativeSelectClass() {
  return "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-focus dark:bg-input/30";
}

/** Port modal Add/Edit Source Rating (`source_reliability.js:113-299`,
 * `_srPopulateModal`/`srModalSubmit`). Source picker autocomplete
 * (`_srRenderSourceDd`/`srSourceKey`, arrow-key nav) -- gak ada
 * komponen Combobox siap pakai di `ui/`, dibangun sendiri di sini
 * (Input + dropdown lokal), bukan port Base UI `Select` (itu buat
 * fixed-option, bukan free-text+filter). */
export function SrEntryDialog({ mode, entry, open, onClose, onSaved }: SrEntryDialogProps) {
  const { user } = useAuth();
  const [source, setSource] = useState(entry?.source_name ?? "");
  const [ddOpen, setDdOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const [analyst, setAnalyst] = useState(entry?.analyst_name ?? user?.username ?? "");
  const [grade, setGrade] = useState(entry?.reliability_grade ?? "");
  const [notes, setNotes] = useState(entry?.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const labelsQuery = useQuery({
    queryKey: ["intelligence", "sr-labels"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/labels");
      if (error) throw error;
      return data as { reliability: Record<string, string> };
    },
  });

  const ungradedQuery = useQuery({
    queryKey: ["intelligence", "ungraded-sources"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/sr/ungraded-sources");
      if (error) throw error;
      return data.sources;
    },
    enabled: mode === "add" && open,
  });

  const matches = useMemo(() => {
    const list = ungradedQuery.data ?? [];
    const q = source.toLowerCase();
    return q ? list.filter((s) => s.toLowerCase().includes(q)) : list;
  }, [ungradedQuery.data, source]);

  function handleSourceKeyDown(e: React.KeyboardEvent) {
    if (!ddOpen || matches.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      setSource(matches[activeIdx]);
      setDdOpen(false);
    } else if (e.key === "Escape") {
      setDdOpen(false);
    }
  }

  async function submit() {
    setErr("");
    if (!analyst.trim() || !grade || (mode === "add" && !source.trim())) {
      setErr("All required fields must be filled.");
      return;
    }
    setSaving(true);
    try {
      if (mode === "edit" && entry) {
        const { data, error } = await api.PUT("/api/sr/entries/{entry_id}", {
          params: { path: { entry_id: entry.id } },
          body: { analyst_name: analyst.trim(), reliability_grade: grade, notes: notes.trim() },
        });
        if (error) throw new Error(JSON.stringify(error));
        const d = data as unknown as { success: boolean };
        if (!d.success) {
          setErr("Update failed.");
          return;
        }
        toast.success("Updated.");
      } else {
        const { data, error } = await api.POST("/api/sr/entries", {
          body: {
            source_name: source.trim(),
            analyst_name: analyst.trim(),
            reliability_grade: grade,
            notes: notes.trim(),
          },
        });
        if (error) throw new Error(JSON.stringify(error));
        const d = data as unknown as SrActionResult;
        if (!d.success) {
          setErr(d.reason === "duplicate" ? "Source already exists." : `Error: ${d.reason}`);
          return;
        }
        toast.success("Source added.");
      }
      onSaved();
      onClose();
    } catch (e) {
      setErr(`Error: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const reliabilityLabels = labelsQuery.data?.reliability ?? {};

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{mode === "edit" ? "Edit Source Rating" : "Add Source Rating"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="relative flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Source Name</Label>
            <Input
              ref={inputRef}
              value={source}
              disabled={mode === "edit"}
              placeholder="Start typing…"
              onChange={(e) => {
                setSource(e.target.value);
                setDdOpen(true);
                setActiveIdx(-1);
              }}
              onFocus={() => mode === "add" && setDdOpen(true)}
              onBlur={() => setTimeout(() => setDdOpen(false), 150)}
              onKeyDown={handleSourceKeyDown}
              className="text-xs"
            />
            {mode === "add" && ddOpen && (
              <ul className="absolute top-full z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-popover shadow-md">
                {matches.length === 0 ? (
                  <li className="px-3 py-2 text-xs text-muted-foreground">No ungraded sources found</li>
                ) : (
                  matches.map((s, i) => (
                    <li
                      key={s}
                      className={cn(
                        "cursor-pointer px-3 py-1.5 text-xs",
                        i === activeIdx ? "bg-accent text-accent-foreground" : "hover:bg-accent",
                      )}
                      onMouseDown={() => {
                        setSource(s);
                        setDdOpen(false);
                      }}
                    >
                      {s}
                    </li>
                  ))
                )}
              </ul>
            )}
          </div>

          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Analyst Name</Label>
            <Input value={analyst} onChange={(e) => setAnalyst(e.target.value)} className="text-xs" />
          </div>

          {/* Kredibilitas tidak lagi ditanyakan: sejak P6 dihitung per artikel dari bukti (spec 2.2),
              bukan sifat sumber. */}
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Reliability Grade</Label>
            <select value={grade} onChange={(e) => setGrade(e.target.value)} className={nativeSelectClass()}>
              <option value="">— Select —</option>
              {Object.entries(reliabilityLabels).map(([g, label]) => (
                <option key={g} value={g}>
                  {g} — {label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Notes</Label>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="text-xs" />
          </div>

          {err && <p className="text-xs text-destructive">{err}</p>}
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
