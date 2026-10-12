"use client";

import { PaletteIcon } from "lucide-react";
import { useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { TemplateState } from "@/components/newsletter/types";

interface Props {
  value: TemplateState;
  onChange: (value: TemplateState) => void;
}

const CLUSTER_DAYS_ITEMS: Record<string, string> = { "7": "7 days", "14": "14 days", "30": "30 days" };

/** Port "Customize Template" collapsible (`newsletter.html:353-396`) --
 * custom CSS/footer buat email + toggle "Include Top Campaign
 * Clusters" (`include_clusters`/`cluster_days`, jalan sejak Fase 7.4
 * Grup A, `services/newsletter.py::build_newsletter_context`). Custom
 * Intro pindah ke blok Executive Summary di atas composer (field yang
 * sama, `custom_intro`; PR 9). */
export function NewsletterTemplatePanel({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);

  function set<K extends keyof TemplateState>(key: K, v: TemplateState[K]) {
    onChange({ ...value, [key]: v });
  }

  return (
    <div className="mt-6 border-t border-border pt-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 text-sm font-semibold text-primary"
      >
        <PaletteIcon aria-hidden /> Customize Template
        <span className="ml-auto text-xs text-muted-foreground">{open ? "▼ collapse" : "▶ expand"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div>
            <Label className="mb-1 block text-sm font-medium text-muted-foreground">Custom CSS — whole email</Label>
            <Textarea
              value={value.customCss}
              onChange={(e) => set("customCss", e.target.value)}
              placeholder="/* Override any styles, e.g.: .header { background: #1a1a1a; } */"
              className="h-20 resize-y font-mono text-xs"
            />
          </div>
          <div>
            <Label className="mb-1 block text-sm font-medium text-muted-foreground">
              Custom Footer — replaces default footer (HTML allowed)
            </Label>
            <Textarea
              value={value.customFooter}
              onChange={(e) => set("customFooter", e.target.value)}
              placeholder="<p>CTI Team &middot; Internal &mdash; Confidential</p>"
              className="h-14 resize-y font-mono text-xs"
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-foreground">
              <Checkbox checked={value.includeClusters} onCheckedChange={(v) => set("includeClusters", v === true)} />
              Include Top Campaign Clusters section
            </label>
            <span className="font-mono text-xs text-muted-foreground">Lookback:</span>
            <Select
              items={CLUSTER_DAYS_ITEMS}
              value={String(value.clusterDays)}
              onValueChange={(v) => v && set("clusterDays", Number(v))}
            >
              <SelectTrigger size="sm" className="w-28 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(CLUSTER_DAYS_ITEMS).map(([val, label]) => (
                  <SelectItem key={val} value={val} className="font-mono text-xs">
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
    </div>
  );
}
