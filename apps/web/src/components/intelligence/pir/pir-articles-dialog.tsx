"use client";

import { CheckIcon, StickyNoteIcon } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/components/providers/auth-provider";
import { SimplePager } from "@/components/pager";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type PIROut = components["schemas"]["PIROut"];
type PIRArticleOut = components["schemas"]["PIRArticleOut"];

const PAGE_SIZE = 15;

interface PirArticlesDialogProps {
  pir: PIROut | null;
  onClose: () => void;
}

/** Port overlay artikel yang match PIR + note analis (`pir.js:6-105`,
 * `viewPirArticles`/`_fetchPirArticles`/`openPirNote`/`savePirNote`). */
export function PirArticlesDialog({ pir, onClose }: PirArticlesDialogProps) {
  const can = useCan();
  const [page, setPage] = useState(1);
  const [noteArticle, setNoteArticle] = useState<PIRArticleOut | null>(null);

  const query = useQuery({
    queryKey: ["intelligence", "pir-articles", pir?.id, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir/{pir_id}/articles", {
        params: { path: { pir_id: pir!.id }, query: { page, page_size: PAGE_SIZE } },
      });
      if (error) throw error;
      return data;
    },
    enabled: pir !== null,
  });

  const total = query.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <Dialog
        open={pir !== null}
        onOpenChange={(open) => {
          if (!open) {
            onClose();
            setPage(1);
          }
        }}
      >
        <DialogContent className="max-h-[85vh] w-full max-w-2xl overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{pir?.title}</DialogTitle>
            <p className="font-mono text-xs text-muted-foreground">
              {total.toLocaleString()} matching articles — page {page} of {totalPages}
            </p>
          </DialogHeader>

          {query.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
          {query.isError && <p className="py-6 text-center text-xs text-destructive">Error loading articles.</p>}
          {query.data && query.data.articles.length === 0 && (
            <p className="py-6 text-center text-xs text-muted-foreground">No articles found.</p>
          )}

          <div className="space-y-2">
            {query.data?.articles.map((a) => (
              <div key={a.id} className="rounded-xl border border-border bg-background p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className="flex-1 text-sm font-semibold text-foreground hover:underline">
                    {a.title}
                  </a>
                  <div className="flex shrink-0 items-center gap-1">
                    {a.has_note && (
                      <Badge variant="outline" className="text-success text-xs">
                        <CheckIcon aria-hidden /> NOTED
                      </Badge>
                    )}
                    {can("manage_pir") && (
                      <Button size="sm" variant="outline" className="h-6 px-1.5 text-xs" onClick={() => setNoteArticle(a)}>
                        <StickyNoteIcon aria-hidden /> Note
                      </Button>
                    )}
                  </div>
                </div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">
                  {[a.source, a.posted_on, a.news_type].filter(Boolean).join(" · ")}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-2 flex justify-center">
            <SimplePager page={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        </DialogContent>
      </Dialog>

      <PirNoteDialog
        key={noteArticle?.id ?? "none"}
        pirId={pir?.id ?? null}
        article={noteArticle}
        onClose={() => setNoteArticle(null)}
        onSaved={() => void query.refetch()}
      />
    </>
  );
}

interface PirNoteDialogProps {
  pirId: number | null;
  article: PIRArticleOut | null;
  onClose: () => void;
  onSaved: () => void;
}

function PirNoteDialog({ pirId, article, onClose, onSaved }: PirNoteDialogProps) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);

  const noteQuery = useQuery({
    queryKey: ["intelligence", "pir-note", pirId, article?.url],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir/{pir_id}/note", {
        params: { path: { pir_id: pirId! }, query: { url: article!.url } },
      });
      if (error) throw error;
      return data;
    },
    enabled: pirId !== null && article !== null,
  });

  async function save(note: string, analyst: string) {
    if (!pirId || !article) return;
    setSaving(true);
    try {
      const { error } = await api.PUT("/api/pir/{pir_id}/note", {
        params: { path: { pir_id: pirId } },
        body: { url: article.url, note, analyst: analyst.trim() },
      });
      if (error) throw new Error(JSON.stringify(error));
      toast.success("Note saved.");
      void queryClient.invalidateQueries({ queryKey: ["intelligence", "pir-note"] });
      onSaved();
      onClose();
    } catch (e) {
      toast.error(`Error saving note: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={article !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">{article?.title}</DialogTitle>
        </DialogHeader>
        {noteQuery.isPending ? (
          <p className="py-4 text-center text-xs text-muted-foreground">Loading…</p>
        ) : (
          <NoteForm
            initialNote={noteQuery.data?.note ?? ""}
            initialAnalyst={noteQuery.data?.analyst || user?.username || ""}
            updatedAt={noteQuery.data?.updated_at}
            saving={saving}
            onSave={save}
            onCancel={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Mount cuma sekali data note-nya udah resolve (parent nge-gate lewat
 * `noteQuery.isPending`), jadi `useState(initialNote)` aman dipakai
 * langsung sebagai nilai awal -- gak butuh sinkronisasi effect. */
function NoteForm({
  initialNote,
  initialAnalyst,
  updatedAt,
  saving,
  onSave,
  onCancel,
}: {
  initialNote: string;
  initialAnalyst: string;
  updatedAt?: string;
  saving: boolean;
  onSave: (note: string, analyst: string) => void;
  onCancel: () => void;
}) {
  const [note, setNote] = useState(initialNote);
  const [analyst, setAnalyst] = useState(initialAnalyst);
  return (
    <div className="space-y-3">
      {updatedAt && <p className="font-mono text-xs text-muted-foreground">Last saved: {updatedAt.slice(0, 16).replace("T", " ")}</p>}
      <div className="flex flex-col gap-1">
        <Label className="text-sm font-medium text-muted-foreground">Analyst</Label>
        <Input value={analyst} onChange={(e) => setAnalyst(e.target.value)} className="text-xs" />
      </div>
      <div className="flex flex-col gap-1">
        <Label className="text-sm font-medium text-muted-foreground">Note</Label>
        <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} className="text-xs" />
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button disabled={saving} onClick={() => onSave(note, analyst)}>
          {saving ? "Saving…" : "Save Note"}
        </Button>
      </div>
    </div>
  );
}
