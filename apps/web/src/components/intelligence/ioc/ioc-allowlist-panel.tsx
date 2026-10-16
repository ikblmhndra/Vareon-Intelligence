"use client";

import { XIcon } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { IocAllowlistResponse } from "@/lib/api/loose-types";

const TYPE_LABEL: Record<string, string> = { url_domain: "URL Domain", email_domain: "Email Domain", ip: "IP Address" };
const TYPES = Object.keys(TYPE_LABEL);

/** Port bagian "IOC ALLOWLIST" (`ioc_mgmt.js:411-487`) -- domain/email/IP
 * yang dikecualiin dari deteksi IOC. Add sekalian ngehapus IOC existing
 * yang match (`deleted_iocs` di respons, port apa adanya). */
export function IocAllowlistPanel() {
  const queryClient = useQueryClient();
  const [type, setType] = useState<string>(TYPES[0]);
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const query = useQuery({
    queryKey: ["intelligence", "ioc-allowlist"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/allowlist");
      if (error) throw error;
      return data as unknown as IocAllowlistResponse;
    },
  });

  async function add() {
    const v = value.trim();
    if (!v) return;
    setSubmitting(true);
    try {
      const { error } = await api.POST("/api/iocs/allowlist", {
        body: { type: type as "url_domain" | "email_domain" | "ip", value: v },
      });
      if (error) throw new Error(JSON.stringify(error));
      toast.success("Added to allowlist.");
      setValue("");
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-allowlist"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-list"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-stats"] });
    } catch (e) {
      toast.error(`Error: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(entryId: number) {
    try {
      const { error } = await api.DELETE("/api/iocs/allowlist/{entry_id}", { params: { path: { entry_id: entryId } } });
      if (error) throw new Error(JSON.stringify(error));
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-allowlist"] });
    } catch (e) {
      toast.error(`Remove failed: ${(e as Error).message}`);
    }
  }

  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-muted-foreground">IOC Allowlist</h2>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Type</Label>
          <Select items={TYPE_LABEL} value={type} onValueChange={(v) => v && setType(v)}>
            <SelectTrigger size="sm" className="w-36 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TYPES.map((t) => (
                <SelectItem key={t} value={t} className="font-mono text-xs">
                  {TYPE_LABEL[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-sm font-medium text-muted-foreground">Value</Label>
          <Input
            placeholder="e.g. example.com"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void add()}
            className="w-56 font-mono text-xs"
          />
        </div>
        <Button size="sm" disabled={submitting} onClick={() => void add()}>
          + Add
        </Button>
      </div>

      {query.isPending && <p className="py-4 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-4 text-center text-xs text-destructive">Failed to load allowlist.</p>}
      {query.data && (
        <Table framed>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Added By</TableHead>
              <TableHead>Added At</TableHead>
              <TableHead className="text-center">Remove</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.entries.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="py-4 text-center text-xs text-muted-foreground">
                  No allowlist entries
                </TableCell>
              </TableRow>
            )}
            {query.data.entries.map((e) => (
              <TableRow key={e.id}>
                <TableCell>
                  <span className="rounded-full border border-primary/25 bg-primary/10 px-1.5 py-0.5 font-mono text-xs text-primary-text">
                    {TYPE_LABEL[e.type] || e.type}
                  </span>
                </TableCell>
                <TableCell className="font-code text-xs text-foreground">{e.value}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{e.added_by || "—"}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{e.added_at.slice(0, 10)}</TableCell>
                <TableCell className="text-center">
                  <button type="button" aria-label={`Remove ${e.value} from allowlist`} onClick={() => void remove(e.id)} className="text-xs text-muted-foreground hover:text-destructive">
                    <XIcon aria-hidden />
                  </button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
