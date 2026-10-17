"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { DomainBadges } from "@/components/intelligence/attack-db/domain-badges";
import type { AttackTechniquesResponse } from "@/lib/api/loose-types";
import type { DetailTarget } from "@/components/intelligence/attack-db/attack-detail-dialog";

const PAGE_SIZE = 50;
const ALL = "__all__";
const DOMAINS = ["enterprise-attack", "ics-attack", "mobile-attack"];
const DOMAIN_LABELS: Record<string, string> = { "enterprise-attack": "Enterprise", "ics-attack": "ICS", "mobile-attack": "Mobile" };

/** Port sub-tab Techniques (`attack_db.js:163-214`). */
export function TechniquesPanel({ onSelect }: { onSelect: (target: DetailTarget) => void }) {
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [tactic, setTactic] = useState("");
  const [subs, setSubs] = useState("");
  const [page, setPage] = useState(1);

  const tacticsQuery = useQuery({
    queryKey: ["intelligence", "attack-tactics-distinct", domain],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/tactics/distinct", { params: { query: { domain: domain || undefined } } });
      if (error) throw error;
      return data;
    },
  });

  const query = useQuery({
    queryKey: ["intelligence", "attack-techniques", search, domain, tactic, subs, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/techniques", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            search: search || undefined,
            domain: domain || undefined,
            tactic: tactic || undefined,
            is_subtechnique: subs ? subs === "true" : undefined,
          },
        },
      });
      if (error) throw error;
      return data as unknown as AttackTechniquesResponse;
    },
  });

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Search</Label>
          <Input
            placeholder="Technique name…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-44 font-mono text-xs"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Domain</Label>
          <Select
            items={{ [ALL]: "All Domains", ...Object.fromEntries(DOMAINS.map((d) => [d, DOMAIN_LABELS[d]])) }}
            value={domain || ALL}
            onValueChange={(v) => {
              setDomain(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-32 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Domains
              </SelectItem>
              {DOMAINS.map((d) => (
                <SelectItem key={d} value={d} className="font-mono text-xs">
                  {DOMAIN_LABELS[d]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Tactic</Label>
          <Select
            items={{ [ALL]: "All Tactics", ...Object.fromEntries((tacticsQuery.data ?? []).map((t) => [t, t.replace(/-/g, " ")])) }}
            value={tactic || ALL}
            onValueChange={(v) => {
              setTactic(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All Tactics
              </SelectItem>
              {(tacticsQuery.data ?? []).map((t) => (
                <SelectItem key={t} value={t} className="font-mono text-xs capitalize">
                  {t.replace(/-/g, " ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Type</Label>
          <Select
            items={{ [ALL]: "All", true: "Sub-techniques", false: "Techniques only" }}
            value={subs || ALL}
            onValueChange={(v) => {
              setSubs(v === ALL ? "" : (v ?? ""));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL} className="font-mono text-xs">
                All
              </SelectItem>
              <SelectItem value="false" className="font-mono text-xs">
                Techniques only
              </SelectItem>
              <SelectItem value="true" className="font-mono text-xs">
                Sub-techniques
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {query.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-6 text-center text-xs text-destructive">Error loading techniques</p>}
      {query.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Tactics</TableHead>
                <TableHead>Domains</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.techniques.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-xs text-muted-foreground">
                    No techniques found
                  </TableCell>
                </TableRow>
              )}
              {query.data.techniques.map((t) => (
                <TableRow key={t.attack_id} className="cursor-pointer" onClick={() => onSelect({ kind: "technique", id: t.attack_id })}>
                  <TableCell className="font-code text-[13px] text-primary whitespace-nowrap">{t.attack_id}</TableCell>
                  <TableCell className="text-xs">
                    {t.is_subtechnique ? "↳ " : ""}
                    {t.name}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{t.tactics.join(", ")}</TableCell>
                  <TableCell>
                    <DomainBadges domains={t.domains} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-3 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} totalLabel={`${total} total`} onPageChange={setPage} />
          </div>
        </>
      )}
    </div>
  );
}
