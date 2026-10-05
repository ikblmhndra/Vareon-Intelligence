"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/components/providers/auth-provider";
import { PLATFORM_NAME } from "@/lib/brand";

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
    <form
      onSubmit={handleSubmit}
      className="w-full max-w-sm space-y-6 rounded-3xl border border-border bg-card p-8 shadow-sm"
    >
      <div className="space-y-1 text-center">
        <h1 className="font-heading text-2xl tracking-wide text-foreground">{PLATFORM_NAME}</h1>
        <p className="text-sm text-muted-foreground">Sign in to continue</p>
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

      {error && <p className="text-sm text-destructive">{error}</p>}

      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? "Signing in..." : "Sign in"}
      </Button>
    </form>
  );
}

// `useSearchParams()` (baca query `?redirect=`, dipakai `LoginForm`) butuh
// dibungkus `<Suspense>` biar `/login` bisa di-prerender statis -- KETEMU
// pas `pnpm build` Grup A ("should be wrapped in a suspense boundary"),
// gak muncul di `pnpm dev` (Turbopack dev gak prerender).
export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
