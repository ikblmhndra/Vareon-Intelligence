import Link from "next/link";

import { PLATFORM_NAME } from "@/lib/brand";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="font-heading text-2xl tracking-wide text-foreground">{PLATFORM_NAME}</h1>
      <p className="text-sm text-muted-foreground">Halaman tidak ditemukan.</p>
      <Link href="/dashboard" className="text-sm underline underline-offset-4">
        Kembali ke Dashboard
      </Link>
    </div>
  );
}
