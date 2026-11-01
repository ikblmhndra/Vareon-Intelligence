"use client";

import { Download } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { EntityChip } from "@/components/entities/entity-chip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type EntityDetail = components["schemas"]["EntityDetail"];

/** Tab ATT&CK: teknik, mitigasi, dan unduhan layer Navigator (`<nama entity>-layer.json`). */
export function EntityAttackTab({ entity }: { entity: EntityDetail }) {
  const attack = useQuery({
    queryKey: ["entity-attack", entity.id],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/attack", {
        params: { path: { entity_id: entity.id } },
      });
      if (error || !data) throw new Error("attack failed");
      return data;
    },
  });

  function downloadLayer() {
    if (!attack.data) return;
    try {
      const blob = new Blob([JSON.stringify(attack.data.layer, null, 2)], { type: "application/json" });
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = `${entity.name}-layer.json`;
      anchor.click();
      URL.revokeObjectURL(anchor.href);
    } catch (e) {
      toast.error(`Download failed: ${(e as Error).message}`);
    }
  }

  if (attack.isPending) return <Skeleton className="h-48 w-full" />;
  if (attack.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Could not load ATT&amp;CK data. Try again later.
      </p>
    );
  }
  const { techniques, mitigations } = attack.data;

  return (
    <div className="space-y-4">
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-attack-tech">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="entity-attack-tech" className="text-base font-semibold">
            Techniques{" "}
            <span className="text-xs font-normal text-muted-foreground">{techniques.length} total</span>
          </h2>
          <Button variant="outline" size="sm" className="max-sm:h-11" onClick={downloadLayer}>
            <Download aria-hidden />
            Navigator layer
          </Button>
        </div>
        {techniques.length === 0 ? (
          <p className="text-sm text-muted-foreground">No techniques mapped to this entity.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Technique</TableHead>
                <TableHead>Tactics</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {techniques.map((t) => (
                <TableRow key={t.id}>
                  <TableCell>
                    <EntityChip
                      type={t.type}
                      name={t.name}
                      id={t.id}
                      label={t.external_id ? `${t.external_id} ${t.name}` : t.name}
                    />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{t.tactics.join(", ") || "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
      <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="entity-attack-mit">
        <h2 id="entity-attack-mit" className="text-base font-semibold">
          Mitigations{" "}
          <span className="text-xs font-normal text-muted-foreground">{mitigations.length} total</span>
        </h2>
        {mitigations.length === 0 ? (
          <p className="text-sm text-muted-foreground">No mitigations listed.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mitigation</TableHead>
                <TableHead>Addresses</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mitigations.map((m) => (
                <TableRow key={m.mitigation_id}>
                  <TableCell className="max-w-md whitespace-normal">
                    <span className="font-code text-xs">{m.mitigation_id}</span>{" "}
                    <span className="text-sm font-medium">{m.name}</span>
                    {m.description && (
                      <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{m.description}</p>
                    )}
                  </TableCell>
                  <TableCell className="font-code text-xs break-words whitespace-normal">
                    {m.techniques.join(", ") || "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
