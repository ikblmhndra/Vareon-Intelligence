"use client";

import { useState } from "react";
import { ArrowRight, Plus, Undo2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EntityChip, refLabel } from "@/components/entities/entity-chip";
import {
  RelationshipCreateDialog,
  type RelationshipEnd,
} from "@/components/entities/relationship-create-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useCan } from "@/lib/auth/permissions";

type EntityDetail = components["schemas"]["EntityDetail"];
type RelationshipOut = components["schemas"]["RelationshipOut"];
type CoMention = components["schemas"]["CoMention"];

const PROVENANCE_LABEL: Record<string, string> = {
  attack: "ATT&CK",
  analyst: "Analyst",
  ransomware: "Ransomware",
};

/** Query relasi + co-mention, dipakai tab Relationships, ringkasan Overview, dan badge tab. */
export function useEntityRelationships(entityId: number, enabled = true) {
  return useQuery({
    queryKey: ["entity-relationships", entityId],
    enabled,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/relationships", {
        params: { path: { entity_id: entityId } },
      });
      if (error || !data) throw new Error("relationships failed");
      return data;
    },
  });
}

/** Ujung relasi yang BUKAN entity halaman ini; sumber indikator tidak punya entity (nilai kode). */
function OtherEnd({ rel, entityId }: { rel: RelationshipOut; entityId: number }) {
  const incoming = rel.source?.id !== entityId && rel.target.id === entityId;
  if (incoming) {
    if (rel.source) {
      return <EntityChip type={rel.source.type} name={rel.source.name} id={rel.source.id} label={refLabel(rel.source)} />;
    }
    return (
      <span className="font-code text-xs break-all" title="Indicator">
        {rel.source_indicator_id != null ? `indicator #${rel.source_indicator_id}` : "indicator"}
      </span>
    );
  }
  return <EntityChip type={rel.target.type} name={rel.target.name} id={rel.target.id} label={refLabel(rel.target)} />;
}

function Verb({ rel, entityId }: { rel: RelationshipOut; entityId: number }) {
  const incoming = rel.source?.id !== entityId && rel.target.id === entityId;
  return (
    <span className="text-xs font-medium">
      {incoming && (
        <>
          <span aria-hidden>← </span>
          <span className="sr-only">incoming </span>
        </>
      )}
      {rel.relationship_type}
    </span>
  );
}

function ProvenanceBadge({ provenance }: { provenance: string }) {
  return (
    <Badge variant={provenance === "analyst" ? "secondary" : "outline"}>
      {PROVENANCE_LABEL[provenance] ?? provenance}
    </Badge>
  );
}

function useCreateTarget() {
  const [target, setTarget] = useState<RelationshipEnd | null>(null);
  const [open, setOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  return {
    open,
    target,
    nonce,
    start(t: RelationshipEnd | null) {
      setTarget(t);
      setNonce((n) => n + 1);
      setOpen(true);
    },
    close: () => setOpen(false),
  };
}

function CoMentionRows({
  items,
  onRelate,
  canRelate,
}: {
  items: CoMention[];
  onRelate: (e: CoMention["entity"]) => void;
  canRelate: boolean;
}) {
  const max = Math.max(1, ...items.map((c) => c.stories));
  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li
          key={c.entity.id}
          className="grid grid-cols-[minmax(0,1fr)_7rem_auto] items-center gap-3 max-sm:grid-cols-[minmax(0,1fr)_auto]"
        >
          <EntityChip type={c.entity.type} name={c.entity.name} id={c.entity.id} label={refLabel(c.entity)} />
          <div className="max-sm:order-last max-sm:col-span-2">
            <div
              role="meter"
              aria-label={`${c.stories} stories together`}
              aria-valuemin={0}
              aria-valuemax={max}
              aria-valuenow={c.stories}
              className="h-1.5 overflow-hidden rounded-full bg-muted"
            >
              <div className="h-full rounded-full bg-primary" style={{ width: `${(c.stories / max) * 100}%` }} />
            </div>
            <span className="text-2xs text-muted-foreground">
              {c.stories} {c.stories === 1 ? "story" : "stories"}
            </span>
          </div>
          {canRelate && (
            <Button
              variant="outline"
              size="sm"
              className="max-sm:h-11"
              aria-label={`Make relationship with ${c.entity.name}`}
              onClick={() => onRelate(c.entity)}
            >
              <Plus aria-hidden />
              Relate
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Ringkasan untuk kolom kanan Overview: 3 relasi pertama + "Often mentioned together". */
export function EntityRelationshipsSummary({
  entity,
  onViewAll,
}: {
  entity: EntityDetail;
  onViewAll: () => void;
}) {
  const can = useCan();
  const rels = useEntityRelationships(entity.id);
  const create = useCreateTarget();
  const source: RelationshipEnd = { id: entity.id, type: entity.type, name: entity.name };
  const total = rels.data?.relationships.length ?? 0;
  const coMentions = (rels.data?.co_mentions ?? []).slice(0, 5);

  return (
    <div className="space-y-4">
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-rel-preview">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="entity-rel-preview" className="text-base font-semibold">
            Relationships
          </h2>
          {total > 0 && (
            <Button variant="ghost" size="sm" className="max-sm:h-11" onClick={onViewAll}>
              View all {total}
              <ArrowRight aria-hidden />
            </Button>
          )}
        </div>
        {rels.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : rels.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Could not load relationships.
          </p>
        ) : total === 0 ? (
          <p className="text-sm text-muted-foreground">No relationships yet.</p>
        ) : (
          <ul className="space-y-2">
            {rels.data.relationships.slice(0, 3).map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2">
                <Verb rel={r} entityId={entity.id} />
                <OtherEnd rel={r} entityId={entity.id} />
                <ProvenanceBadge provenance={r.provenance} />
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-co-mentions">
        <h2 id="entity-co-mentions" className="text-base font-semibold">
          Often mentioned together{" "}
          <span className="text-xs font-normal text-muted-foreground">365 days</span>
        </h2>
        {rels.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : coMentions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No co-mentions in the last year.</p>
        ) : (
          <CoMentionRows
            items={coMentions}
            canRelate={can("manage_entities")}
            onRelate={(e) => create.start(e)}
          />
        )}
      </section>
      <RelationshipCreateDialog
        key={create.nonce}
        open={create.open}
        onClose={create.close}
        source={source}
        target={create.target}
      />
    </div>
  );
}

export function EntityRelationshipsTab({ entity }: { entity: EntityDetail }) {
  const can = useCan();
  const qc = useQueryClient();
  const rels = useEntityRelationships(entity.id);
  const create = useCreateTarget();
  const [revoking, setRevoking] = useState<RelationshipOut | null>(null);
  const canManage = can("manage_entities");
  const source: RelationshipEnd = { id: entity.id, type: entity.type, name: entity.name };

  const revoke = useMutation({
    mutationFn: async (id: number) => {
      const { error } = await api.DELETE("/api/relationships/{relationship_id}", {
        params: { path: { relationship_id: id } },
      });
      if (error) throw new Error("revoke failed");
    },
    onSuccess: () => {
      toast.success("Relationship revoked.");
      void qc.invalidateQueries({ queryKey: ["entity-relationships", entity.id] });
    },
    onError: () => toast.error("Could not revoke the relationship."),
  });

  const items = rels.data?.relationships ?? [];
  const coMentions = rels.data?.co_mentions ?? [];

  return (
    <div className="space-y-4">
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-rel-all">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="entity-rel-all" className="text-base font-semibold">
            Relationships
          </h2>
          {canManage && (
            <Button size="sm" className="max-sm:h-11" onClick={() => create.start(null)}>
              <Plus aria-hidden />
              Make relationship
            </Button>
          )}
        </div>
        {rels.isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : rels.isError ? (
          <p role="alert" className="text-sm text-destructive">
            Could not load relationships.
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No relationships yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Relationship</TableHead>
                <TableHead>Other end</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Confidence</TableHead>
                <TableHead>Created by</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Verb rel={r} entityId={entity.id} />
                  </TableCell>
                  <TableCell>
                    <OtherEnd rel={r} entityId={entity.id} />
                  </TableCell>
                  <TableCell>
                    <ProvenanceBadge provenance={r.provenance} />
                  </TableCell>
                  <TableCell className="text-right font-code text-xs">{r.confidence ?? "-"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{r.created_by ?? "-"}</TableCell>
                  <TableCell className="text-right">
                    {r.provenance === "analyst" && canManage && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="max-sm:h-11"
                        aria-label={`Revoke ${r.relationship_type} relationship with ${r.source?.id === entity.id || r.source == null ? r.target.name : r.source.name}`}
                        onClick={() => setRevoking(r)}
                      >
                        <Undo2 aria-hidden />
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-co-all">
        <h2 id="entity-co-all" className="text-base font-semibold">
          Often mentioned together <span className="text-xs font-normal text-muted-foreground">365 days</span>
        </h2>
        {rels.isPending ? (
          <Skeleton className="h-24 w-full" />
        ) : coMentions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No co-mentions in the last year.</p>
        ) : (
          <CoMentionRows items={coMentions} canRelate={canManage} onRelate={(e) => create.start(e)} />
        )}
      </section>
      <RelationshipCreateDialog
        key={create.nonce}
        open={create.open}
        onClose={create.close}
        source={source}
        target={create.target}
      />
      <ConfirmDialog
        open={revoking != null}
        onOpenChange={(o) => !o && setRevoking(null)}
        title="Revoke relationship?"
        description="It disappears from this page and is marked revoked in the TAXII feed."
        confirmLabel="Revoke"
        onConfirm={() => {
          if (revoking) revoke.mutate(revoking.id);
          setRevoking(null);
        }}
      />
    </div>
  );
}
