"use client";

import { useInfiniteQuery, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { daysUntil } from "@/lib/format";

export type RFIOut = components["schemas"]["RFIOut"];
export type RfiStatus = "open" | "in_progress" | "closed";

export const RFI_STATUS_OPTIONS: readonly { value: RfiStatus; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "closed", label: "Closed" },
];

export function isRfiStatus(v: string | null): v is RfiStatus {
  return v === "open" || v === "in_progress" || v === "closed";
}

export const RFI_PAGE_SIZE = 25;

/** Filter PIR tertaut: `all` = tanpa filter, `none` = RFI tanpa PIR (API tak punya filter ini, jadi disaring
 * di klien), angka = id PIR (disaring server lewat `linked_pir`). */
export type RfiPirFilter = "all" | "none" | `${number}`;

/** RFI berhalaman 25 (load more), urut jatuh tempo terdekat. `status_counts` ikut tiap halaman dan tidak
 * bergantung pada filter status, jadi halaman pertama cukup untuk lencana tab. Untuk filter "none" halaman
 * berikutnya diambil otomatis sampai habis, karena penyaringan sisi klien membuat satu halaman bisa kosong. */
export function useRfis(status: RfiStatus, q: string, pir: RfiPirFilter) {
  const query = useInfiniteQuery({
    queryKey: ["rfi", "list", status, q, pir],
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const { data, error } = await api.GET("/api/rfi", {
        params: {
          query: {
            status,
            q: q || undefined,
            linked_pir: pir === "all" || pir === "none" ? undefined : Number(pir),
            sort: "due",
            page: pageParam,
            page_size: RFI_PAGE_SIZE,
          },
        },
      });
      if (error) throw error;
      return data;
    },
    getNextPageParam: (last, all) =>
      all.reduce((n, p) => n + p.rfis.length, 0) < last.total ? last.page + 1 : undefined,
  });
  return query;
}

/** Semua kunci RFI segar lagi; PIR ikut karena kartunya memuat "Linked RFIs". */
export function invalidateRfis(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: ["rfi"] });
  void queryClient.invalidateQueries({ queryKey: ["pir"] });
}

/** Sisa waktu jatuh tempo: `tone` hanya untuk RFI yang belum closed (RFI selesai tidak perlu diwarnai). */
export function dueInfo(
  dueDate: string | null | undefined,
  status: string,
): { days: number; tone: "overdue" | "soon" | "normal"; text: string } | null {
  const days = daysUntil(dueDate);
  if (days == null) return null;
  const open = status !== "closed";
  const tone = open && days < 0 ? "overdue" : open && days <= 2 ? "soon" : "normal";
  const text =
    days < 0
      ? `${-days} ${days === -1 ? "day" : "days"} overdue`
      : days === 0
        ? "today"
        : `in ${days} ${days === 1 ? "day" : "days"}`;
  return { days, tone, text };
}

export const DUE_TONE_CLASS = {
  overdue: "font-semibold text-destructive-text",
  soon: "font-semibold text-warning-text",
  normal: "text-foreground",
} as const;
