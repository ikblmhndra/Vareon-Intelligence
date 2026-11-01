"use client";

import type { ReactNode } from "react";

import { SimplePager } from "@/components/pager";
import { Skeleton } from "@/components/ui/skeleton";

/** Ukuran halaman semua sub-daftar entity (stories, indicators, CVEs). */
export const SUBLIST_PAGE_SIZE = 25;

/** Kartu sub-daftar: judul, status memuat/gagal/kosong, isi tabel, dan pager (client-state). */
export function SubListSection({
  id,
  title,
  status,
  total,
  emptyText,
  page,
  onPageChange,
  children,
}: {
  id: string;
  title: string;
  status: "pending" | "error" | "success";
  total: number;
  emptyText: string;
  page: number;
  onPageChange: (page: number) => void;
  children: ReactNode;
}) {
  return (
    <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby={id}>
      <h2 id={id} className="text-base font-semibold">
        {title}
        {status === "success" && (
          <span className="ml-2 text-xs font-normal text-muted-foreground">{total} total</span>
        )}
      </h2>
      {status === "pending" ? (
        <Skeleton className="h-40 w-full" />
      ) : status === "error" ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load this list. Try again later.
        </p>
      ) : total === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <>
          {children}
          <SimplePager
            page={page}
            totalPages={Math.max(1, Math.ceil(total / SUBLIST_PAGE_SIZE))}
            onPageChange={onPageChange}
          />
        </>
      )}
    </section>
  );
}
