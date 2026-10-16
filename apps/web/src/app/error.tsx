"use client";

import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { Button, buttonVariants } from "@/components/ui/button";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="auth-backdrop flex min-h-dvh items-center justify-center px-6">
      <div role="alert" className="w-full max-w-md">
        <BrandMark />
        <h1 className="mt-8 font-heading text-3xl font-extrabold tracking-tight text-foreground">
          Halaman gagal dimuat
        </h1>
        <p className="mt-3 max-w-[40ch] text-sm text-muted-foreground">
          Terjadi kesalahan saat memuat halaman ini. Coba lagi, atau kembali ke Dashboard.
        </p>
        {error.digest && (
          <p className="mt-3 font-code text-xs text-muted-foreground">Kode: {error.digest}</p>
        )}
        <div className="mt-8 flex items-center gap-2">
          <Button onClick={reset}>Coba lagi</Button>
          <Link href="/dashboard" className={buttonVariants({ variant: "ghost" })}>
            Ke Dashboard
          </Link>
        </div>
      </div>
    </main>
  );
}
