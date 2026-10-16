"use client";

import { useEffect, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimplePager } from "@/components/pager";
import { useAuditLog } from "@/components/admin/hooks";

const PAGE_SIZES = [25, 50, 100];

/** Port section "Audit Log" + `loadAuditLog()`. `require_admin`. Filter
 * teks di-debounce 400ms (port `_umAuditDebounce()`). */
export function AuditLogSection() {
  const [userFilter, setUserFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [debounced, setDebounced] = useState({ user: "", action: "" });
  const [pageSize, setPageSize] = useState(25);
  const [page, setPage] = useState(1);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced({ user: userFilter, action: actionFilter });
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [userFilter, actionFilter]);

  const log = useAuditLog({ page, pageSize, user: debounced.user, action: debounced.action });
  const totalPages = log.data ? Math.ceil(log.data.total / pageSize) : 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base font-semibold text-foreground">
          Audit Log
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Input
            placeholder="Filter user…"
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className="w-36 font-mono text-xs"
          />
          <Input
            placeholder="Filter action…"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="w-44 font-mono text-xs"
          />
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              if (!v) return;
              setPageSize(Number(v));
              setPage(1);
            }}
          >
            <SelectTrigger size="sm" className="w-24 font-mono text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((s) => (
                <SelectItem key={s} value={String(s)} className="font-mono text-xs">
                  {`${s} / pg`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {log.data && (
            <span className="ml-auto font-mono text-xs text-muted-foreground">
              {log.data.total} entries
            </span>
          )}
        </div>

        {log.isPending && <Skeleton className="h-40 w-full" />}
        {log.isError && <p className="text-sm text-destructive">Failed to load audit log.</p>}
        {log.data && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Target</TableHead>
                  <TableHead>Detail</TableHead>
                  <TableHead>IP</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {log.data.logs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-xs text-muted-foreground">
                      No entries found.
                    </TableCell>
                  </TableRow>
                )}
                {log.data.logs.map((l, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {l.timestamp.replace("T", " ").split(".")[0]}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-primary">{l.user}</TableCell>
                    <TableCell className="text-xs">{l.action}</TableCell>
                    <TableCell className="max-w-[140px] truncate text-xs text-muted-foreground">
                      {l.target_id || "—"}
                    </TableCell>
                    <TableCell className="max-w-[180px] truncate font-mono text-xs text-muted-foreground">
                      {l.detail && Object.keys(l.detail).length ? JSON.stringify(l.detail) : "—"}
                    </TableCell>
                    <TableCell className="font-code text-xs text-muted-foreground">{l.ip}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="mt-3">
              <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
