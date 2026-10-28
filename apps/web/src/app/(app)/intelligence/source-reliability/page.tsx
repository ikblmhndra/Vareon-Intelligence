"use client";

import { useState } from "react";

import { SrReviewTable } from "@/components/intelligence/source-reliability/sr-review-table";
import { SrTable } from "@/components/intelligence/source-reliability/sr-table";
import { TabPills } from "@/components/ui/tab-pills";
import { useCan } from "@/lib/auth/permissions";

type View = "all" | "review";

const VIEWS = [
  { value: "all", label: "All sources" },
  { value: "review", label: "Needs review" },
] as const;

export default function SourceReliabilityPage() {
  const can = useCan();
  const [view, setView] = useState<View>("all");

  // `GET /api/sr/review` butuh `manage_sources`; tanpa izin itu tab review cuma akan 403.
  if (!can("manage_sources")) return <SrTable />;

  return (
    <div>
      <TabPills aria-label="Source reliability views" className="mb-4" items={VIEWS} value={view} onChange={setView} />
      {view === "all" ? <SrTable /> : <SrReviewTable />}
    </div>
  );
}
