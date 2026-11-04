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
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
import { InferredTtpsSection } from "@/components/newsroom/inferred-ttps-section";
import { HuntPanel } from "@/components/hunt/hunt-panel";
import { CredibilityOverride } from "@/components/newsroom/credibility-override";
import { GradeChip } from "@/components/newsroom/grade-chip";
import { gradeLines } from "@/components/newsroom/score-reasons";
import { useCan } from "@/lib/auth/permissions";
import { addToQueue } from "@/lib/newsletter/queue";
import { EntityChip, EntityChipList } from "@/components/entities/entity-chip";
import {
  actorChips,
  countryChip,
  malwareChips,
  sectorChips,
  techniqueChips,
} from "@/lib/entities/article-refs";

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

const TTP_SOURCE_BADGE: Record<string, string> = { explicit: "ID", keyword: "KW", llm: "LLM" };

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
 * Port `openModal()` (`modal.js`). Kode Admiralty + prioritas artikel tampil
 * di meta bar, alasannya di "Why this grade", plus override kredibilitas
 * untuk `manage_intel` (P6 bagian 6). IOC section terstruktur tapi PASTI kosong sekarang --
 * `ArticleOut.iocs` SELALU `{}` (linkage artikel<->IOC belum diport,
 * placeholder yang udah didokumentasikan sejak schema Fase 7.3), bukan
 * bug di sini.
 */
export function ArticleModal({ article, onOpenChange }: { article: Article | null; onOpenChange: (open: boolean) => void }) {
  const [queueLabel, setQueueLabel] = useState("+ Newsletter");
  const can = useCan();
  // Hasil override kredibilitas: `article` dipegang state induk dan tidak ikut refetch, jadi
  // versi terbaru dari API disimpan di sini selama artikel yang sama masih dibuka.
  const [updated, setUpdated] = useState<Article | null>(null);

  if (!article) return null;
  const a = updated?.id === article.id ? updated : article;

  const dotColor = TYPE_COLORS[a.news_type] ?? "var(--muted-foreground)";
  const victimCountries = a.victim_countries ?? [];
  const actorCountries = a.actor_countries ?? [];
  const mentionedCountries = a.mentioned_countries ?? [];
  const hasRoles = victimCountries.length > 0 || actorCountries.length > 0;
  // Negara: chip entity + penanda peran (VICTIM/ORIGIN) di sebelahnya bila ada peran.
  const countryItems = hasRoles
    ? [
        ...victimCountries.map((c) => ({ chip: countryChip(a, c, "victim"), role: "VICTIM", k: `v-${c}` })),
        ...actorCountries.map((c) => ({ chip: countryChip(a, c, "actor"), role: "ORIGIN", k: `a-${c}` })),
      ]
    : mentionedCountries.map((c) => ({ chip: countryChip(a, c, "mentioned"), role: undefined, k: `m-${c}` }));
  const ttpChips = techniqueChips(a);

  const iocEntries = Object.entries(a.iocs ?? {}).filter(
    ([, v]) => Array.isArray(v) && v.length > 0,
  ) as [string, string[]][];

  function handleQueue() {
    const result = addToQueue(a);
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
          {a.admiralty_code && (
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground">Grade </span>
              <GradeChip a={a} />
            </div>
          )}
        </div>

        {a.classify_inherited_from != null && (
          <p className="text-xs text-muted-foreground">Klasifikasi diwarisi dari artikel lead</p>
        )}

        <div className="space-y-4">
          {a.admiralty_code && (
            <Section title="Why this grade">
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-foreground">
                {gradeLines(a).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              {can("manage_intel") && <CredibilityOverride key={a.id} article={a} onSaved={setUpdated} />}
            </Section>
          )}

          <Section title="Impacted Industries">
            <div className="flex flex-wrap items-center gap-1.5">
              {sectorChips(a).length ? (
                <EntityChipList items={sectorChips(a)} max={12} />
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
              {a.industry_source === "keyword" && (
                <Tooltip>
                  <TooltipTrigger render={<span tabIndex={0} />}>
                    <Badge variant="secondary" className="text-xs">KW</Badge>
                  </TooltipTrigger>
                  <TooltipContent>Industries matched by keyword</TooltipContent>
                </Tooltip>
              )}
            </div>
          </Section>

          <Section title="Countries">
            {countryItems.length ? (
              <div className="flex flex-wrap gap-1.5">
                {countryItems.map((c) => (
                  <span key={c.k} className="inline-flex items-center gap-1">
                    <EntityChip {...c.chip} />
                    {c.role && <span className="text-2xs text-muted-foreground">{c.role}</span>}
                  </span>
                ))}
              </div>
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </Section>

          <Section title="Threat Actors">
            {actorChips(a).length ? (
              <EntityChipList items={actorChips(a)} max={12} />
            ) : (
              <span className="text-xs text-muted-foreground">—</span>
            )}
          </Section>

          {(a.malware ?? []).length > 0 && (
            <Section title="Malware / Tools">
              <EntityChipList items={malwareChips(a)} max={12} />
            </Section>
          )}

          <Section title="MITRE ATT&CK TTPs">
            {a.ttps.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Technique ID</TableHead>
                    <TableHead>Name</TableHead>
                    <TableHead className="w-16">Source</TableHead>
                    <TableHead className="w-32">D3FEND</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {a.ttps.map((t, i) => (
                    <TableRow key={t.id}>
                      <TableCell>
                        <EntityChip {...ttpChips[i]} />
                      </TableCell>
                      <TableCell className="text-xs whitespace-normal">{t.name}</TableCell>
                      <TableCell>
                        {t.evidence ? (
                          <Tooltip>
                            <TooltipTrigger render={<span tabIndex={0} />}>
                              <Badge variant="outline" className="text-xs">{TTP_SOURCE_BADGE[t.source] ?? t.source}</Badge>
                            </TooltipTrigger>
                            <TooltipContent>{t.evidence}</TooltipContent>
                          </Tooltip>
                        ) : (
                          <Badge variant="outline" className="text-xs">{TTP_SOURCE_BADGE[t.source] ?? t.source}</Badge>
                        )}
                      </TableCell>
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

          {((a.threat_actors ?? []).length > 0 || (a.malware ?? []).length > 0) && (
            <InferredTtpsSection articleId={a.id} />
          )}

          {a.story && <HuntPanel key={a.story.id} anchorType="story" anchorId={a.story.id} />}

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
