"use client";

import { RefreshCwIcon, SaveIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { DEFAULT_FG, loadMindmapColors, saveMindmapColors } from "@/lib/mindmap/colors";
import { renderMindmap } from "@/lib/mindmap/render";
import type { MindmapDocResponse } from "@/lib/api/loose-types";

interface MindmapEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  featureType: string;
  docId: string;
  title?: string;
}

/** Port `mmOpenEditor()` (`mindmap.js:199-379`) -- editor full-layar:
 * textarea syntax Mermaid di kiri, preview live di kanan, color picker
 * node/font, Save (`PUT`, persist ke DB) + Regenerate (`POST .../
 * regenerate`, timpa `custom_syntax` balik ke hasil builder). Body cuma
 * mount pas `open` (bukan `useEffect` buat reset state pas dialog
 * dibuka ulang) -- mount baru = state fresh otomatis, sama pola kayak
 * `NoteForm` PIR Grup G2 (hindari `react-hooks/set-state-in-effect`). */
export function MindmapEditorDialog({ open, onOpenChange, featureType, docId, title }: MindmapEditorDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[90vh] w-full max-w-[95vw] flex-col gap-3 sm:max-w-[95vw]">
        <DialogHeader className="sr-only">
          <DialogTitle>Mind Map Editor</DialogTitle>
        </DialogHeader>
        {open && (
          <MindmapEditorBody key={`${featureType}:${docId}`} featureType={featureType} docId={docId} title={title} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function MindmapEditorBody({ featureType, docId, title }: { featureType: string; docId: string; title?: string }) {
  const query = useQuery({
    queryKey: ["mindmap", "doc", featureType, docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mindmap/{feature_type}/{doc_id}", {
        params: { path: { feature_type: featureType, doc_id: docId } },
      });
      if (error) throw error;
      return data as unknown as MindmapDocResponse;
    },
  });

  return (
    <>
      {query.isPending && <p className="py-8 text-center text-xs text-muted-foreground">Loading…</p>}
      {query.isError && <p className="py-8 text-center text-xs text-destructive">Failed to load mind map.</p>}
      {query.data && <MindmapEditorForm featureType={featureType} docId={docId} title={title} doc={query.data} />}
    </>
  );
}

function MindmapEditorForm({
  featureType,
  docId,
  title,
  doc,
}: {
  featureType: string;
  docId: string;
  title?: string;
  doc: MindmapDocResponse;
}) {
  const queryClient = useQueryClient();
  const previewRef = useRef<HTMLDivElement>(null);
  const [syntax, setSyntax] = useState(doc.display_syntax || doc.mermaid_syntax || "");
  const [nodeBg, setNodeBg] = useState<string | null>(() => loadMindmapColors(featureType, docId).nodeBg);
  const [nodeFg, setNodeFg] = useState(() => loadMindmapColors(featureType, docId).nodeFg || DEFAULT_FG);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => {
      if (previewRef.current) void renderMindmap(previewRef.current, syntax, nodeBg, nodeFg);
    }, 400);
    return () => clearTimeout(t);
  }, [syntax, nodeBg, nodeFg]);

  async function save() {
    setSaving(true);
    setStatus("Saving…");
    try {
      saveMindmapColors(featureType, docId, nodeBg, nodeFg);
      const { error } = await api.PUT("/api/mindmap/{feature_type}/{doc_id}", {
        params: { path: { feature_type: featureType, doc_id: docId } },
        body: { syntax },
      });
      if (error) throw new Error(JSON.stringify(error));
      setStatus("Saved");
      await queryClient.invalidateQueries({ queryKey: ["mindmap", "doc", featureType, docId] });
    } catch (e) {
      setStatus(`Save error: ${(e as Error).message}`);
      toast.error("Failed to save mind map.");
    } finally {
      setSaving(false);
    }
  }

  async function regenerate() {
    setRegenerating(true);
    setStatus("Regenerating…");
    try {
      const { data, error } = await api.POST("/api/mindmap/{feature_type}/{doc_id}/regenerate", {
        params: { path: { feature_type: featureType, doc_id: docId } },
      });
      if (error) throw new Error(JSON.stringify(error));
      const d = data as unknown as MindmapDocResponse;
      setSyntax(d.display_syntax || "");
      setStatus("Regenerated");
      await queryClient.invalidateQueries({ queryKey: ["mindmap", "doc", featureType, docId] });
    } catch (e) {
      setStatus(`Regen error: ${(e as Error).message}`);
      toast.error("Failed to regenerate mind map.");
    } finally {
      setRegenerating(false);
    }
  }

  const isAuto = nodeBg === null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-2.5 pr-8">
        <span className="font-mono text-xs text-foreground">{title || `${featureType}/${docId}`}</span>
        <span className="rounded-full border border-border bg-background px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
          Mind Map Editor
        </span>

        <div className="ml-2 flex items-center gap-1.5" title="Node background color">
          <span className="font-mono text-xs text-muted-foreground">Node</span>
          <input
            type="color"
            value={nodeBg || "#d0002f"}
            onChange={(e) => setNodeBg(e.target.value)}
            className={cn("h-[22px] w-[26px] cursor-pointer rounded-full border border-border bg-transparent p-0.5", isAuto && "opacity-35")}
          />
          <button
            type="button"
            onClick={() => setNodeBg(isAuto ? "#d0002f" : null)}
            title="Use level-based colors instead"
            className={cn(
              "rounded-full border px-1.5 py-0.5 font-mono text-xs",
              isAuto ? "border-primary/40 bg-primary/12 text-primary-text" : "border-border text-muted-foreground",
            )}
          >
            Auto
          </button>
        </div>

        <div className="flex items-center gap-1.5" title="Font color">
          <span className="font-mono text-xs text-muted-foreground">Font</span>
          <input
            type="color"
            value={nodeFg}
            onChange={(e) => setNodeFg(e.target.value)}
            className="h-[22px] w-[26px] cursor-pointer rounded-full border border-border bg-transparent p-0.5"
          />
        </div>

        <div className="ml-auto flex gap-1.5">
          <Button size="sm" variant="outline" className="h-7 px-2.5 text-xs" disabled={regenerating} onClick={() => void regenerate()}>
            <RefreshCwIcon aria-hidden /> Regenerate
          </Button>
          <Button size="sm" className="h-7 px-2.5 text-xs" disabled={saving} onClick={() => void save()}>
            <SaveIcon aria-hidden /> Save
          </Button>
        </div>
      </div>
      {status && <div className="flex-shrink-0 font-mono text-xs text-muted-foreground">{status}</div>}

      <div className="flex min-h-0 flex-1 gap-3">
        <div className="flex w-[340px] flex-shrink-0 flex-col gap-1">
          <div className="text-sm font-semibold text-muted-foreground">Mermaid Syntax</div>
          <textarea
            value={syntax}
            onChange={(e) => setSyntax(e.target.value)}
            spellCheck={false}
            className="flex-1 resize-none rounded-2xl border border-border bg-surface shadow-sm p-2.5 font-mono text-[13px] leading-relaxed text-foreground outline-none"
          />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="text-sm font-semibold text-muted-foreground">Preview</div>
          <div ref={previewRef} className="flex flex-1 items-start justify-center overflow-auto rounded-2xl border border-border bg-surface  p-4" />
        </div>
      </div>
    </div>
  );
}
