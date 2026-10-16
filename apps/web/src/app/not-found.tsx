import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";
import { buttonVariants } from "@/components/ui/button";
import { PLATFORM_NAME } from "@/lib/brand";

export default function NotFound() {
  return (
    <div className="auth-backdrop flex min-h-dvh items-center justify-center px-6">
      <div className="w-full max-w-md">
        <div className="flex items-center gap-3">
          <BrandMark />
          <span className="font-heading text-sm font-semibold text-muted-foreground">{PLATFORM_NAME}</span>
        </div>
        <p aria-hidden className="mt-10 font-heading text-8xl font-extrabold tracking-tighter text-primary tabular-nums">
          404
        </p>
        <h1 className="mt-2 font-heading text-3xl font-extrabold tracking-tight text-foreground">
          Halaman tidak ditemukan
        </h1>
        <p className="mt-3 max-w-[40ch] text-sm text-muted-foreground">
          Alamatnya mungkin salah ketik, atau halamannya sudah dipindahkan.
        </p>
        <Link href="/dashboard" className={buttonVariants({ className: "mt-8" })}>
          Kembali ke Dashboard
        </Link>
      </div>
    </div>
  );
}
