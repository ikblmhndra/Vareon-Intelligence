"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { RecapDoc, RecapEnvelope, RecapKind, RecapListItem } from "@/lib/api/loose-types";
import { isClientError } from "@/lib/exec/query";
import {
  formatRange,
  isoWeek,
  isoWeekYear,
  lastFinishedWeekStart,
  mondayOf,
  previousPeriod,
  sundayOf,
} from "@/lib/recap/period";
import { apiErrorMessage } from "@/lib/recap/quality";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { RecapGenerateDialog } from "@/components/recap/recap-generate-dialog";
import { RecapPageHeader } from "@/components/recap/recap-page-header";
import { RecapView } from "@/components/recap/recap-view";
import { useCan } from "@/lib/auth/permissions";
import { usePageTitle } from "@/lib/use-page-title";

/** Recap yang dipilih; `null` = recap MINGGUAN terbaru yang tersimpan (halaman membuka itu). */
type Selection = { kind: RecapKind; date: string };

/** Query tidak diulang untuk 4xx (izin/validasi tidak sembuh sendiri); 5xx maksimal dua kali. */
const retry = (n: number, e: unknown) => n < 2 && !isClientError(e);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function useRecapHistory() {
  return useQuery({
    queryKey: ["recap", "list"],
    retry,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/recap/list", {
        params: { query: { limit: 60 } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return (data as { recaps?: RecapListItem[] } | undefined)?.recaps ?? [];
    },
  });
}

/** Yang di-cache adalah amplop balasan (`{recap, hit_rate?}`), bukan recap-nya saja: `hit_rate`
 * ikut dibaca di tempat yang sama dan diganti oleh balasan override (`recap-quality.tsx`). */
function useRecapDoc(selected: Selection | null) {
  return useQuery<RecapEnvelope>({
    queryKey: selected ? ["recap", "doc", selected.kind, selected.date] : ["recap", "doc", "latest"],
    retry,
    queryFn: async () => {
      if (!selected) {
        const { data, response } = await api.GET("/api/recap/latest");
        if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
        return (data as RecapEnvelope | undefined) ?? { recap: null };
      }
      const { data, response } = await api.GET("/api/recap/{date}", {
        params: { path: { date: selected.date }, query: { kind: selected.kind } },
      });
      if (response.status === 404) return { recap: null };
      if (!response.ok) throw new Error(`HTTP ${response.status}`, { cause: response.status });
      return (data as RecapEnvelope | undefined) ?? { recap: null };
    },
  });
}

function useGenerateRecap() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ target, force }: { target: Selection; force: boolean }) => {
      // Tanggal kosong = default server (kemarin / pekan terakhir yang sudah selesai).
      const query =
        target.kind === "weekly"
          ? { kind: "weekly" as const, week_start: target.date || undefined, force }
          : { kind: "daily" as const, date: target.date || undefined, force };
      const { data, error, response } = await api.POST("/api/recap/generate", {
        params: { query },
      });
      if (!response.ok) {
        // Pesan penolakan server (mis. pekan yang belum selesai di UTC) satu-satunya petunjuk buat pengguna.
        throw new Error(apiErrorMessage(error, response.status), { cause: response.status });
      }
      return (data as { recap: RecapDoc } | undefined)?.recap ?? null;
    },
    onSuccess: (recap) => {
      if (recap) {
        // Kunci dari balasan server (tanggal/pekan yang BENAR-BENAR dibuat), bukan dari input.
        queryClient.setQueryData<RecapEnvelope>(
          ["recap", "doc", recap.kind, recap.date],
          (old) => ({ recap, hit_rate: old?.hit_rate }),
        );
      }
      void queryClient.invalidateQueries({ queryKey: ["recap", "list"] });
      // Recap mingguan baru bisa jadi yang terbaru, dan scorecard-nya mengubah hit rate yang
      // berlaku lintas pekan: semua recap mingguan di cache diambil ulang, bukan cuma yang baru.
      void queryClient.invalidateQueries({
        queryKey: recap?.kind === "weekly" ? ["recap", "doc"] : ["recap", "doc", "latest"],
      });
    },
  });
}

/**
 * Halaman Recap. Periode yang dipilih hidup di URL (`?kind=weekly|daily&date=YYYY-MM-DD`; keduanya
 * kosong = recap mingguan terbaru), jadi tautan berfungsi (pilihan memakai `router.replace`, jadi Back tidak menelusuri pilihan) dan `selected` tidak punya
 * state sendiri. Riwayat dipilih lewat Select di header; membuat/ulang lewat dialog.
 */
function RecapPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const kindParam = params.get("kind");
  const dateParam = params.get("date") ?? "";
  // Tanggal mingguan ketikan tangan yang bukan Senin dipaku ke Senin pekannya.
  const snapped = kindParam === "weekly" ? mondayOf(dateParam) : dateParam;
  const selected: Selection | null =
    (kindParam === "weekly" || kindParam === "daily") && ISO_DATE.test(dateParam)
      ? { kind: kindParam, date: snapped }
      : null;
  useEffect(() => {
    if (kindParam === "weekly" && ISO_DATE.test(dateParam) && snapped !== dateParam)
      router.replace(`${pathname}?kind=weekly&date=${snapped}`);
  }, [kindParam, snapped, dateParam, pathname, router]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const history = useRecapHistory();
  const doc = useRecapDoc(selected);
  const generate = useGenerateRecap();
  // Generate memanggil LLM: butuh `manage_intel` (0.8.4); tanpa itu tombolnya disembunyikan.
  const canGenerate = useCan()("manage_intel");

  const recap: RecapDoc | null = doc.data?.recap ?? null;
  const empty = doc.data !== undefined && recap === null;
  // Yang tampil: pilihan eksplisit, atau recap mingguan terbaru yang dimuat `/latest`.
  const shown: Selection | null = selected ?? (recap ? { kind: recap.kind, date: recap.date } : null);
  const list = history.data ?? [];
  const existing = new Set(list.map((it) => `${it.kind}:${it.date}`));
  // Riwayat bisa belum termuat/gagal/lebih tua dari 60 teratas: recap yang sedang tampil tetap "ada",
  // kalau tidak dialog mengirim force=false dan backend mengembalikan cache tanpa regenerate.
  if (shown) existing.add(`${shown.kind}:${shown.date}`);

  usePageTitle(
    recap
      ? recap.kind === "weekly"
        ? `Weekly recap ${isoWeekYear(recap.period_start)}-W${String(isoWeek(recap.period_start)).padStart(2, "0")}`
        : `Daily recap ${recap.date}`
      : "Recap",
  );

  function select(kind: RecapKind, date: string) {
    router.replace(`${pathname}?kind=${kind}&date=${date}`);
  }

  function openDialog() {
    generate.reset();
    setDialogOpen(true);
  }

  function confirm(req: { kind: RecapKind; date: string; force: boolean }) {
    generate.mutate(
      { target: { kind: req.kind, date: req.date }, force: req.force },
      {
        onSuccess: (made) => {
          setDialogOpen(false);
          if (made) select(made.kind, made.date);
          toast.success("Recap generated");
        },
        // Dialog tetap terbuka dan menampilkan galatnya inline (400/502), jadi tanpa toast.
      },
    );
  }

  const emptyRange = selected
    ? selected.kind === "weekly"
      ? formatRange(selected.date, sundayOf(selected.date))
      : selected.date
    : null;

  return (
    <div className="pb-10">
      <RecapPageHeader
        doc={recap}
        kind={shown?.kind ?? null}
        date={shown?.date ?? null}
        list={list}
        canGenerate={canGenerate}
        onSelect={select}
        onPrevious={() => shown && select(shown.kind, previousPeriod(shown.kind, shown.date))}
        onRegenerate={openDialog}
        generating={generate.isPending}
      />

      {generate.isPending ? (
        <Notice busy tone="info" title="Generating the recap. This can take up to 30 seconds." />
      ) : (
        <>
          {doc.isPending && (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          )}
          {doc.isError && (
            <StatePanel
              variant="error"
              title="Could not load the recap"
              description={(doc.error as Error).message}
              action={
                <Button variant="outline" onClick={() => void doc.refetch()}>
                  Retry
                </Button>
              }
            />
          )}
          {recap && <RecapView doc={recap} hitRate={doc.data?.hit_rate} />}
          {empty && (
            <StatePanel
              variant="empty"
              title={
                !selected
                  ? "No weekly recap yet"
                  : selected.kind === "weekly"
                    ? `No weekly recap for ${emptyRange}`
                    : `No recap for ${emptyRange}`
              }
              description={
                canGenerate ? undefined : "Weekly recaps are generated automatically early on Mondays (UTC)."
              }
              action={canGenerate ? <Button onClick={openDialog}>Generate recap</Button> : undefined}
            />
          )}
        </>
      )}

      <RecapGenerateDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        defaultKind={shown?.kind ?? "weekly"}
        defaultDate={shown?.date ?? lastFinishedWeekStart()}
        existing={existing}
        pending={generate.isPending}
        error={generate.isError ? (generate.error as Error).message : null}
        onConfirm={confirm}
      />
    </div>
  );
}

/** `useSearchParams` butuh batas Suspense agar build tidak gagal pada prerender. */
export default function RecapPage() {
  return (
    <Suspense>
      <RecapPageInner />
    </Suspense>
  );
}
