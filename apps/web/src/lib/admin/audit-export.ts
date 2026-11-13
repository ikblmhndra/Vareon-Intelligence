"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { AuditLogEntry } from "@/lib/api/loose-types";
import { downloadCsv, toCsv } from "@/lib/csv";
import { unwrap } from "@/lib/scrapers/queries";

const PAGE_SIZE = 200; // le=200 di router audit-log
const MAX_ROWS = 5000;

/** Ambil audit log halaman demi halaman (sekuensial, maks 25 request) lalu unduh CSV. Satu halaman gagal =
 * lempar, tanpa berkas. Timestamp tetap string ISO API (UTC); sel formula dijaga `toCsv`. */
export async function exportAuditLog(opts: {
  user: string;
  action: string;
  signal: AbortSignal;
  onProgress: (got: number, target: number) => void;
}): Promise<{ rows: number; total: number }> {
  const rows: AuditLogEntry[] = [];
  let total = 0;
  let target = MAX_ROWS;
  for (let page = 1; rows.length < target; page++) {
    opts.signal.throwIfAborted();
    const data = unwrap(
      await api.GET("/api/auth/audit-log", {
        params: {
          query: {
            page,
            page_size: PAGE_SIZE,
            user: opts.user || undefined,
            action: opts.action || undefined,
          },
        },
        signal: opts.signal,
      }),
      "Failed to load audit log",
    ) as unknown as { logs: AuditLogEntry[]; total: number };
    total = data.total;
    target = Math.min(total, MAX_ROWS);
    rows.push(...data.logs);
    opts.onProgress(Math.min(rows.length, target), target);
    if (data.logs.length === 0) break; // tidak ada halaman lagi
  }
  const kept = rows.slice(0, MAX_ROWS);
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  const name = `audit-log-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}.csv`;
  downloadCsv(
    name,
    toCsv(
      ["timestamp_utc", "user", "action", "target", "detail", "ip"],
      kept.map((r) => [
        r.timestamp,
        r.user,
        r.action,
        r.target_id,
        r.detail ? JSON.stringify(r.detail) : "",
        r.ip,
      ]),
    ),
  );
  return { rows: kept.length, total };
}

export function useAuditExport(): {
  run: (filters: { user: string; action: string }) => void;
  pending: boolean;
  label: string | null;
} {
  const [label, setLabel] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ctl = useRef<AbortController | null>(null);
  useEffect(() => () => ctl.current?.abort(), []);

  function run(filters: { user: string; action: string }) {
    if (pending) return;
    const c = new AbortController();
    ctl.current = c;
    setPending(true);
    setLabel("Exporting… 0 / 0");
    exportAuditLog({
      ...filters,
      signal: c.signal,
      onProgress: (got, target) => setLabel(`Exporting… ${got} / ${target}`),
    })
      .then(({ rows, total }) => {
        toast.success(
          total > MAX_ROWS
            ? `Exported the newest 5,000 of ${total} rows. Narrow the filters to get the rest.`
            : `Exported ${rows} rows`,
        );
      })
      .catch((e: unknown) => {
        if (c.signal.aborted) return; // pindah halaman, bukan galat
        toast.error(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => {
        if (c.signal.aborted) return; // komponen sudah unmount
        setPending(false);
        setLabel(null);
      });
  }
  return { run, pending, label };
}
