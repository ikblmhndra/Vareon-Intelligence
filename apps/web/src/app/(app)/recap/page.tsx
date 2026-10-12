"use client";

import { RefreshCwIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { RecapDoc, RecapKind, RecapListItem } from "@/lib/api/loose-types";
import { formatRange, lastFinishedWeekStart, mondayOf, sundayOf } from "@/lib/recap/period";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { RecapHistory } from "@/components/recap/recap-history";
import { RecapView } from "@/components/recap/recap-view";

type Mode = "day" | "week";
/** Recap yang dipilih; `null` = recap MINGGUAN terbaru yang tersimpan (halaman membuka itu). */
type Selection = { kind: RecapKind; date: string };

function useRecapHistory() {
  return useQuery({
    queryKey: ["recap", "list"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/recap/list", {
        params: { query: { limit: 60 } },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (data as { recaps?: RecapListItem[] } | undefined)?.recaps ?? [];
    },
  });
}

function useRecapDoc(selected: Selection | null) {
  return useQuery({
    queryKey: selected ? ["recap", "doc", selected.kind, selected.date] : ["recap", "doc", "latest"],
    queryFn: async () => {
      if (!selected) {
        const { data, response } = await api.GET("/api/recap/latest");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return (data as { recap: RecapDoc | null } | undefined)?.recap ?? null;
      }
      const { data, response } = await api.GET("/api/recap/{date}", {
        params: { path: { date: selected.date }, query: { kind: selected.kind } },
      });
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return (data as { recap: RecapDoc } | undefined)?.recap ?? null;
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
        // `openapi-fetch` sudah membaca body-nya (`response.text()` di sini selalu kosong), jadi
        // alasannya diambil dari `error`. Pesan penolakan server, mis. pekan yang belum selesai di
        // UTC, adalah satu-satunya petunjuk buat pengguna.
        const detail = (error as { detail?: unknown } | undefined)?.detail;
        const text = typeof detail === "string" ? detail : error ? JSON.stringify(error) : "";
        throw new Error(`HTTP ${response.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
      }
      return (data as { recap: RecapDoc } | undefined)?.recap ?? null;
    },
    onSuccess: (recap) => {
      if (recap) {
        // Kunci dari balasan server (tanggal/pekan yang BENAR-BENAR dibuat), bukan dari input.
        queryClient.setQueryData(["recap", "doc", recap.kind, recap.date], recap);
      }
      void queryClient.invalidateQueries({ queryKey: ["recap", "list"] });
      // Recap mingguan baru bisa jadi yang terbaru.
      void queryClient.invalidateQueries({ queryKey: ["recap", "doc", "latest"] });
    },
  });
}

/**
 * Port `legacy/static/js/newsroom/recap.js` + `tab_recap.html`. Dua state
 * tanggal terpisah kayak lama: `inputDate` (nilai date-picker mentah) vs
 * `selected` (recap yang beneran di-query) -- LOAD baru nge-sync keduanya,
 * generate baca `inputDate` langsung (independen dari yang lagi ke-render),
 * sama persis perilaku `recapLoad()`/`recapGenerate()` lama.
 *
 * Recap MINGGUAN (#21): halaman membuka recap mingguan terbaru, history memuat dua jenis (tiap
 * item dibaca dengan `kind`-nya), dan toggle Day/Week di kontrol generate memilih jenis yang
 * di-load/di-generate. Mode Week meng-snap tanggal pilihan ke hari Senin pekannya; mode Day
 * tetap satu hari seperti dulu.
 */
export default function RecapPage() {
  const [mode, setMode] = useState<Mode>("week");
  const [inputDate, setInputDate] = useState(lastFinishedWeekStart);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [confirm, setConfirm] = useState<{ force: boolean } | null>(null);

  const history = useRecapHistory();
  const doc = useRecapDoc(selected);
  const generate = useGenerateRecap();

  const weekStart = mondayOf(inputDate);
  const target: Selection =
    mode === "week" ? { kind: "weekly", date: weekStart } : { kind: "daily", date: inputDate };
  const weekLabel = weekStart
    ? `${formatRange(weekStart, sundayOf(weekStart))} (Mon–Sun, UTC)`
    : "the last finished week";
  const dateLabel = mode === "week" ? weekLabel : inputDate || "yesterday";
  const noun = mode === "week" ? "week" : "date";
  // Yang tampil: pilihan eksplisit, atau recap mingguan terbaru yang dimuat `/latest`.
  const shown: Selection | null = selected ?? (doc.data ? { kind: doc.data.kind, date: doc.data.date } : null);

  const status = useMemo(() => {
    if (generate.isPending) return { text: "Generating… this can take 10-30s", tone: "info" as const };
    if (generate.isError) return { text: (generate.error as Error).message, tone: "err" as const };
    if (generate.isSuccess) return { text: "Generated · saved", tone: "ok" as const };
    if (doc.isFetching) return { text: "Loading…", tone: "info" as const };
    if (doc.isError) return { text: (doc.error as Error).message, tone: "err" as const };
    if (doc.data === null) {
      const text = selected
        ? `No ${selected.kind === "weekly" ? "weekly " : ""}recap stored for that ${selected.kind === "weekly" ? "week" : "date"}`
        : "No weekly recap stored yet";
      return { text, tone: "warn" as const };
    }
    if (doc.data) return { text: "Loaded", tone: "ok" as const };
    return { text: "", tone: "info" as const };
  }, [generate.isPending, generate.isError, generate.isSuccess, generate.error, doc.isFetching, doc.isError, doc.error, doc.data, selected]);

  const statusColor = {
    info: "text-muted-foreground",
    ok: "text-primary",
    err: "text-destructive",
    warn: "text-warning",
  }[status.tone];

  function handleSelectHistory(item: RecapListItem) {
    setMode(item.kind === "weekly" ? "week" : "day");
    setInputDate(item.date);
    setSelected({ kind: item.kind, date: item.date });
  }

  function handleConfirmGenerate() {
    if (!confirm) return;
    generate.mutate(
      { target, force: confirm.force },
      {
        onSuccess: (recap) => {
          if (recap) setSelected({ kind: recap.kind, date: recap.date });
        },
      },
    );
    setConfirm(null);
  }

  return (
    <div className="pb-10">
      <div className="mb-4 flex flex-wrap items-center gap-2.5 border-b border-border pb-3">
        <div role="group" aria-label="Recap period" className="flex items-center gap-1">
          <Button
            size="sm"
            variant={mode === "week" ? "default" : "outline"}
            aria-pressed={mode === "week"}
            onClick={() => setMode("week")}
          >
            Week
          </Button>
          <Button
            size="sm"
            variant={mode === "day" ? "default" : "outline"}
            aria-pressed={mode === "day"}
            onClick={() => setMode("day")}
          >
            Day
          </Button>
        </div>
        <span className="text-sm font-semibold text-muted-foreground">
          {mode === "week" ? "Week of" : "Recap Date"}
        </span>
        <Input
          type="date"
          value={inputDate}
          onChange={(e) => setInputDate(e.target.value)}
          className="w-auto font-mono text-xs"
        />
        {mode === "week" && (
          <span className="font-mono text-xs text-muted-foreground">{weekLabel}</span>
        )}
        <Button size="sm" disabled={!target.date} onClick={() => setSelected(target)}>
          Load
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setConfirm({ force: false })}>
          ↻ Generate
        </Button>
        <Button size="sm" variant="outline" onClick={() => setConfirm({ force: true })}>
          <RefreshCwIcon aria-hidden /> Force Regen
        </Button>
        <span className={`ml-auto font-mono text-xs ${statusColor}`}>{status.text}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[240px_1fr]">
        <div className="max-h-[calc(100vh-220px)] overflow-y-auto rounded-2xl border border-border bg-surface shadow-sm p-2.5">
          <div className="mb-2 border-b border-border pb-1.5 text-sm font-semibold text-muted-foreground">
            Recap History
          </div>
          {history.isPending && (
            <div className="space-y-1.5">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          )}
          {history.isError && <p className="p-1.5 text-xs text-destructive">Failed to load history.</p>}
          {history.data && (
            <RecapHistory items={history.data} selected={shown} onSelect={handleSelectHistory} />
          )}
        </div>

        <div className="min-h-[300px]">
          {doc.isPending && (
            <div className="space-y-2">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}
          {doc.isError && <p className="text-sm text-destructive">{(doc.error as Error).message}</p>}
          {doc.data && <RecapView doc={doc.data} />}
          {doc.data === null && (
            <div className="rounded-md border border-dashed border-border px-6 py-8 text-center">
              <p className="mb-3 font-mono text-xs text-muted-foreground">
                {selected ? (
                  <>
                    No {selected.kind === "weekly" ? "weekly " : ""}recap stored for{" "}
                    <span className="font-medium text-foreground">
                      {selected.kind === "weekly"
                        ? formatRange(selected.date, sundayOf(selected.date))
                        : selected.date}
                    </span>
                    .
                  </>
                ) : (
                  "No weekly recap has been generated yet."
                )}
              </p>
              <Button size="sm" onClick={() => setConfirm({ force: false })}>
                ↻ Generate Now
              </Button>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={mode === "week" ? "Generate Weekly Recap" : "Generate Daily Recap"}
        description={
          mode === "week"
            ? `Generate the weekly recap for ${weekLabel}? This calls the LLM and may take 10–30 seconds. A week can only be generated after its Sunday has ended in UTC.`
            : `Generate recap for ${dateLabel}? This calls the LLM and may take 10–30 seconds.`
        }
        warning={confirm?.force ? `FORCE REGEN will overwrite the existing recap for this ${noun}.` : undefined}
        confirmLabel={confirm?.force ? "Force Regen" : "Generate"}
        onConfirm={handleConfirmGenerate}
      />
    </div>
  );
}
