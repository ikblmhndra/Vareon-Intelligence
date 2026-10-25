"use client";

import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { components } from "@/lib/api/schema";
import { D3fendToggle } from "@/components/newsroom/d3fend-toggle";
import { addToQueue } from "@/lib/newsletter/queue";

type Article = components["schemas"]["ArticleOut"];

const TYPE_COLORS: Record<string, string> = {
  apac: "var(--info)",
  global: "var(--info)",
  ransomware: "var(--severity-critical)",
  indonesia: "var(--success)",
};

const IOC_FIELD_LABEL: Record<string, string> = {
  ips: "IP",
  domains: "Domain",
  urls: "URL",
  urls_with_path: "URL+Path",
  emails: "Email",
  sha256: "SHA256",
  sha1: "SHA1",
  md5: "MD5",
  cves: "CVE",
};

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-sm font-semibold text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

function Tags({ items }: { items: { label: string; suffix?: string; variant?: "outline" | "destructive" }[] }) {
  if (!items.length) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it, i) => (
        <Badge key={`${it.label}-${i}`} variant={it.variant ?? "outline"} className="text-xs">
          {it.label}
          {it.suffix && <span className="ml-1 text-xs opacity-70">{it.suffix}</span>}
        </Badge>
      ))}
    </div>
  );
}

function exportIocsCsv(a: Article) {
  const fieldToType: Record<string, string> = {
    ips: "ip",
    domains: "domain",
    urls: "url",
    emails: "email",
    sha256: "sha256",
    sha1: "sha1",
    md5: "md5",
    cves: "cve",
  };
  const rows: string[][] = [["type", "value", "article_title", "article_url", "article_source", "article_date"]];
  for (const [field, vals] of Object.entries(a.iocs ?? {})) {
    const type = fieldToType[field] ?? field;
    for (const v of Array.isArray(vals) ? vals : []) {
      rows.push([type, String(v), a.title, a.url, a.source, a.posted_on]);
    }
  }
  const csv = rows.map((r) => r.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `iocs_${a.title.slice(0, 40).replace(/[^a-z0-9]/gi, "_")}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * Port `openModal()` (`modal.js`). Admiralty/source-reliability badge di
 * meta bar SENGAJA belum diport (Source Reliability punya `/intelligence`,
 * Grup G). IOC section terstruktur tapi PASTI kosong sekarang --
 * `ArticleOut.iocs` SELALU `{}` (linkage artikel<->IOC belum diport,
 * placeholder yang udah didokumentasikan sejak schema Fase 7.3), bukan
 * bug di sini.
 */
export function ArticleModal({ article: a, onOpenChange }: { article: Article | null; onOpenChange: (open: boolean) => void }) {
  const [queueLabel, setQueueLabel] = useState("+ Newsletter");

  if (!a) return null;

  const dotColor = TYPE_COLORS[a.news_type] ?? "var(--muted-foreground)";
  const victimCountries = a.victim_countries ?? [];
  const actorCountries = a.actor_countries ?? [];
  const mentionedCountries = a.mentioned_countries ?? [];
  const hasRoles = victimCountries.length > 0 || actorCountries.length > 0;
  const countryTags = hasRoles
    ? [
        ...victimCountries.map((c) => ({ label: c, suffix: "VICTIM" })),
        ...actorCountries.map((c) => ({ label: c, suffix: "ORIGIN", variant: "destructive" as const })),
      ]
    : mentionedCountries.map((c) => ({ label: c }));

  const iocEntries = Object.entries(a.iocs ?? {}).filter(
    ([, v]) => Array.isArray(v) && v.length > 0,
  ) as [string, string[]][];

  function handleQueue() {
    const result = addToQueue(a!);
    setQueueLabel(result === "already" ? "Already queued" : "Queued");
    setTimeout(() => setQueueLabel("+ Newsletter"), 1500);
  }

  return (
    <Dialog open={a !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-start gap-2 font-heading text-sm leading-snug">
            <span
              className="mt-1.5 size-2.5 shrink-0 rounded-full"
              style={{ background: dotColor, boxShadow: `0 0 6px ${dotColor}` }}
            />
            {a.title}
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-wrap gap-x-6 gap-y-1 border-b border-border pb-3 text-xs">
          <div>
            <span className="text-muted-foreground">Source </span>
            <span className="text-foreground">{a.source}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Published </span>
            <span className="text-foreground">{a.posted_on}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Type </span>
            <span className="text-foreground">{a.news_type}</span>
          </div>
        </div>

        <div className="space-y-4">
          <Section title="Impacted Industries">
            <Tags items={(a.impacted_industries ?? []).map((i) => ({ label: i }))} />
          </Section>

          <Section title="Countries">
            <Tags items={countryTags} />
          </Section>

          <Section title="Threat Actors">
            <Tags items={(a.threat_actors ?? []).map((t) => ({ label: t, variant: "destructive" as const }))} />
          </Section>

          <Section title="MITRE ATT&CK TTPs">
            {a.ttps.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Technique ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="w-32">D3FEND</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {a.ttps.map((t) => (
                    <TableRow key={t.id}>
                      <TableCell className="font-code text-xs text-primary">{t.id}</TableCell>
                      <TableCell className="text-xs">{t.name}</TableCell>
                      <TableCell>
                        <D3fendToggle ttpId={t.id} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <span className="text-xs text-muted-foreground">No TTPs recorded</span>
            )}
          </Section>

          {iocEntries.length > 0 && (
            <Section title="Indicators of Compromise">
              <div className="flex flex-col gap-1.5">
                {iocEntries.map(([field, vals]) => (
                  <div key={field} className="flex items-start gap-2">
                    <Badge variant="outline" className="border-warning/30 bg-warning/10 font-mono text-xs text-warning-text">
                      {IOC_FIELD_LABEL[field] ?? field.toUpperCase()}
                    </Badge>
                    <div className="flex flex-wrap gap-1">
                      {vals.map((v) => (
                        <span
                          key={v}
                          className="rounded border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-xs text-foreground"
                        >
                          {v}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={handleQueue}>
            {queueLabel}
          </Button>
          {iocEntries.length > 0 && (
            <Button variant="outline" size="sm" onClick={() => exportIocsCsv(a)}>
              Export IOCs (CSV)
            </Button>
          )}
          <Button size="sm" nativeButton={false} render={<a href={a.url} target="_blank" rel="noopener noreferrer" />}>
            Open Article ↗
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
