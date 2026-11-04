"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { formatWib } from "@/lib/cve/freshness";

type AnchorType = "story" | "entity";

/**
 * Draf hipotesis hunting dari LLM (P7e 7.2). GET 404 = belum pernah dibuat (bukan error). Tombol
 * Draft/Regenerate hanya untuk `manage_intel`; API tetap menegakkan izinnya, 502 = LLM gagal dan
 * draf lama tetap tersimpan.
 */
export function HuntHypothesis({ anchorType, anchorId }: { anchorType: AnchorType; anchorId: number }) {
  const canGenerate = useCan()("manage_intel");
  const queryClient = useQueryClient();
  const key = ["hunt-hypothesis", anchorType, anchorId];
  const path = { params: { path: { anchor_type: anchorType, anchor_id: anchorId } } };

  const query = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/hunt-packs/{anchor_type}/{anchor_id}/hypothesis", path);
      if (response.status === 404) return null;
      if (!data) throw new Error(`HTTP ${response.status}`);
      return data;
    },
  });

  const generate = useMutation({
    mutationFn: async () => {
      const { data, response } = await api.POST("/api/hunt-packs/{anchor_type}/{anchor_id}/hypothesis", path);
      if (!data) throw new Error(response.status === 502 ? "the LLM call failed" : `HTTP ${response.status}`);
      return data;
    },
    onSuccess: (data) => queryClient.setQueryData(key, data),
    onError: (e) => toast.error(`Could not draft a hypothesis: ${(e as Error).message}`),
  });

  const draft = query.data;
  return (
    <section className="space-y-2" aria-labelledby={`hunt-hyp-${anchorType}-${anchorId}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`hunt-hyp-${anchorType}-${anchorId}`} className="text-sm font-semibold">
          Hunt hypothesis
        </h3>
        {canGenerate && !query.isPending && (
          <Button
            variant="outline"
            size="sm"
            className="max-sm:h-11"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? "Drafting…" : draft ? "Regenerate" : "Draft hypothesis"}
          </Button>
        )}
      </div>
      {query.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : query.isError ? (
        <p role="alert" className="text-xs text-destructive">
          Could not load the hypothesis.
        </p>
      ) : draft ? (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <Badge variant="secondary">LLM draft</Badge>
            <span className="font-code">{draft.model}</span>
            <span>
              {formatWib(draft.generated_at)} by {draft.generated_by}
            </span>
          </div>
          <p className="text-sm break-words whitespace-pre-wrap text-foreground">{draft.text}</p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No hypothesis drafted yet.</p>
      )}
    </section>
  );
}
