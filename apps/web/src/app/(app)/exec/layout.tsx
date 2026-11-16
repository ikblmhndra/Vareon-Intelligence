import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
// Header halaman (kicker, judul dinamis, pemilih tampilan) dirender `page.tsx` karena bergantung pada periode & data.
export const metadata: Metadata = {
  title: { default: "Exec", template: `%s · ${PLATFORM_NAME}` },
};

export default function ExecLayout({ children }: { children: React.ReactNode }) {
  return children;
}
