"use client";

import { AvatarMenu } from "@/components/app-shell/avatar-menu";
import { ClientSwitcher } from "@/components/client-switcher";
import { useAuth } from "@/components/providers/auth-provider";
import { useActiveClientName } from "@/lib/auth/client-id";
import { PLATFORM_NAME } from "@/lib/brand";

/** Bar tipis paling atas (mockup FigCraft "Utility"): konteks platform + client aktif di kiri,
 * switcher client dan menu avatar di kanan, ditutup garis tinta 2 px. Lebar kolom diatur `AppShell`. */
export function UtilityBar() {
  const { user } = useAuth();
  const clientName = useActiveClientName();

  return (
    <div className="flex h-[54px] items-center justify-between gap-4 border-b-2 border-foreground">
        <p className="min-w-0 truncate text-xs text-muted-foreground">
          {clientName ? `${PLATFORM_NAME} · ${clientName}` : PLATFORM_NAME}
        </p>
        <div className="flex shrink-0 items-center gap-3">
          {user && <ClientSwitcher user={user} />}
          <AvatarMenu />
        </div>
    </div>
  );
}
