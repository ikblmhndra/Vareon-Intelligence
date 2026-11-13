import { Suspense } from "react";

import { ScrapersView } from "@/components/scrapers/scrapers-view";

export default function ScrapersPage() {
  // `useSearchParams` di ScrapersView (pilihan scraper dari URL) mewajibkan batas Suspense.
  return (
    <Suspense>
      <ScrapersView />
    </Suspense>
  );
}
