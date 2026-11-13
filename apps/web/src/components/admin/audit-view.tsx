"use client";

import { useMemo, useState } from "react";

import { AdminFrame, AdminPageHeading } from "@/components/admin/admin-frame";
import { adminErrorMessage, useAuditLog } from "@/components/admin/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NumberedPager } from "@/components/ui/numbered-pager";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCan } from "@/lib/auth/permissions";
import { useAuditExport } from "@/lib/admin/audit-export";
import { useDebounced } from "@/lib/cve/catalog";
import { browserZoneName, fmtDateTime } from "@/lib/format";

const PAGE_SIZE = 50; // P18

/** "key: value" digabung " · "; nilai bersarang jadi JSON. */
function detailText(detail: Record<string, unknown> | null): string {
  const entries = detail ? Object.entries(detail) : [];
  if (entries.length === 0) return "–";
  return entries
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ");
}

/** Halaman Audit log. `GET /api/auth/audit-log` dan ekspor CSV butuh `view_audit_log`. */
export function AuditView() {
  const can = useCan();
  const canView = can("view_audit_log");
  const [userInput, setUserInput] = useState("");
  const [actionInput, setActionInput] = useState("");
  const [pageState, setPageState] = useState({ key: "", n: 1 });
  // Objek dimemo supaya useDebounced tidak memicu efek tiap render.
  const typed = useMemo(() => ({ user: userInput, action: actionInput }), [userInput, actionInput]);
  const filters = useDebounced(typed, 400);
  // Halaman kembali ke 1 saat filter berubah, tanpa efek tambahan.
  const filterKey = `${filters.user}\u0000${filters.action}`;
  const page = pageState.key === filterKey ? pageState.n : 1;
  const log = useAuditLog({ page, pageSize: PAGE_SIZE, ...filters }, canView);
  const exporter = useAuditExport();
  // Baris DETAIL yang dibuka penuh; tombolnya bisa difokus keyboard (title saja tak terjangkau).
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  let body;
  if (!canView) {
    body = (
      <StatePanel
        variant="no-access"
        title="You need the view_audit_log permission"
        description="The audit log is shown to users with that permission."
      />
    );
  } else if (log.isPending) {
    body = (
      <div role="status">
        <Skeleton aria-hidden className="h-64 w-full" />
        <span className="sr-only">Loading audit log</span>
      </div>
    );
  } else if (log.isError) {
    body = (
      <StatePanel
        variant="error"
        title="Failed to load the audit log"
        description={adminErrorMessage(log.error, "view_audit_log")}
        action={<Button variant="outline" size="sm" onClick={() => void log.refetch()}>Retry</Button>}
      />
    );
  } else if (log.data.logs.length === 0) {
    body = <StatePanel variant="empty" title="No audit entry matches these filters" />;
  } else {
    body = (
      <>
        <Table framed className="table-fixed" style={{ minWidth: 880 }}>
          <colgroup>
            <col style={{ width: "16%" }} />
            <col style={{ width: "13%" }} />
            <col style={{ width: "18%" }} />
            <col style={{ width: "15%" }} />
            <col style={{ width: "26%" }} />
            <col style={{ width: "12%" }} />
          </colgroup>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>{`TIME (${browserZoneName()})`}</TableHead>
              <TableHead>USER</TableHead>
              <TableHead>ACTION</TableHead>
              <TableHead>TARGET</TableHead>
              <TableHead>DETAIL</TableHead>
              <TableHead>IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {log.data.logs.map((l, i) => {
              const detail = detailText(l.detail);
              const rowKey = `${l.timestamp}-${i}`;
              const open = expanded.has(rowKey);
              return (
                <TableRow key={rowKey}>
                  <TableCell className="text-xs text-muted-foreground">{fmtDateTime(l.timestamp)}</TableCell>
                  <TableCell className="truncate font-code text-xs text-foreground" title={l.user}>
                    {l.user}
                  </TableCell>
                  <TableCell className="truncate font-code text-xs" title={l.action}>
                    {l.action}
                  </TableCell>
                  <TableCell className="truncate text-xs text-muted-foreground" title={l.target_id ?? undefined}>
                    {l.target_id || "–"}
                  </TableCell>
                  <TableCell
                    className="whitespace-normal break-words text-xs text-muted-foreground"
                  >
                    {detail ? (
                      <button
                        type="button"
                        aria-expanded={open}
                        title={open ? "Collapse detail" : "Show full detail"}
                        onClick={() =>
                          setExpanded((prev) => {
                            const next = new Set(prev);
                            if (!next.delete(rowKey)) next.add(rowKey);
                            return next;
                          })
                        }
                        className="rounded-sm text-left focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
                      >
                        <span className={open ? undefined : "line-clamp-2"}>{detail}</span>
                      </button>
                    ) : (
                      <span>{detail}</span>
                    )}
                  </TableCell>
                  <TableCell className="truncate font-code text-xs text-muted-foreground" title={l.ip || undefined}>
                    {l.ip || "–"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <NumberedPager
          page={page}
          totalPages={Math.ceil(log.data.total / PAGE_SIZE)}
          onPageChange={(n) => setPageState({ key: filterKey, n })}
          label="Audit log pages"
          summary={`${log.data.total} entries`}
        />
      </>
    );
  }

  return (
    <AdminFrame page="audit">
      <AdminPageHeading title="Audit log" description="Every admin action and sign-in, newest first." />
      {canView && (
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="audit-user" className="text-xs font-medium text-muted-foreground">
              User
            </Label>
            <Input
              id="audit-user"
              autoComplete="off"
              placeholder="all"
              value={userInput}
              onChange={(e) => setUserInput(e.target.value)}
              className="w-40 font-code text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="audit-action" className="text-xs font-medium text-muted-foreground">
              Action
            </Label>
            <Input
              id="audit-action"
              autoComplete="off"
              placeholder="all"
              value={actionInput}
              onChange={(e) => setActionInput(e.target.value)}
              className="w-48 font-code text-xs"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            disabled={exporter.pending || typed !== filters}
            onClick={() => exporter.run(filters)}
          >
            {exporter.pending ? (exporter.label ?? "Exporting…") : "Export CSV"}
          </Button>
        </div>
      )}
      {body}
    </AdminFrame>
  );
}
