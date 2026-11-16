"use client";

import { usePathname } from "next/navigation";

import { IntelligenceNav } from "@/components/intelligence/intelligence-nav";
import { PageHeader } from "@/components/page-header";
import { routeFor } from "@/lib/intelligence/routes";

/** Header Intelligence: kicker + H1 + deskripsi mengikuti tab aktif, lalu pil dan garis tipis.
 * Detail entitas tidak memakainya (halaman itu punya `<h1>` sendiri), jadi `routeFor` mengembalikan `null`
 * dan tidak ada yang dirender -- pil pun ikut hilang. Pola sama dengan `CvePageHeader`. */
export function IntelligencePageHeader() {
  const pathname = usePathname();
  const route = routeFor(pathname);
  if (!route) return null;
  return (
    <>
      <PageHeader kicker="INTELLIGENCE" title={route.title} description={route.description} className="mb-4" />
      <IntelligenceNav />
    </>
  );
}
