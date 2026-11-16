"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { IocAllowlistPanel, useIocAllowlist } from "@/components/intelligence/ioc/ioc-allowlist-panel";
import { IocFpAnalyticsPanel } from "@/components/intelligence/ioc/ioc-fp-analytics-panel";
import { IocIndicatorsView, useIocStats } from "@/components/intelligence/ioc/ioc-table";
import { TabPills } from "@/components/ui/tab-pills";

type View = "indicators" | "allowlist" | "fp";
const isView = (v: string | null): v is View => v === "indicators" || v === "allowlist" || v === "fp";

/** IOC management (spec 2b 6.9): tiga tampilan halaman (Indicators | Allowlist | FP analytics) lewat
 * `?view=`, menggantikan tiga section bertumpuk. Indicators tetap ter-mount (disembunyikan) saat pindah
 * tampilan supaya filter, halaman, dan pilihan baris tidak hilang. Pemanggil membungkus dengan Suspense. */
export function IocManagementView() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("view");
  const view: View = isView(raw) ? raw : "indicators";
  const stats = useIocStats();
  const allowlist = useIocAllowlist();

  function setView(next: View) {
    const qs = new URLSearchParams(params.toString());
    if (next === "indicators") qs.delete("view");
    else qs.set("view", next);
    const s = qs.toString();
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false });
  }

  const tabs = [
    { value: "indicators" as const, label: "Indicators", count: stats.data?.total },
    { value: "allowlist" as const, label: "Allowlist", count: allowlist.data?.entries.length },
    { value: "fp" as const, label: "FP analytics" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <TabPills aria-label="IOC management views" items={tabs} value={view} onChange={setView} />
      <div role="tabpanel" aria-label="Indicators" hidden={view !== "indicators"}>
        <IocIndicatorsView />
      </div>
      {view === "allowlist" && (
        <div role="tabpanel" aria-label="Allowlist">
          <IocAllowlistPanel />
        </div>
      )}
      {view === "fp" && (
        <div role="tabpanel" aria-label="FP analytics">
          <IocFpAnalyticsPanel />
        </div>
      )}
    </div>
  );
}
