"use client";

import { useState } from "react";

import type { AuthUser } from "@/components/providers/auth-provider";
import { setActiveClientId, getActiveClientId } from "@/lib/auth/client-id";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Port switcher client aktif (superadmin bisa liat semua client user-nya,
 * `X-Client-ID` header dikirim tiap request lewat proxy -- lihat
 * `lib/api/client.ts`). Cuma tampil kalau user emang punya >1 client,
 * sama pola kayak app lama (single-client user gak pernah liat dropdown
 * ini sama sekali). */
export function ClientSwitcher({ user }: { user: AuthUser }) {
  const [value, setValue] = useState(() => getActiveClientId() ?? user.client_ids[0]);

  if (user.client_ids.length <= 1) return null;

  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (!next) return;
        setValue(next);
        setActiveClientId(next);
        // Reload penuh -- query yang udah di-cache TanStack Query bawa
        // data client LAMA, cara paling aman biar semua re-fetch dengan
        // X-Client-ID baru (port perilaku `onClientSwitch()` lama yang
        // juga reload seluruh tab aktif).
        window.location.reload();
      }}
    >
      {/* Gaya ghost ala utility bar mockup ("Client: {name} ▾", tanpa kotak); nama client
          panjang dipotong supaya tidak mendorong avatar keluar baris. */}
      <SelectTrigger
        size="sm"
        aria-label="Active client"
        className="max-w-48 border-transparent bg-transparent px-2 text-xs font-semibold hover:bg-surface"
      >
        <SelectValue className="min-w-0">
          {(id: string) => <span className="truncate">{`Client: ${id}`}</span>}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {user.client_ids.map((id) => (
          <SelectItem key={id} value={id} className="font-mono text-xs">
            {id}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
