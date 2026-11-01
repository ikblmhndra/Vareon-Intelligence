"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import { useCan } from "@/lib/auth/permissions";
import { ENTITY_TABS } from "@/lib/entities/types";
import { cn } from "@/lib/utils";

/**
 * Nama tanpa id (recap LLM, teks bebas) dicari lewat `/api/entities/resolve`; ketemu = redirect
 * ke halaman entity, 404 = pesan + jalan keluar (cari di daftar, atau buat entity baru).
 */
export function EntityResolveView() {
  const router = useRouter();
  const params = useSearchParams();
  const can = useCan();
  const type = params.get("type") ?? "";
  const name = params.get("name") ?? "";

  const q = useQuery({
    queryKey: ["entity-resolve", type, name],
    enabled: type !== "" && name !== "",
    retry: false,
    queryFn: async () => {
      const { data, response } = await api.GET("/api/entities/resolve", {
        params: { query: { type, name } },
      });
      if (data) return { id: data.id };
      if (response.status === 404) return null;
      throw new Error(`resolve gagal (${response.status})`, { cause: response.status });
    },
  });

  const id = q.data?.id;
  useEffect(() => {
    if (id != null) router.replace(`/intelligence/entities/${id}`);
  }, [id, router]);

  if (type === "" || name === "") {
    return <p className="text-sm text-muted-foreground">Missing type or name.</p>;
  }
  if (q.isPending || id != null) {
    return (
      <div className="space-y-2" role="status" aria-label="Resolving entity">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-4 w-40" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {q.error instanceof Error && q.error.cause === 403
          ? "You don't have access to entity pages."
          : "Could not look up this entity. Try again later."}
      </p>
    );
  }

  const first = type.split(",")[0];
  const tab = ENTITY_TABS.find((t) => t.types.some((x) => x === first))?.key ?? "actors";
  const search = new URLSearchParams({ tab, q: name });
  const create = new URLSearchParams({ new: "1", type: first, name });
  return (
    <section className="surface-raised space-y-3 rounded-xl p-5" aria-labelledby="resolve-title">
      <h2 id="resolve-title" className="text-base font-semibold">
        No entity named {name}
      </h2>
      <div className="flex flex-wrap gap-2">
        <Link
          href={`/intelligence/entities?${search}`}
          className={cn(buttonVariants({ variant: "outline" }), "max-sm:h-11")}
        >
          Search entities
        </Link>
        {can("manage_entities") && (
          <Link
            href={`/intelligence/entities?${create}`}
            className={cn(buttonVariants(), "max-sm:h-11")}
          >
            New entity
          </Link>
        )}
      </div>
    </section>
  );
}
