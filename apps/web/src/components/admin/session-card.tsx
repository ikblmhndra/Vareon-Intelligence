"use client";

import { useAuth } from "@/components/providers/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { browserZoneName, fmtDateTime } from "@/lib/format";

/** Kartu "Your session" (D11): siapa yang masuk, client yang bisa dipakai, dan waktu sign-in token ini. Tanpa IP. */
export function SessionCard() {
  const { user } = useAuth();
  if (!user) return null;
  const ids = user.client_ids;
  const clients =
    user.role === "superadmin"
      ? "all clients"
      : ids.slice(0, 3).join(", ") + (ids.length > 3 ? ` +${ids.length - 3}` : "");
  return (
    <section aria-label="Your session" className="rounded-lg border border-border bg-card p-4">
      <p className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">Your session</p>
      <div className="mt-3 flex items-center gap-3">
        <Avatar>
          <AvatarFallback>{user.username.slice(0, 2).toUpperCase()}</AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <p className="truncate font-code text-sm font-semibold text-foreground">{user.username}</p>
          <p className="truncate text-xs text-muted-foreground">
            {user.role} · {clients}
          </p>
        </div>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {user.signed_in_at ? `Signed in ${fmtDateTime(user.signed_in_at)} ${browserZoneName()}. ` : ""}
        Token revoked on sign-out.
      </p>
    </section>
  );
}
