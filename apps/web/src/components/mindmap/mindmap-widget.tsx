"use client";

import { PencilIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { loadMindmapColors } from "@/lib/mindmap/colors";
import { useThemeKey } from "@/lib/chart-theme";
import { renderMindmap } from "@/lib/mindmap/render";
import { MindmapEditorDialog } from "@/components/mindmap/mindmap-editor-dialog";
import type { MindmapDocResponse } from "@/lib/api/loose-types";

interface MindmapWidgetProps {
  featureType: string;
  docId: string;
  title?: string;
}

/** Port `mmInlineWidget()`/`mmToggleInline()` (`mindmap.js:134-192`) --
 * toggle inline (lazy-load pas expand pertama, tetep ke-render abis
 * collapse/expand ulang) + tombol buka editor full-layar. Dipakai
 * Cluster (`clusters.js`, Grup G7) dan Threat Actor (`ta.js`, Grup G6)
 * di legacy -- komponen dibangun di sini (Grup G5) buat dipasang pas
 * G6/G7 digarap. */
export function MindmapWidget({ featureType, docId, title }: MindmapWidgetProps) {
  const [expanded, setExpanded] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const diagramRef = useRef<HTMLDivElement>(null);

  const query = useQuery({
    queryKey: ["mindmap", "doc", featureType, docId],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/mindmap/{feature_type}/{doc_id}", {
        params: { path: { feature_type: featureType, doc_id: docId } },
      });
      if (error) throw error;
      return data as unknown as MindmapDocResponse;
    },
    enabled: expanded,
  });

  const themeKey = useThemeKey();

  useEffect(() => {
    if (!expanded || !query.data || !diagramRef.current) return;
    const colors = loadMindmapColors(featureType, docId);
    void renderMindmap(diagramRef.current, query.data.display_syntax || "", colors.nodeBg, colors.nodeFg);
  }, [expanded, query.data, featureType, docId, themeKey]);

  return (
    <div className="mb-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-sm font-semibold text-muted-foreground">Mind Map</span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="rounded-full border border-primary/30 bg-primary/8 px-2 py-0.5 font-mono text-xs text-primary"
        >
          {expanded ? "⬡ Hide Map" : "⬡ Mind Map"}
        </button>
        <button
          type="button"
          onClick={() => setEditorOpen(true)}
          className="rounded-full border border-border px-2 py-0.5 font-mono text-xs text-muted-foreground"
        >
          <PencilIcon aria-hidden /> Edit Mindmap
        </button>
      </div>

      {expanded && (
        <div className="max-h-[400px] overflow-auto rounded-2xl surface-raised  p-3">
          {query.isPending && <div className="font-mono text-xs text-muted-foreground">Loading…</div>}
          {query.isError && <div className="font-mono text-xs text-destructive">Failed to load mind map.</div>}
          <div ref={diagramRef} />
        </div>
      )}

      <MindmapEditorDialog open={editorOpen} onOpenChange={setEditorOpen} featureType={featureType} docId={docId} title={title} />
    </div>
  );
}
