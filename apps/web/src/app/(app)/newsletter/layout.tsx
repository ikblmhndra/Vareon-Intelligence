import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
// Header halaman dirender `page.tsx` karena bergantung pada data.
export const metadata: Metadata = {
  title: { default: "Newsletter", template: `%s · ${PLATFORM_NAME}` },
};

export default function NewsletterLayout({ children }: { children: React.ReactNode }) {
  return children;
}
