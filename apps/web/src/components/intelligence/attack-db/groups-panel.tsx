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
import type { AttackGroupsResponse } from "@/lib/api/loose-types";
import type { DetailTarget } from "@/components/intelligence/attack-db/attack-detail-dialog";

const PAGE_SIZE = 50;
const ALL = "__all__";
const DOMAINS = ["enterprise-attack", "ics-attack", "mobile-attack"];
const DOMAIN_LABELS: Record<string, string> = { "enterprise-attack": "Enterprise", "ics-attack": "ICS", "mobile-attack": "Mobile" };

/** Port sub-tab Groups (`attack_db.js:216-263`). */
export function GroupsPanel({ onSelect }: { onSelect: (target: DetailTarget) => void }) {
  const [search, setSearch] = useState("");
  const [domain, setDomain] = useState("");
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["intelligence", "attack-groups", search, domain, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/attack/groups", {
        params: { query: { page, page_size: PAGE_SIZE, search: search || undefined, domain: domain || undefined } },
      });
      if (error) throw error;
      return data as unknown as AttackGroupsResponse;
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
            placeholder="Group name…"
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
      </div>

      {query.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-6 text-center text-xs text-destructive">Error loading groups</p>}
      {query.data && (
        <>
          <Table framed>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Aliases</TableHead>
                <TableHead>Domains</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.groups.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="py-6 text-center text-xs text-muted-foreground">
                    No groups found
                  </TableCell>
                </TableRow>
              )}
              {query.data.groups.map((g) => (
                <TableRow key={g.group_id} className="cursor-pointer" onClick={() => onSelect({ kind: "group", id: g.group_id })}>
                  <TableCell className="font-mono text-xs text-primary whitespace-nowrap">{g.group_id}</TableCell>
                  <TableCell className="text-xs">{g.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{g.aliases.slice(0, 3).join(", ")}</TableCell>
                  <TableCell>
                    <DomainBadges domains={g.domains} />
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
