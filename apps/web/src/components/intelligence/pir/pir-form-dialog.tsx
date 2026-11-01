"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { components } from "@/lib/api/schema";
import { MultiSelectField } from "@/components/intelligence/pir/multi-select-field";
import { COUNTRIES, countryName } from "@/lib/countries";
import { EntityAutocomplete } from "@/components/entities/entity-autocomplete";

type PIROut = components["schemas"]["PIROut"];

const PRIORITIES = ["P1", "P2", "P3"];
const STATUSES = ["active", "paused", "archived"];

interface PirFormDialogProps {
  pir?: PIROut | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

function toOptions(values: string[]): { value: string; label: string }[] {
  return values.map((v) => ({ value: v, label: v }));
}

/** Port modal Add/Edit PIR (`pir.js:193-265`, `openPirModal`/`savePir`) +
 * multi-select criteria (`exec.js`'s `_pirMsXxx`, di sini jadi
 * `MultiSelectField`). */
export function PirFormDialog({ pir, open, onClose, onSaved }: PirFormDialogProps) {
  const isEdit = Boolean(pir);
  const [title, setTitle] = useState(pir?.title ?? "");
  const [description, setDescription] = useState(pir?.description ?? "");
  const [priority, setPriority] = useState(pir?.priority ?? "P2");
  const [owner, setOwner] = useState(pir?.owner ?? "");
  const [status, setStatus] = useState(pir?.status ?? "active");
  const [startDate, setStartDate] = useState(pir?.start_date ?? "");
  const [endDate, setEndDate] = useState(pir?.end_date ?? "");
  const [keywords, setKeywords] = useState((pir?.criteria.keywords ?? []).join(", "));
  const [threatActors, setThreatActors] = useState<string[]>(pir?.criteria.threat_actors ?? []);
  const [malware, setMalware] = useState<string[]>(pir?.criteria.malware ?? []);
  const [industries, setIndustries] = useState<string[]>(pir?.criteria.industries ?? []);
  const [countries, setCountries] = useState<string[]>(pir?.criteria.countries ?? []);
  const [newsTypes, setNewsTypes] = useState<string[]>(pir?.criteria.news_types ?? []);
  const [ttps, setTtps] = useState<string[]>(pir?.criteria.ttps ?? []);
  const [saving, setSaving] = useState(false);

  const optionsQuery = useQuery({
    queryKey: ["intelligence", "pir-options"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir/options");
      if (error) throw error;
      return data;
    },
  });

  async function submit() {
    if (!title.trim()) {
      toast.error("Title is required");
      return;
    }
    setSaving(true);
    try {
      const criteria = {
        threat_actors: threatActors,
        malware,
        industries,
        countries,
        news_types: newsTypes,
        ttps,
        keywords: keywords.split(",").map((s) => s.trim()).filter(Boolean),
      };
      if (isEdit && pir) {
        const { error } = await api.PUT("/api/pir/{pir_id}", {
          params: { path: { pir_id: pir.id } },
          body: {
            title,
            description,
            priority,
            owner,
            criteria,
            status,
            start_date: startDate || null,
            end_date: endDate || null,
          },
        });
        if (error) throw new Error(JSON.stringify(error));
        toast.success("PIR updated.");
      } else {
        const { error } = await api.POST("/api/pir", {
          body: {
            title,
            description,
            priority,
            owner,
            criteria,
            start_date: startDate || undefined,
            end_date: endDate || undefined,
          },
        });
        if (error) throw new Error(JSON.stringify(error));
        toast.success("PIR created.");
      }
      onSaved();
      onClose();
    } catch (e) {
      toast.error(`Error: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const opts = optionsQuery.data;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] w-full max-w-xl overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit PIR" : "New PIR"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Title</Label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} className="text-xs" />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-sm font-medium text-muted-foreground">Description</Label>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className="text-xs" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Priority</Label>
              <Select value={priority} onValueChange={(v) => v && setPriority(v)}>
                <SelectTrigger size="sm" className="w-full font-mono text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITIES.map((p) => (
                    <SelectItem key={p} value={p} className="font-mono text-xs">
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Owner</Label>
              <Input value={owner} onChange={(e) => setOwner(e.target.value)} className="text-xs" />
            </div>
          </div>

          {isEdit && (
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Status</Label>
              <Select value={status} onValueChange={(v) => v && setStatus(v)}>
                <SelectTrigger size="sm" className="w-full font-mono text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUSES.map((s) => (
                    <SelectItem key={s} value={s} className="font-mono text-xs">
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">Start Date</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="text-xs" />
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-sm font-medium text-muted-foreground">End Date</Label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="text-xs" />
            </div>
          </div>

          <div className="border-t border-border pt-3">
            <p className="mb-2 text-sm font-semibold text-muted-foreground">Match Criteria</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <EntityAutocomplete label="Threat Actors" types={["intrusion-set"]} value={threatActors} onChange={setThreatActors} />
              <EntityAutocomplete label="Malware and tools" types={["malware", "tool"]} value={malware} onChange={setMalware} />
              <EntityAutocomplete label="Industries" types={["identity"]} identityClass="class" value={industries} onChange={setIndustries} />
              {/* Negara disimpan sebagai kode ISO (sama seperti opsi lama), TTP sebagai id teknik. */}
              <EntityAutocomplete
                label="Countries"
                types={["location"]} store="external_id"
                value={countries}
                onChange={setCountries}
                labelFor={(c) => countryName(c)}
                resolveTyped={(t) =>
                  COUNTRIES.find((c) => c.code.toLowerCase() === t.toLowerCase() || c.name.toLowerCase() === t.toLowerCase())?.code ?? null
                }
                invalidMessage="Pick a country from the list"
                help="Use a country from the list to match articles"
              />
              <MultiSelectField label="News Types" options={toOptions(opts?.news_types ?? [])} selected={newsTypes} onChange={setNewsTypes} />
              <EntityAutocomplete
                label="TTPs"
                types={["attack-pattern"]} store="external_id"
                showId
                value={ttps}
                onChange={setTtps}
                labelFor={(id) => opts?.ttps.find((t) => t.id === id)?.name}
                resolveTyped={(t) => (/^T\d{4}(\.\d{3})?$/i.test(t) ? t.toUpperCase() : null)}
                invalidMessage="Pick a technique from the list"
              />
              <div className="flex flex-col gap-1">
                <Label htmlFor="pir-keywords" className="text-sm font-medium text-muted-foreground">Keywords (comma-separated)</Label>
                <Input id="pir-keywords" value={keywords} onChange={(e) => setKeywords(e.target.value)} className="text-xs" />
              </div>
            </div>
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
