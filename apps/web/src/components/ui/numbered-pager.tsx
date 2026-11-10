"use client";

import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";

interface NumberedPagerProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  label?: string;
  /** Teks kiri pengganti "Page {page} of {N}" (mis. "Showing 1-25 of 96"); tetap tampil walau hanya satu halaman. */
  summary?: string;
}

/** Halaman yang ditampilkan: selalu 1 dan N, jendela +-1 di sekitar halaman aktif, "..." untuk celah. */
function pageList(page: number, total: number): (number | "gap-start" | "gap-end")[] {
  const keep = new Set([1, total, page - 1, page, page + 1].filter((p) => p >= 1 && p <= total));
  const sorted = [...keep].sort((a, b) => a - b);
  const out: (number | "gap-start" | "gap-end")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push(i === sorted.length - 1 ? "gap-end" : "gap-start");
    out.push(p);
  });
  return out;
}

/** Pager bernomor `< 1 2 3 ... N >` + teks "Page {page} of {N}". Disusun dari bagian `pagination.tsx`. */
export function NumberedPager({
  page,
  totalPages,
  onPageChange,
  label = "pagination",
  summary,
}: NumberedPagerProps) {
  if (totalPages <= 1) return summary ? <p className="pt-3 text-xs text-muted-foreground">{summary}</p> : null;
  const go = (p: number) => (e: React.MouseEvent) => {
    e.preventDefault();
    if (p >= 1 && p <= totalPages && p !== page) onPageChange(p);
  };
  return (
    <div className="flex items-center justify-between gap-3 pt-3 max-lg:flex-col">
      <p className="text-xs text-muted-foreground">
        {summary ?? `Page ${page} of ${totalPages}`}
      </p>
      <Pagination aria-label={label} className="mx-0 w-auto">
        <PaginationContent>
          <PaginationItem>
            <PaginationPrevious
              href="#"
              text=""
              aria-disabled={page <= 1}
              onClick={go(page - 1)}
              className={page <= 1 ? "pointer-events-none opacity-50" : undefined}
            />
          </PaginationItem>
          {pageList(page, totalPages).map((p) => (
            <PaginationItem key={p}>
              {typeof p === "number" ? (
                <PaginationLink
                  href="#"
                  isActive={p === page}
                  aria-label={`Page ${p}`}
                  onClick={go(p)}
                >
                  {p}
                </PaginationLink>
              ) : (
                <PaginationEllipsis />
              )}
            </PaginationItem>
          ))}
          <PaginationItem>
            <PaginationNext
              href="#"
              text=""
              aria-disabled={page >= totalPages}
              onClick={go(page + 1)}
              className={page >= totalPages ? "pointer-events-none opacity-50" : undefined}
            />
          </PaginationItem>
        </PaginationContent>
      </Pagination>
    </div>
  );
}
