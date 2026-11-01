"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { SubListSection, SUBLIST_PAGE_SIZE } from "@/components/entities/entity-subtab";
import { IocDetailDialog, type IocTarget } from "@/components/intelligence/ioc/ioc-detail-dialog";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { relativeTime } from "@/lib/cve/freshness";
import { defang } from "@/lib/intelligence/defang";

type EntityDetail = components["schemas"]["EntityDetail"];

/** Indikator yang terhubung ke entity; baris membuka dialog detail IOC yang sudah ada. */
export function EntityIndicatorsTab({ entity }: { entity: EntityDetail }) {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [target, setTarget] = useState<IocTarget | null>(null);

  const list = useQuery({
    queryKey: ["entity-indicators", entity.id, page],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/entities/{entity_id}/indicators", {
        params: {
          path: { entity_id: entity.id },
          query: { limit: SUBLIST_PAGE_SIZE, offset: (page - 1) * SUBLIST_PAGE_SIZE },
        },
      });
      if (error || !data) throw new Error("indicators failed");
      return data;
    },
  });

  return (
    <>
      <SubListSection
        id="entity-indicators"
        title="Indicators"
        status={list.status}
        total={list.data?.total ?? 0}
        emptyText="No indicators are linked to this entity yet."
        page={page}
        onPageChange={setPage}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Value</TableHead>
              <TableHead>Type</TableHead>
              <TableHead className="text-right">Confidence</TableHead>
              <TableHead>First seen</TableHead>
              <TableHead>Last seen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((i) => (
              <TableRow key={i.id}>
                <TableCell className="max-w-sm">
                  <button
                    type="button"
                    onClick={() => setTarget({ type: i.type, value: i.value })}
                    className="max-w-full rounded text-left font-code text-xs break-all text-primary-text underline-offset-2 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-focus"
                  >
                    {defang(i.type, i.value)}
                  </button>
                  {i.revoked_at && (
                    <Badge variant="destructive" className="ml-2">
                      Revoked
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-xs">{i.type}</TableCell>
                <TableCell className="text-right font-code text-xs">{i.confidence_score}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{relativeTime(i.first_seen_at)}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{relativeTime(i.last_seen_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </SubListSection>
      <IocDetailDialog
        target={target}
        onClose={() => setTarget(null)}
        onDeleted={() => {
          setTarget(null);
          void qc.invalidateQueries({ queryKey: ["entity-indicators", entity.id] });
          void qc.invalidateQueries({ queryKey: ["entity-totals", entity.id] });
        }}
      />
    </>
  );
}
