"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api/client";

const ROWS = [
  { key: "mapped_family", label: "Mapped to a catalog product", dot: "bg-success" },
  { key: "mapped_vendor", label: "Mapped to a whole vendor", dot: "bg-info" },
  { key: "unmapped", label: "Unmapped (legacy name match)", dot: "bg-warning" },
  { key: "hidden", label: "Hidden", dot: "bg-border" },
] as const;

/** Kartu "Coverage" (kolom kanan Monitored Tech) + kartu statis "Exposure matters". Hitungan dari
 * `GET /api/techstack/coverage`; query ini ikut ter-invalidate oleh aksi Monitor (key `techstack`). */
export function CoverageCard() {
  const query = useQuery({
    queryKey: ["techstack", "coverage"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/techstack/coverage");
      if (error) throw error;
      return data;
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Coverage</CardTitle>
          <CardDescription>How the stack maps to the catalog</CardDescription>
        </CardHeader>
        <CardContent>
          {query.isError ? (
            <p role="alert" className="text-xs text-destructive-text">
              Could not load coverage.
            </p>
          ) : (
            <ul className="flex flex-col gap-2.5">
              {ROWS.map((r) => (
                <li key={r.key} className="flex items-center gap-2.5 text-sm">
                  <span aria-hidden className={`size-2 shrink-0 rounded-full ${r.dot}`} />
                  <span className="flex-1">{r.label}</span>
                  <span className="font-semibold tabular-nums">{query.data ? query.data[r.key] : "-"}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Exposure matters</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Public, internet-facing entries raise a CVE&apos;s adjusted risk and sort first in the CVEs tab. Set exposure and
            hosting so the ranking matches reality.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
