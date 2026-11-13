"use client";

import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice } from "@/components/ui/notice";
import { useAuth } from "@/components/providers/auth-provider";
import { PLATFORM_NAME } from "@/lib/brand";

// Peta titik memuat world-atlas; ssr:false menjaga data geografi di luar first paint /login.
const WorldDots = dynamic(() => import("@/components/world-dots").then((m) => m.WorldDots), {
  ssr: false,
});

type Failure = { tone: "destructive" | "warning" | "neutral"; title: string; body: string };

/** Hanya path internal ("/x"); tolak "//host", "/\\host", dan URL absolut (open redirect). */
function safeRedirect(target: string | null): string {
  if (target && target.startsWith("/") && !target.startsWith("//") && !target.startsWith("/\\")) {
    return target;
  }
  return "/dashboard";
}

/** Teks gagal-masuk tetap per status (spec 6.1); `detail` API sengaja tidak pernah dicetak. */
function loginFailure(result: { status: number; retryAfterS: number | null } | "network"): Failure {
  if (result === "network") {
    return {
      tone: "destructive",
      title: "Cannot reach the server",
      body: "Check your connection and try again.",
    };
  }
  const { status } = result;
  if (status === 401) {
    return {
      tone: "destructive",
      title: "Username or password is incorrect",
      body: "Check both and try again. After 10 tries in a minute, sign-in pauses briefly.",
    };
  }
  if (status === 429) {
    const seconds = result.retryAfterS ?? 60;
    const wait = seconds === 60 ? "1 minute" : `${seconds} seconds`;
    return {
      tone: "warning",
      title: "Too many sign-in attempts",
      body: `Wait ${wait} before trying again. Your administrator can reset the password if you forgot it.`,
    };
  }
  if (status === 400) {
    return {
      tone: "warning",
      title: "This account signs in with SSO",
      body: "Password sign-in is not available for it. Contact your platform admin.",
    };
  }
  if (status >= 500) {
    return {
      tone: "destructive",
      title: "The sign-in service is not responding",
      body: "Try again in a moment.",
    };
  }
  return {
    tone: "destructive",
    title: "Sign-in failed",
    body: "Try again. If it keeps failing, contact your platform admin.",
  };
}

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const passwordRef = useRef<HTMLInputElement>(null);

  // Hitung mundur 429: satu interval per deadline, dibersihkan saat unmount atau deadline berubah.
  useEffect(() => {
    if (deadline === null) return;
    const tick = () => {
      const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) {
        setDeadline(null);
        setFailure(null);
      }
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFailure(null);
    setDeadline(null);
    setRemaining(0);
    setPending(true);
    let failed: Failure | null = null;
    try {
      const result = await login(username, password);
      if (result.ok) {
        // Tahap ganti-password paksa menyusul di Task 7; sementara dialog layout (app) yang mengambil alih.
        router.push(safeRedirect(searchParams.get("redirect")));
        return;
      }
      failed = loginFailure(result);
      if (result.status === 429) {
        setDeadline(Date.now() + (result.retryAfterS ?? 60) * 1000);
      }
    } catch {
      failed = loginFailure("network");
    } finally {
      setPending(false);
    }
    setFailure(failed);
    passwordRef.current?.focus();
  }

  const counting = remaining > 0;

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-6">
      <div className="space-y-1">
        <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
          Sign in
        </p>
        <h2 className="font-heading text-2xl font-extrabold tracking-tight text-foreground">
          Welcome back
        </h2>
        <p className="text-sm text-muted-foreground">Use your Vareon account.</p>
      </div>

      {failure && (
        <div role="alert">
          <Notice tone={failure.tone} title={failure.title}>
            {failure.body}
          </Notice>
        </div>
      )}

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
        <div className="relative">
          <Input
            id="password"
            ref={passwordRef}
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            className="pr-14"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button
            type="button"
            aria-pressed={showPassword}
            aria-controls="password"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute inset-y-0 right-0 rounded-r-lg px-3 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
      </div>

      <Button type="submit" className="w-full" disabled={pending || counting}>
        {pending ? "Signing in…" : counting ? `Try again in ${remaining} s` : "Sign in"}
      </Button>

      <p className="text-xs text-muted-foreground">
        Forgot your password? Contact your platform admin.
      </p>
    </form>
  );
}

const SIGNALS = [
  { title: "CVE-2026-0119", meta: "KEV · CVSS 9.8", when: "2h ago", pos: "left-[8%] top-[46%]" },
  { title: "RANSOMWARE", meta: "New victim · PH", when: "5h ago", pos: "right-[8%] top-[34%]" },
  { title: "UNC5221", meta: "Active campaign", when: "today", pos: "left-[22%] top-[66%]" },
];

// `useSearchParams()` (baca query `?redirect=`, dipakai `LoginForm`) butuh
// dibungkus `<Suspense>` biar `/login` bisa di-prerender statis -- KETEMU
// pas `pnpm build` Grup A ("should be wrapped in a suspense boundary"),
// gak muncul di `pnpm dev` (Turbopack dev gak prerender).
export default function LoginPage() {
  return (
    <main className="grid min-h-dvh bg-background md:grid-cols-2">
      <section className="relative overflow-hidden bg-hero text-hero-foreground">
        <div className="pointer-events-none absolute inset-0" aria-hidden="true">
          <WorldDots className="opacity-100" fit="cover" />
        </div>
        {/* Kartu sinyal: dekorasi statis, bukan data dan tanpa kontrol. */}
        <div className="pointer-events-none absolute inset-0 hidden md:block" aria-hidden="true">
          {SIGNALS.map((s) => (
            <div
              key={s.title}
              className={`absolute ${s.pos} rounded-lg bg-hero-panel px-3 py-2 text-2xs`}
            >
              <p className="font-code font-semibold tracking-wide text-hero-foreground">{s.title}</p>
              <p className="text-hero-muted">{s.meta}</p>
              <p className="text-hero-eyebrow">{s.when}</p>
            </div>
          ))}
        </div>
        <div className="relative flex h-full flex-col justify-between gap-10 px-6 py-8 md:p-12">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <BrandMark className="size-9 text-base" />
              <span className="font-heading text-lg font-extrabold tracking-tight">
                {PLATFORM_NAME}
              </span>
            </div>
            <p className="hidden text-2xs font-semibold uppercase tracking-widest text-hero-eyebrow md:block">
              Threat intelligence platform
            </p>
            <p className="hidden items-center gap-2 text-2xs uppercase tracking-widest text-hero-muted md:flex">
              <span
                aria-hidden="true"
                className="size-1.5 animate-pulse rounded-full bg-hero-accent motion-reduce:animate-none"
              />
              <span className="font-code">06°12′S 106°49′E</span>
              <span>· APAC coverage</span>
            </p>
          </div>

          <div className="space-y-4">
            <h1 className="max-w-[16ch] font-heading text-[32px] font-[750] leading-tight text-balance">
              Threat intelligence, briefed daily.
            </h1>
            <p className="hidden max-w-sm text-sm text-hero-muted md:block">
              News, ransomware, CVEs and threat actors from across APAC, ranked by what matters to
              your organisation.
            </p>
          </div>

          <p className="hidden text-[11.5px] text-hero-muted md:block">{PLATFORM_NAME}</p>
        </div>
      </section>

      <section className="flex flex-col px-6 py-10 md:px-12">
        <p className="hidden text-2xs text-muted-foreground md:block">
          {PLATFORM_NAME} · Authorized users only
        </p>
        <div className="flex flex-1 items-center justify-center">
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
        <div className="hidden items-center justify-between text-2xs text-muted-foreground md:flex">
          <span>Sign-in activity is logged.</span>
          <span>
            {PLATFORM_NAME} · v{process.env.NEXT_PUBLIC_APP_VERSION}
          </span>
        </div>
      </section>
    </main>
  );
}
