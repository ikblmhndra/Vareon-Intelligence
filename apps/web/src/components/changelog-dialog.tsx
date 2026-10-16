"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Markdown from "react-markdown";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Validasi pola end-to-end Grup A: modal (shadcn Dialog, gantiin overlay
 * manual lama) + client typed (`api.GET`, schema dari OpenAPI) + proxy
 * (`/api/proxy/api/changelog`) + markdown asli (`react-markdown`, gantiin
 * mini-parser regex `_clRenderMd` lama yang gak support nested list/link/
 * table). Endpoint ini gak butuh auth (`changelog.py` gak pasang
 * `Depends(require_auth)`), jadi jalan duluan tanpa nunggu login beneran
 * -- test pertama yang paling murah buat mastiin pipa proxy-nya hidup.
 */
export function ChangelogDialog() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <Dialog onOpenChange={(open) => !open && setSelected(null)}>
      <DialogTrigger render={<Button variant="ghost" size="sm" className="font-mono text-xs" />}>
        Changelog
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
        {selected ? (
          <VersionDetail version={selected} onBack={() => setSelected(null)} />
        ) : (
          <VersionList onSelect={setSelected} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function VersionList({ onSelect }: { onSelect: (version: string) => void }) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["changelog", "list"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/changelog");
      if (error) throw error;
      return data;
    },
  });

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-heading">Changelog</DialogTitle>
      </DialogHeader>
      <div className="space-y-1">
        {isPending && (
          <>
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </>
        )}
        {isError && <p className="text-sm text-destructive">Failed to load changelog.</p>}
        {data?.map((entry) => (
          <button
            key={entry.version}
            onClick={() => onSelect(entry.version)}
            className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-accent"
          >
            <span className="font-mono">{entry.version}</span>
            <span className="text-muted-foreground">{entry.date}</span>
          </button>
        ))}
      </div>
    </>
  );
}

function VersionDetail({ version, onBack }: { version: string; onBack: () => void }) {
  const { data, isPending } = useQuery({
    queryKey: ["changelog", "detail", version],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/changelog/{version}", {
        params: { path: { version } },
      });
      if (error) throw error;
      return data;
    },
  });

  return (
    <>
      <DialogHeader>
        <Button variant="link" size="sm" className="w-fit px-0" onClick={onBack}>
          ← Back
        </Button>
        <DialogTitle className="font-mono">
          {version} {data?.date && <span className="text-muted-foreground">· {data.date}</span>}
        </DialogTitle>
      </DialogHeader>
      {isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="prose prose-sm max-w-none font-mono text-xs leading-relaxed">
          <Markdown>{data?.content ?? ""}</Markdown>
        </div>
      )}
    </>
  );
}
