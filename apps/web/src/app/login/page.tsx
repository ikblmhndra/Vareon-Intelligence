"use client";

import { Suspense, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/components/providers/auth-provider";
import { PLATFORM_NAME } from "@/lib/brand";

// Peta titik memuat world-atlas; ssr:false menjaga data geografi di luar first paint /login.
const WorldDots = dynamic(() => import("@/components/world-dots").then((m) => m.WorldDots), {
  ssr: false,
});

const HERO_POINTS = [
  "Berita ancaman dari banyak sumber, dirangkum dan diberi skor.",
  "CVE dicocokkan dengan tech stack organisasi Anda.",
  "Aktor, TTP dan IOC dipetakan ke MITRE ATT&CK.",
];

/** Hanya path internal ("/x"); tolak "//host", "/\\host", dan URL absolut (open redirect). */
function safeRedirect(target: string | null): string {
  if (target && target.startsWith("/") && !target.startsWith("//") && !target.startsWith("/\\")) {
    return target;
  }
  return "/dashboard";
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const result = await login(username, password);
      if (!result.ok) {
        setError(result.detail);
        return;
      }
      router.push(safeRedirect(searchParams.get("redirect")));
    } catch {
      setError("Tidak bisa terhubung ke server. Coba lagi.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-6">
      <div className="space-y-1">
        <h2 className="font-heading text-2xl font-extrabold tracking-tight text-foreground">Masuk</h2>
        <p className="text-sm text-muted-foreground">Gunakan akun Vareon Anda.</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="username">Username</Label>
        <Input
          id="username"
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Signing in..." : "Sign in"}
      </Button>

      <p className="text-xs text-muted-foreground">Lupa password? Hubungi admin platform.</p>
    </form>
  );
}

// `useSearchParams()` (baca query `?redirect=`, dipakai `LoginForm`) butuh
// dibungkus `<Suspense>` biar `/login` bisa di-prerender statis -- KETEMU
// pas `pnpm build` Grup A ("should be wrapped in a suspense boundary"),
// gak muncul di `pnpm dev` (Turbopack dev gak prerender).
export default function LoginPage() {
  return (
    <main className="grid min-h-dvh bg-background md:grid-cols-[1.1fr_1fr]">
      <section className="relative overflow-hidden bg-hero text-hero-foreground">
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <WorldDots className="opacity-100" fit="cover" />
        </div>
        <div className="relative flex h-full flex-col justify-between gap-10 px-6 py-8 md:p-12">
          <div className="flex items-center gap-3">
            <BrandMark className="size-9 text-base" />
            <span className="font-heading text-lg font-extrabold tracking-tight">{PLATFORM_NAME}</span>
          </div>

          <div className="space-y-6">
            <p className="text-2xs font-semibold uppercase tracking-widest text-hero-eyebrow">
              Cyber threat intelligence
            </p>
            <h1 className="max-w-[16ch] font-heading text-[32px] font-[750] leading-tight text-balance">
              Tahu lebih dulu. Bertindak lebih cepat.
            </h1>
            <ul className="hidden space-y-3 text-hero-muted md:block">
              {HERO_POINTS.map((line) => (
                <li key={line} className="flex items-start gap-3 text-sm">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-hero-accent" aria-hidden="true" />
                  {line}
                </li>
              ))}
            </ul>
          </div>

          <p className="hidden text-[11.5px] text-hero-muted md:block">
            Akses terbatas untuk pengguna terdaftar
          </p>
        </div>
      </section>

      <section className="flex items-center justify-center px-6 py-10 md:px-12">
        <Suspense>
          <LoginForm />
        </Suspense>
      </section>
    </main>
  );
}
