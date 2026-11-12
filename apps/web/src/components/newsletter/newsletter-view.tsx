"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { ConfirmDialog } from "@/components/confirm-dialog";
import type { components } from "@/lib/api/schema";
import type {
  NewsletterDraftResult,
  NewsletterPreviewResult,
  NewsletterResendResult,
  NewsletterSourceHint,
} from "@/lib/api/loose-types";
import { addToQueue, clearQueue, getQueue, removeFromQueue, type QueueArticle } from "@/lib/newsletter/queue";
import {
  SLOT_BY_KEY,
  buildRequestBody,
  emptyComposer,
  isComposerEmpty,
  locate,
  mergeSuggestion,
  move,
  place,
  placedIds,
  remove,
  swap,
  unplacedSuggestion,
  type ComposerState,
  type MergeResult,
  type SlotKey,
} from "@/lib/newsletter/composer";
import { errorMessage } from "@/lib/newsletter/format";
import { CVE_MARKER, countCveMarkers, escapeHtml, summaryToIntro } from "@/lib/newsletter/summary";
import { getActiveClientId } from "@/lib/auth/client-id";
import { isClientError } from "@/lib/exec/query";
import { monthWindow, recentMonths } from "@/lib/newsletter/period";
import { usePageTitle } from "@/lib/use-page-title";
import {
  DEFAULT_TEMPLATE_STATE,
  PREVIEW_DIALOG_CLOSED,
  SECTION_BLOCKS,
  type BlockId,
  type PreviewDialogState,
  type SummaryLanguage,
  type TemplateState,
} from "@/components/newsletter/types";
import { NewsletterQueuePanel } from "@/components/newsletter/newsletter-queue-panel";
import { NewsletterContentColumn } from "@/components/newsletter/newsletter-content-column";
import type { PoolEntry } from "@/components/newsletter/newsletter-composer-sections";
import { NewsletterSuggestionBar, type SuggestionPhase } from "@/components/newsletter/newsletter-suggestion-bar";
import { NewsletterTemplateColumn } from "@/components/newsletter/newsletter-template-column";
import { NewsletterPreviewDialog } from "@/components/newsletter/newsletter-preview-dialog";
import { NewsletterHistoryPanel } from "@/components/newsletter/newsletter-history-panel";
import { useCan } from "@/lib/auth/permissions";

type Article = components["schemas"]["ArticleOut"];
type Suggestion = components["schemas"]["NewsletterSuggestionResponse"];

type Confirm = { kind: "rebuild" } | { kind: "use-summary" } | null;

/** Satu saran = satu baris (`id`) yang bisa ditimpa rebuild (`created_at` berubah). Kuncinya dipakai
 * untuk tahu apakah saran yang sedang tampil sudah dipasang ke composer. */
function suggestionKey(s: Suggestion): string {
  return `${s.id}:${s.created_at}`;
}

type Fetched = { kind: "ok"; suggestion: Suggestion } | { kind: "none" } | { kind: "error"; message: string };

/** Galat HTTP dengan status di `cause` (supaya `isClientError` bisa menahan retry) dan `detail`
 * server bila ada. Badan kosong (502 dari proxy) tidak membawa `error`, jadi `response.ok` yang
 * menentukan, bukan `if (error)`. */
function httpError(error: unknown, status: number): Error {
  const hasDetail = !!error && typeof error === "object" && "detail" in error;
  return new Error(hasDetail ? errorMessage(error) : `HTTP ${status}`, { cause: status });
}

/** `GET /suggestion` untuk satu bulan: 404 ("No newsletter suggestion found") adalah keadaan biasa, bukan galat. */
async function fetchSuggestion(start: string, end: string): Promise<Fetched> {
  try {
    const res = await api.GET("/api/newsletter/suggestion", { params: { query: { period_start: start, period_end: end } } });
    const status = res.response.status;
    if (status === 404) return { kind: "none" };
    if (!res.response.ok || !res.data) throw httpError(res.error, status);
    return { kind: "ok", suggestion: res.data };
  } catch (e) {
    return { kind: "error", message: errorMessage(e) };
  }
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Ringkasan hasil memasang saran, untuk toast "Use suggestion" / "Merge". */
function describeMerge(r: MergeResult, mode: "replace" | "merge"): string {
  const placed = r.added + r.demoted;
  const parts = [mode === "replace" ? `Suggestion applied: ${plural(placed, "article", "articles")} placed` : `Merged ${plural(placed, "article", "articles")}`];
  if (r.demoted > 0) parts.push(`${r.demoted} moved down a tier to fit the limits`);
  if (r.skipped > 0) parts.push(`${r.skipped} did not fit the limits`);
  if (r.left > 0) parts.push(`${r.left} already in your queue were left there`);
  if (r.alreadyPlaced > 0) parts.push(`${r.alreadyPlaced} already placed`);
  return `${parts.join("; ")}.`;
}

/** Port `newsletter.html` (1261 baris, route standalone di app lama --
 * di sini route Next.js biasa `/newsletter`, nav udah disiapin Grup A
 * `app-shell/nav-items.ts`). Grup H, sub-grup terakhir Fase 8 -- numpang
 * komponen Mindmap (G5) buat "Mind Map" per histori.
 *
 * Composer baru (ROADMAP #22, PR 9): terbuka sudah terisi saran bulan itu (artikel per section dan
 * tier, plus paragraf Executive Summary) kalau antrean kosong; kalau analis sudah punya antrean,
 * saran ditawarkan lewat banner "Use suggestion" / "Merge" tanpa menimpa apa pun. Hasil kerja analis
 * hidup di state browser ini, bukan di saran tersimpan. Draft dibuat dari dialog preview, bukan
 * langsung, supaya peringatan ukuran dan penanda CVE terlihat sebelum draft ada. */
export function NewsletterView() {
  const can = useCan();
  const [state, setState] = useState<ComposerState>(emptyComposer);
  const [template, setTemplate] = useState<TemplateState>(DEFAULT_TEMPLATE_STATE);
  const [queue, setQueue] = useState<QueueArticle[]>(() => getQueue());
  // Jangkar bulan = state sekali jalan (bukan `new Date()` di render); bulan terbaru bawaan server.
  const [months] = useState(recentMonths);
  const [period, setPeriod] = useState(() => months[0].value);
  const [block, setBlock] = useState<BlockId | null>(null);
  const [language, setLanguage] = useState<SummaryLanguage>("id");
  const [regenerate, setRegenerate] = useState<ReadonlySet<number>>(new Set());
  const [bodySources, setBodySources] = useState<Record<string, string>>({});

  const [phase, setPhase] = useState<SuggestionPhase>({ kind: "loading" });
  const [appliedKey, setAppliedKey] = useState<string | null>(null);
  /** Isi field intro yang terakhir ditulis dari saran: selama field masih sama dengan ini analis
   * belum menyuntingnya, jadi rebuild boleh menggantinya tanpa bertanya. */
  const [introPrefill, setIntroPrefill] = useState("");
  const [rebuilding, setRebuilding] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);

  const [preview, setPreview] = useState<PreviewDialogState>(PREVIEW_DIALOG_CLOSED);
  const [sending, setSending] = useState(false);
  const [resendingId, setResendingId] = useState<number | null>(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // Callback async (muat saran, rebuild) membaca keadaan TERKINI lewat ref: closure-nya dibuat
  // sebelum `await`, jadi `state`/`queue` di dalamnya sudah basi saat jawaban datang.
  const latest = useRef({ state, template, queue, introPrefill });
  useEffect(() => {
    latest.current = { state, template, queue, introPrefill };
  });
  const appliedKeyRef = useRef<string | null>(null);

  const hintsQuery = useQuery({
    queryKey: ["newsletter", "source-hints"],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/newsletter/source-hints");
      if (!response.ok) throw httpError(error, response.status);
      return data as unknown as Record<string, NewsletterSourceHint>;
    },
    retry: (n, e) => n < 2 && !isClientError(e),
  });

  // ── Antrean (localStorage) ────────────────────────────────────────────────

  function pushToQueue(article: Article) {
    addToQueue(article);
    setQueue((prev) => (prev.some((a) => a._id === article.id) ? prev : [...prev, { ...article, _id: article.id } as QueueArticle]));
  }

  function popFromQueue(articleId: number) {
    removeFromQueue(articleId);
    setQueue((prev) => prev.filter((a) => a._id !== articleId));
  }

  function handleClearQueue() {
    clearQueue();
    setQueue([]);
    toast.info("Queue cleared");
  }

  // ── Saran ─────────────────────────────────────────────────────────────────

  /** Pasang artikel saran ke composer. `replace` mengganti isi composer (artikel analis yang tidak
   * ada di saran kembali ke antrean, tidak hilang; catatan dipertahankan); `merge` hanya
   * menambah yang belum ada dan tidak ada di antrean, menghormati batas. Mengembalikan hasilnya
   * untuk toast. */
  const applyArticles = useCallback((s: Suggestion, mode: "replace" | "merge"): MergeResult => {
    const cur = latest.current;
    const queuedIds = new Set(cur.queue.map((a) => a._id));
    const result =
      mode === "replace"
        ? mergeSuggestion({ ...emptyComposer(), notes: cur.state.notes }, s.items)
        : mergeSuggestion(cur.state, s.items, queuedIds);

    if (mode === "replace") {
      const placed = placedIds(result.state);
      const suggested = new Set(s.items.map((i) => i.article_id));
      // Yang ditempatkan keluar dari antrean; yang dulu ditempatkan analis dan tidak ada di saran
      // kembali ke antrean, supaya "replace" tidak membuang pilihan mereka diam-diam.
      for (const id of placed) if (queuedIds.has(id)) removeFromQueue(id);
      setQueue((prev) => prev.filter((a) => !placed.has(a._id)));
      for (const slotKey of Object.keys(cur.state.slots) as SlotKey[]) {
        for (const a of cur.state.slots[slotKey]) {
          if (!placed.has(a.id) && !suggested.has(a.id)) {
            addToQueue(a);
            setQueue((prev) => (prev.some((q) => q._id === a.id) ? prev : [...prev, { ...a, _id: a.id } as QueueArticle]));
          }
        }
      }
    }

    const key = suggestionKey(s);
    appliedKeyRef.current = key;
    setAppliedKey(key);
    setState(result.state);
    return result;
  }, []);

  /** Saran baru (dimuat atau hasil rebuild) tiba. Intro yang belum disentuh analis langsung
   * diganti; artikel hanya dipasang otomatis kalau analis belum punya apa-apa, selain itu banner
   * menawarkan pilihan. */
  const receiveSuggestion = useCallback(
    (s: Suggestion) => {
      const cur = latest.current;
      setPhase({ kind: "ready", suggestion: s });

      const intro = summaryToIntro(s.summary_text);
      const untouched = cur.template.customIntro.trim() === "" || cur.template.customIntro === cur.introPrefill;
      if (intro && untouched) {
        setTemplate((t) => ({ ...t, customIntro: intro }));
        setIntroPrefill(intro);
      }

      const key = suggestionKey(s);
      if (appliedKeyRef.current !== key && cur.queue.length === 0 && isComposerEmpty(cur.state)) {
        applyArticles(s, "replace");
      }
    },
    [applyArticles],
  );

  const handleFetched = useCallback(
    (r: Fetched) => {
      if (r.kind === "ok") receiveSuggestion(r.suggestion);
      else if (r.kind === "none") setPhase({ kind: "none" });
      else setPhase({ kind: "error", message: r.message });
    },
    [receiveSuggestion],
  );

  // Ganti bulan: saran bulan lama dilepas seketika (pola "sesuaikan state saat render"), lalu efek
  // di bawah memuat saran bulan baru. Composer dan antrean tidak disentuh.
  const [phasePeriod, setPhasePeriod] = useState(period);
  if (phasePeriod !== period) {
    setPhasePeriod(period);
    setPhase({ kind: "loading" });
  }
  const selected = useMemo(() => monthWindow(period), [period]);

  useEffect(() => {
    if (!selected) return;
    let ignore = false;
    void fetchSuggestion(selected.start, selected.end).then((r) => {
      if (!ignore) handleFetched(r);
    });
    return () => {
      ignore = true;
    };
  }, [handleFetched, selected]);

  async function retrySuggestion() {
    if (!selected) return;
    setPhase({ kind: "loading" });
    handleFetched(await fetchSuggestion(selected.start, selected.end));
  }

  // Artikel yang di-queue dari tab Newsroom lain muncul tanpa reload (`storage` hanya menembak
  // di tab LAIN, jadi tidak bentrok dengan `setQueue` lokal).
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === "newsletter_queue") setQueue(getQueue());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const suggestion = phase.kind === "ready" ? phase.suggestion : null;
  const introEdited = template.customIntro.trim() !== "" && template.customIntro !== introPrefill;

  async function doRebuild() {
    setRebuilding(true);
    try {
      const { data, error, response } = await api.POST("/api/newsletter/suggestion/rebuild", {
        body: selected ? { period_start: selected.start, period_end: selected.end } : undefined,
      });
      if (!response.ok || !data) throw httpError(error, response.status);
      receiveSuggestion(data);
      const meta = data.summary_meta as { error?: string | null };
      if (meta.error) toast.warning(`Suggestion rebuilt for ${data.label}, but the summary model was unavailable (${meta.error}).`);
      else toast.success(`Suggestion rebuilt for ${data.label}`);
    } catch (e) {
      toast.error(`Rebuild failed: ${errorMessage(e)}`);
    } finally {
      setRebuilding(false);
    }
  }

  /** Rebuild menimpa SELURUH saran tersimpan dan memanggil model lagi; kalau analis sudah
   * menyunting ringkasan, tanyakan dulu. */
  function requestRebuild() {
    if (introEdited) setConfirm({ kind: "rebuild" });
    else void doRebuild();
  }

  function applySuggestionAll() {
    if (!suggestion) return;
    const result = applyArticles(suggestion, "replace");
    const intro = summaryToIntro(suggestion.summary_text);
    // Saran tanpa ringkasan (model mati) tidak boleh mengosongkan intro yang sudah ditulis analis.
    if (intro) {
      setTemplate((t) => ({ ...t, customIntro: intro }));
      setIntroPrefill(intro);
    }
    toast.success(describeMerge(result, "replace"));
  }

  function mergeSuggestionIn() {
    if (!suggestion) return;
    toast.success(describeMerge(applyArticles(suggestion, "merge"), "merge"));
  }

  function applySuggestedSummary() {
    if (!suggestion) return;
    const intro = summaryToIntro(suggestion.summary_text);
    if (!intro) return;
    setTemplate((t) => ({ ...t, customIntro: intro }));
    setIntroPrefill(intro);
  }

  // ── Aksi per artikel ──────────────────────────────────────────────────────

  const suggestedById = new Map((suggestion?.items ?? []).map((i) => [i.article_id, i]));
  const queuedIds = new Set(queue.map((a) => a._id));
  const placed = placedIds(state);

  const suggestedPool: PoolEntry[] = suggestion
    ? unplacedSuggestion(state, suggestion.items)
        .filter((i) => !queuedIds.has(i.article_id))
        .map((i) => ({ article: i.article, origin: "suggestion" as const, reasons: i.reasons, section: i.section }))
    : [];
  const queuePool: PoolEntry[] = queue.filter((a) => !placed.has(a._id)).map((a) => ({ article: a as Article, origin: "queue" as const }));
  const pool = [...suggestedPool, ...queuePool];

  function findPlaced(articleId: number): Article | undefined {
    const at = locate(state, articleId);
    return at ? state.slots[at].find((a) => a.id === articleId) : undefined;
  }

  /** Dari kolam ("+" di panel kiri): batas yang menolak dijelaskan dengan toast, bukan menggeser
   * artikel lain diam-diam seperti composer lama. */
  function assign(slot: SlotKey, entry: PoolEntry) {
    const change = place(state, entry.article, slot);
    if (!change.ok) {
      toast.info(change.message);
      return;
    }
    const reasons = entry.reasons ? { ...change.state.reasons, [entry.article.id]: entry.reasons } : change.state.reasons;
    setState({ ...change.state, reasons });
    if (entry.origin === "queue") popFromQueue(entry.article.id);
    toast.success(`Added to ${SLOT_BY_KEY[slot].label}`);
  }

  function moveArticle(articleId: number, to: SlotKey) {
    const change = move(state, articleId, to);
    if (!change.ok) toast.info(change.message);
    else setState(change.state);
  }

  /** Buang dari edisi: artikel saran kembali ke "Suggested, not placed"; artikel dari Newsroom
   * kembali ke antrean (perilaku composer lama). */
  function removeArticle(articleId: number) {
    const article = findPlaced(articleId);
    setState(remove(state, articleId));
    if (article && !suggestedById.has(articleId)) pushToQueue(article);
  }

  function swapArticle(outId: number, entry: PoolEntry) {
    const out = findPlaced(outId);
    const change = swap(state, outId, entry.article);
    if (!change.ok) {
      toast.info(change.message);
      return;
    }
    const reasons = entry.reasons ? { ...change.state.reasons, [entry.article.id]: entry.reasons } : change.state.reasons;
    setState({ ...change.state, reasons });
    if (entry.origin === "queue") popFromQueue(entry.article.id);
    if (out && !suggestedById.has(outId)) pushToQueue(out);
  }

  function updateNote(articleId: number, value: string) {
    setState((prev) => {
      const notes = { ...prev.notes };
      const key = String(articleId);
      if (value.trim()) notes[key] = value;
      else delete notes[key];
      return { ...prev, notes };
    });
  }

  function toggleRegenerate(articleId: number) {
    setRegenerate((prev) => {
      const next = new Set(prev);
      if (!next.delete(articleId)) next.add(articleId);
      return next;
    });
  }

  // ── Preview, draft, riwayat ───────────────────────────────────────────────

  function errorPage(message: string): string {
    return `<body style="font-family:sans-serif;padding:20px;color:#d32f2f">Error: ${escapeHtml(message)}</body>`;
  }

  async function handlePreview() {
    const built = buildRequestBody(state, template, {
      language,
      period: selected ? { start: selected.start, end: selected.end } : null,
      regenerate,
    });
    if (!built.ok) {
      toast.error(built.message);
      return;
    }
    const body = built.body;
    setPreview({ ...PREVIEW_DIALOG_CLOSED, open: true });
    try {
      const { data, error, response } = await api.POST("/api/newsletter/preview", { body });
      if (!response.ok) throw httpError(error, response.status);
      const result = data as unknown as NewsletterPreviewResult;

      const warnings: string[] = [];
      if (result.size_warning) warnings.push(result.size_warning);
      const markers = countCveMarkers(body.custom_intro ?? "");
      if (markers > 0) {
        warnings.push(
          `The Executive Summary still contains ${markers} “${CVE_MARKER}” marker${markers === 1 ? "" : "s"}. Replace or delete ${markers === 1 ? "it" : "them"} before sending.`,
        );
      }
      const sources = result.body_sources ?? {};
      const metadataTitles = Object.entries(sources)
        .filter(([, source]) => source === "metadata")
        .map(([id]) => findPlaced(Number(id))?.title ?? `Article ${id}`);

      setBodySources(sources);
      setRegenerate(new Set()); // sekali bangun ulang sudah terjadi di server, hasilnya di cache
      setPreview({
        open: true,
        label: result.period_label ?? `Week ${result.week}, ${result.year}`,
        html: result.html,
        mode: "compose",
        body,
        warnings,
        metadataTitles,
      });
    } catch (e) {
      setPreview({ ...PREVIEW_DIALOG_CLOSED, open: true, html: errorPage(errorMessage(e)) });
      toast.error(`Preview failed: ${errorMessage(e)}`);
    }
  }

  async function handleSendDraft() {
    const body = preview.body;
    if (!body) return;
    setSending(true);
    try {
      const { data, error, response } = await api.POST("/api/newsletter/draft-email", { body });
      if (!response.ok) throw httpError(error, response.status);
      const result = data as unknown as NewsletterDraftResult;
      toast.success(`Draft created — ${result.method} · ${result.period_label ?? `Week ${result.week}, ${result.year}`}`);
      setPreview(PREVIEW_DIALOG_CLOSED);
      setHistoryRefreshKey((k) => k + 1);
    } catch (e) {
      // 500 sesudah draft jadi tapi riwayat gagal disimpan memuat id Graph-nya: tahan lebih lama.
      toast.error(`Draft failed: ${errorMessage(e)}`, { duration: 15000 });
    } finally {
      setSending(false);
    }
  }

  async function handlePreviewSaved(id: number, label: string) {
    setPreview({ ...PREVIEW_DIALOG_CLOSED, open: true, label, mode: "saved", savedId: id });
    try {
      const clientId = getActiveClientId();
      const resp = await fetch(`/api/proxy/api/newsletter/${id}/html`, clientId ? { headers: { "X-Client-ID": clientId } } : undefined);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const html = await resp.text();
      setPreview((p) => (p.savedId === id ? { ...p, html } : p));
    } catch (e) {
      setPreview((p) => (p.savedId === id ? { ...p, html: errorPage(errorMessage(e)) } : p));
      toast.error("Failed to load saved newsletter");
    }
  }

  async function handleResend(id: number, label: string) {
    setResendingId(id);
    try {
      const { data, error, response } = await api.POST("/api/newsletter/{newsletter_id}/resend", { params: { path: { newsletter_id: id } } });
      if (!response.ok) throw httpError(error, response.status);
      const result = data as unknown as NewsletterResendResult;
      toast.success(`Draft resent — ${result.method} · ${label}`);
      setPreview((p) => (p.savedId === id ? PREVIEW_DIALOG_CLOSED : p));
    } catch (e) {
      toast.error(`Resend failed: ${errorMessage(e)}`);
    } finally {
      setResendingId(null);
    }
  }

  const cardCount = (["highlights", "apac_full", "global_news_full", "indonesia_full"] as const).reduce((n, k) => n + state.slots[k].length, 0);
  const suggestedIntro = suggestion ? summaryToIntro(suggestion.summary_text) : "";
  usePageTitle("Newsletter composer");
  // Blok bawaan: section pertama yang berisi (Indonesia, APAC, Global), selain itu Highlights;
  // berlaku sampai analis memilih sendiri.
  const defaultBlock: BlockId = SECTION_BLOCKS.slice(1).find((b) => state.slots[b.full].length + (b.compact ? state.slots[b.compact].length : 0) > 0)?.id ?? "highlights";
  const activeBlock = block ?? defaultBlock;

  return (
    <div>
      <PageHeader
        kicker="NEWSLETTER"
        title="Newsletter composer"
        description="Monthly client newsletter: pick the articles, the AI writes the summaries, you approve"
        actions={
          can("manage_newsletter") ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={handlePreview}>
                Preview
              </Button>
              <Button onClick={handlePreview}>Generate edition</Button>
            </div>
          ) : undefined
        }
      />

      <NewsletterSuggestionBar
        phase={phase}
        applied={suggestion !== null && appliedKey === suggestionKey(suggestion)}
        busy={rebuilding}
        onBuild={() => void doRebuild()}
        onRetry={() => void retrySuggestion()}
        onUse={applySuggestionAll}
        onMerge={mergeSuggestionIn}
        onRebuild={requestRebuild}
      />

      <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,640px)_minmax(0,356px)] xl:justify-between">
        <NewsletterTemplateColumn
          months={months}
          period={period}
          onPeriodChange={setPeriod}
          language={language}
          onLanguageChange={setLanguage}
          cardCount={cardCount}
          state={state}
          template={template}
          block={activeBlock}
          onBlockChange={setBlock}
        />

        <NewsletterContentColumn
          block={activeBlock}
          template={template}
          onTemplateChange={setTemplate}
          summary={{
            value: template.customIntro,
            onChange: (customIntro) => setTemplate((t) => ({ ...t, customIntro })),
            suggestion,
            suggestedIntro,
            rebuilding,
            onUseSuggested: () => (introEdited ? setConfirm({ kind: "use-summary" }) : applySuggestedSummary()),
            onRebuild: requestRebuild,
          }}
          sections={{
            state,
            pool,
            bodySources,
            paywallHints: hintsQuery.data ?? {},
            regenerate,
            onMove: moveArticle,
            onRemove: removeArticle,
            onSwap: swapArticle,
            onNoteChange: updateNote,
            onToggleRegenerate: toggleRegenerate,
          }}
        />

        <NewsletterQueuePanel
          state={state}
          queue={queue}
          suggested={suggestedPool}
          paywallHints={hintsQuery.data ?? {}}
          onAssign={assign}
          onRemove={popFromQueue}
          onClearAll={handleClearQueue}
        />
      </div>

      <div className="mt-6">
        <NewsletterHistoryPanel refreshKey={historyRefreshKey} onPreview={handlePreviewSaved} onResend={handleResend} resendingId={resendingId} />
      </div>

      <NewsletterPreviewDialog
        state={preview}
        onOpenChange={(open) => setPreview((p) => ({ ...p, open }))}
        onSendDraft={handleSendDraft}
        sending={sending}
        onResendSaved={handleResend}
        resending={resendingId != null}
      />

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm?.kind === "rebuild" ? "Rebuild the suggestion?" : "Replace your Executive Summary?"}
        description={
          confirm?.kind === "rebuild"
            ? `This overwrites the stored suggestion${suggestion ? ` for ${suggestion.label}` : ""} (articles and summary) for everyone and calls the model again.`
            : "The field will be replaced with the suggested paragraph."
        }
        warning={
          confirm?.kind === "rebuild"
            ? "You edited the Executive Summary. It stays as it is; use “Use suggested summary” afterwards if you want the new text instead."
            : "Your edits to the Executive Summary will be lost."
        }
        confirmLabel={confirm?.kind === "rebuild" ? "Rebuild" : "Replace"}
        onConfirm={() => (confirm?.kind === "rebuild" ? void doRebuild() : applySuggestedSummary())}
      />
    </div>
  );
}
