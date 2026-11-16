import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
export const metadata: Metadata = {
  title: { default: "Scrapers", template: `%s · ${PLATFORM_NAME}` },
};

export default function ScrapersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
