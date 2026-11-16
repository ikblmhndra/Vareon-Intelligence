import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
export const metadata: Metadata = {
  title: { default: "Data health", template: `%s · ${PLATFORM_NAME}` },
};

export default function DataHealthLayout({ children }: { children: React.ReactNode }) {
  return children;
}
