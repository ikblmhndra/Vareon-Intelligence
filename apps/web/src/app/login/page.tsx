"use client";

import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { BrandMark } from "@/components/brand-mark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice } from "@/components/ui/notice";
import { PasswordRules } from "@/components/password-rules";
import { useAuth } from "@/components/providers/auth-provider";
import { api } from "@/lib/api/client";
import { allRulesMet, usePasswordPolicy } from "@/lib/auth/password-policy";
import { PLATFORM_NAME } from "@/lib/brand";
import { apiErrorMessage } from "@/lib/recap/quality";
import { usePageTitle } from "@/lib/use-page-title";

// Peta titik memuat world-atlas; ssr:false menjaga data geografi di luar first paint /login.
const WorldDots = dynamic(() => import("@/components/world-dots").then((m) => m.WorldDots), {
  ssr: false,
});

type Failure = { tone: "destructive" | "warning" | "neutral"; title: string; body: string };

// Revokasi sesi disimpan dalam detik utuh dan menolak token dengan `iat` <= detik itu. Jeda ini
// waktu terlewat (bukan jam dinding), jadi server pasti sudah melewati detik berikutnya sebelum
// sign-in ulang; tanpa jeda token baru ikut tercabut.
const RELOGIN_DELAY_MS = 1200;

const SIGN_IN_AGAIN_NOTICE: Failure = {
  tone: "neutral",
  title: "Password changed",
  body: "Sign in with your new password.",
};

/** Input password dengan tombol Show sendiri (tahap ganti-password paksa). */
function PasswordField({
  id,
  label,
  value,
  onChange,
  describedBy,
  autoFocus,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  describedBy?: string;
  autoFocus?: boolean;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input
          id={id}
          type={show ? "text" : "password"}
          autoComplete="new-password"
          aria-describedby={describedBy}
          autoFocus={autoFocus}
          className="pr-14"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
        />
        <button
          type="button"
          aria-pressed={show}
          aria-controls={id}
          onClick={() => setShow((v) => !v)}
          className="absolute inset-y-0 right-0 rounded-r-lg px-3 text-xs font-medium text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none"
        >
          {show ? "Hide" : "Show"}
        </button>
      </div>
    </div>
  );
}

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
  const { login, logout } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [deadline, setDeadline] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [stage, setStage] = useState<"sign-in" | "forced">("sign-in");
  // Password sign-in (`password`) dan dua isian di bawah hanya hidup di memori: dipakai sebagai
  // `current_password` lalu dikosongkan saat sukses, gagal, atau batal. Tanpa storage/URL/query cache.
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [forcedPhase, setForcedPhase] = useState<"saving" | "signing-in" | null>(null);
  const queryClient = useQueryClient();
  // Di /login sesi masih `signing-out`, jadi query kebijakan membeku di 401 sintetis: hanya aktif di tahap
  // forced (setelah login) dan di-invalidate saat masuk supaya entri error lama diambil ulang.
  const policy = usePasswordPolicy(stage === "forced");
  const passwordRef = useRef<HTMLInputElement>(null);
  usePageTitle(stage === "forced" ? "Choose a new password" : null);
  const redirect = searchParams.get("redirect");
  // Unmount (mis. tombol Back) selama jeda sign-in ulang: batalkan timer supaya closure berhenti
  // dan password baru tidak ikut tertahan, lalu jangan login/push lagi.
  const aliveRef = useRef(true);
  const submittingRef = useRef(false);
  const waitRef = useRef<{ timer: ReturnType<typeof setTimeout>; cancel: () => void } | null>(null);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      if (waitRef.current) {
        clearTimeout(waitRef.current.timer);
        waitRef.current.cancel();
      }
    };
  }, []);

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
        if (result.forcePwChange) {
          setFailure(null);
          setStage("forced");
          void queryClient.invalidateQueries({ queryKey: ["auth", "policy"] });
          return;
        }
        setPassword("");
        router.push(safeRedirect(redirect));
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

  /** Kembali ke tahap sign-in: semua password dikosongkan, username tetap. */
  function backToSignIn(notice: Failure | null) {
    setPassword("");
    setNewPassword("");
    setConfirm("");
    setForcedPhase(null);
    setStage("sign-in");
    setFailure(notice);
  }

  function cancelForced() {
    backToSignIn(null);
    void logout(redirect ?? undefined);
  }

  async function handleForcedSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current) return;
    submittingRef.current = true;
    try {
      await runForcedChange();
    } finally {
      submittingRef.current = false;
    }
  }

  async function runForcedChange() {
    setFailure(null);
    setForcedPhase("saving");
    const res = await api
      .POST("/api/auth/change-password", {
        body: { current_password: password, new_password: newPassword },
      })
      .catch(() => null);
    if (!res) {
      setForcedPhase(null);
      setFailure({ tone: "destructive", title: "Could not save the password", body: "Try again." });
      return;
    }
    const { response, error } = res;
    if (!response.ok) {
      setForcedPhase(null);
      const s = response.status;
      if (s === 422) {
        setFailure({
          tone: "destructive",
          title: "That password does not meet the policy",
          body: apiErrorMessage(error, s),
        });
      } else if (s === 400) {
        backToSignIn({
          tone: "warning",
          title: "Sign in again",
          body: "Your sign-in password changed while this page was open.",
        });
        void logout(redirect ?? undefined);
      } else if (s === 401) {
        backToSignIn({
          tone: "warning",
          title: "Your session has ended",
          body: "Sign in again to choose a new password.",
        });
      } else if (s === 429) {
        setFailure({
          tone: "destructive",
          title: "Too many attempts",
          body: "Try again in a few minutes.",
        });
      } else {
        setFailure({ tone: "destructive", title: "Could not save the password", body: "Try again." });
      }
      return;
    }
    setPassword("");
    setForcedPhase("signing-in");
    const waited = await new Promise<boolean>((resolve) => {
      waitRef.current = {
        timer: setTimeout(() => resolve(true), RELOGIN_DELAY_MS),
        cancel: () => resolve(false),
      };
    });
    waitRef.current = null;
    if (!waited || !aliveRef.current) return;
    try {
      const result = await login(username, newPassword);
      if (result.ok) {
        setNewPassword("");
        setConfirm("");
        router.push(safeRedirect(redirect));
        return;
      }
      if (result.status === 429) setDeadline(Date.now() + (result.retryAfterS ?? 60) * 1000);
    } catch {
      // Jaringan putus saat sign-in ulang: tampil sama, user masuk manual.
    }
    backToSignIn(SIGN_IN_AGAIN_NOTICE);
  }

  if (stage === "forced") {
    const mismatch = confirm !== "" && confirm !== newPassword;
    const busy = forcedPhase !== null;
    return (
      <form onSubmit={handleForcedSubmit} className="w-full max-w-sm space-y-6">
        <div className="space-y-1">
          <p className="text-2xs font-semibold uppercase tracking-widest text-muted-foreground">
            Sign in
          </p>
          <h2 className="font-heading text-2xl font-extrabold tracking-tight text-foreground">
            Choose a new password
          </h2>
          <p className="text-sm text-muted-foreground">
            Your account needs a new password, after an administrator reset or a policy change. Pick
            one to continue.
          </p>
        </div>

        {failure && (
          <div role="alert">
            <Notice tone={failure.tone} title={failure.title}>
              {failure.body}
            </Notice>
          </div>
        )}

        <PasswordField
          id="new-password"
          label="New password"
          autoFocus
          value={newPassword}
          onChange={setNewPassword}
          describedBy="new-password-rules"
        />
        <PasswordRules id="new-password-rules" password={newPassword} policy={policy} />

        <div className="space-y-2">
          <PasswordField
            id="confirm-password"
            label="Confirm new password"
            value={confirm}
            onChange={setConfirm}
            describedBy={mismatch ? "confirm-password-error" : undefined}
          />
          {mismatch && (
            <p id="confirm-password-error" role="alert" className="text-xs text-destructive-text">
              Passwords do not match.
            </p>
          )}
        </div>

        <Button
          type="submit"
          className="w-full"
          disabled={busy || !allRulesMet(newPassword, policy) || newPassword !== confirm}
        >
          {forcedPhase === "saving"
            ? "Saving…"
            : forcedPhase === "signing-in"
              ? "Signing you in…"
              : "Save and continue"}
        </Button>

        <button
          type="button"
          disabled={busy}
          onClick={cancelForced}
          className="rounded text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none disabled:opacity-50"
        >
          Cancel and sign out
        </button>
      </form>
    );
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
  { title: "CVE-2026-0119", meta: "KEV · CVSS 9.8", when: "2h ago", pos: "left-0 top-[4%]" },
  { title: "RANSOMWARE", meta: "New victim · PH", when: "5h ago", pos: "right-0 top-[34%]" },
  { title: "UNC5221", meta: "Active campaign", when: "today", pos: "left-[14%] top-[64%]" },
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

          {/* Kartu sinyal: dekorasi statis (bukan data, tanpa kontrol), di kolom antara merek dan judul
              supaya tidak pernah menimpa judul; yang tidak muat terpotong. */}
          <div className="pointer-events-none relative hidden min-h-0 flex-1 overflow-hidden md:block" aria-hidden="true">
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
