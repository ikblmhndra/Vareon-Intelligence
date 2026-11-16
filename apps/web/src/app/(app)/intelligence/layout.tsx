import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";
import { IntelligencePageHeader } from "@/components/intelligence/intelligence-page-header";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
export const metadata: Metadata = {
  title: { default: "Intelligence", template: `%s · ${PLATFORM_NAME}` },
};

export default function IntelligenceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <IntelligencePageHeader />
      {children}
    </div>
  );
}
