import type { Metadata } from "next";

import { PLATFORM_NAME } from "@/lib/brand";

// Template dipasang ulang: `title` string di layout segmen ini akan membuang template root untuk anak-anaknya.
// Header (kicker, judul tetap) dirender `AdminFrame` karena kickernya bergantung pada role pengguna.
export const metadata: Metadata = {
  title: { default: "Admin", template: `%s · ${PLATFORM_NAME}` },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return children;
}
