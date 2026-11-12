"use client";

import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { TemplateState } from "@/components/newsletter/types";

interface Props {
  value: TemplateState;
  onChange: (value: TemplateState) => void;
  /** Blok yang dirender: klaster kampanye, atau footer dan CSS. */
  part: "clusters" | "footer";
}

const CLUSTER_DAYS_ITEMS: Record<string, string> = { "7": "7 days", "14": "14 days", "30": "30 days" };

/** Isi "Customize Template" lama (`newsletter.html:353-396`), tanpa cangkang lipat: kini tiap
 * bagian adalah satu blok di kolom Template. Custom CSS/footer masuk email; `include_clusters` /
 * `cluster_days` menyalakan bagian "Top Campaign Clusters" (`services/newsletter.py::
 * build_newsletter_context`). Custom Intro ada di blok Executive summary (field yang sama). */
export function NewsletterTemplatePanel({ value, onChange, part }: Props) {
  function set<K extends keyof TemplateState>(key: K, v: TemplateState[K]) {
    onChange({ ...value, [key]: v });
  }

  if (part === "clusters") {
    return (
      <div className="space-y-4">
        <Switch
          checked={value.includeClusters}
          onCheckedChange={(v) => set("includeClusters", v)}
          aria-label="Include top campaign clusters"
          label="Include top campaign clusters"
        />
        {value.includeClusters && (
          <div className="flex items-center gap-3">
            <Label htmlFor="newsletter-cluster-days" className="text-xs text-muted-foreground">
              Lookback
            </Label>
            <Select items={CLUSTER_DAYS_ITEMS} value={String(value.clusterDays)} onValueChange={(v) => v && set("clusterDays", Number(v))}>
              <SelectTrigger id="newsletter-cluster-days" aria-label="Lookback" className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(CLUSTER_DAYS_ITEMS).map(([val, label]) => (
                  <SelectItem key={val} value={val}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="newsletter-custom-css" className="text-sm font-medium text-foreground">
          Custom CSS (whole email)
        </Label>
        <Textarea
          id="newsletter-custom-css"
          value={value.customCss}
          onChange={(e) => set("customCss", e.target.value)}
          placeholder="/* Override any styles, e.g.: .header { background: #1a1a1a; } */"
          className="h-28 resize-y font-code text-xs"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="newsletter-custom-footer" className="text-sm font-medium text-foreground">
          Custom footer (replaces the default footer, HTML allowed)
        </Label>
        <Textarea
          id="newsletter-custom-footer"
          value={value.customFooter}
          onChange={(e) => set("customFooter", e.target.value)}
          placeholder="<p>CTI Team &middot; Internal &mdash; Confidential</p>"
          className="h-20 resize-y font-code text-xs"
        />
      </div>
    </div>
  );
}
