"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { AddPackagesDialog } from "@/components/cve/pkgvuln/add-packages-dialog";
import { PackagesPanel } from "@/components/cve/pkgvuln/packages-panel";
import { VulnsPanel } from "@/components/cve/pkgvuln/vulns-panel";
import { useCan } from "@/lib/auth/permissions";

type Segment = "vulns" | "packages";

/** Tab Package Vulnerabilities (spec 2a 6.7/6.8): pil "Vulnerabilities | Packages" di dalam kartu utama (D21);
 * toolbar Import lockfile / Scan all / + Add package (D20) dipakai bersama kedua segmen, dan keduanya membuka
 * `AddPackagesDialog` pada segmen yang cocok. */
export function PkgVulnView() {
  const can = useCan();
  const canManage = can("manage_cve");
  const queryClient = useQueryClient();
  const [segment, setSegment] = useState<Segment>("vulns");
  const [addOpen, setAddOpen] = useState(false);
  const [addMode, setAddMode] = useState<"single" | "import">("single");
  const [scanning, setScanning] = useState(false);

  const statsQuery = useQuery({
    queryKey: ["pkgvuln", "stats"],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pkgvuln/stats");
      if (error) throw error;
      return data;
    },
  });
  const stats = statsQuery.data;

  function openAdd(mode: "single" | "import") {
    setAddMode(mode);
    setAddOpen(true);
  }

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "packages"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
    void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
  }

  async function scanAll() {
    setScanning(true);
    const { error } = await api.POST("/api/pkgvuln/scan");
    if (error) toast.error("Scan failed to start");
    else toast.success("Scanning all packages...");
    // Scan berjalan di latar (tak ada endpoint status): segarkan sekarang dan sekali lagi sesudah jeda.
    invalidate();
    setTimeout(invalidate, 30000);
    setScanning(false);
  }

  const pills = (
    <SegmentedControl
      aria-label="Package view"
      value={segment}
      onChange={setSegment}
      options={[
        { value: "vulns", label: `Vulnerabilities ${stats?.total_vulns ?? 0}` },
        { value: "packages", label: `Packages ${stats?.packages ?? 0}` },
      ]}
    />
  );

  const actions = canManage ? (
    <>
      <Button variant="outline" onClick={() => openAdd("import")}>
        Import lockfile
      </Button>
      <Button variant="outline" loading={scanning} onClick={() => void scanAll()}>
        Scan all
      </Button>
      <Button onClick={() => openAdd("single")}>+ Add package</Button>
    </>
  ) : null;

  return (
    <div>
      {segment === "vulns" ? (
        <VulnsPanel stats={stats} segment={pills} actions={actions} />
      ) : (
        <PackagesPanel segment={pills} actions={actions} />
      )}
      <AddPackagesDialog open={addOpen} onOpenChange={setAddOpen} mode={addMode} />
    </div>
  );
}
