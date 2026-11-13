"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Notice } from "@/components/ui/notice";
import { useSessionState } from "@/lib/auth/session-expired";

/** Logout ulang (idempoten: menutup kasus POST pertama di `client.ts` gagal), lalu load penuh ke
 * /login dengan `redirect` = halaman ini. Load penuh sengaja: membuang state klien dan store. */
async function signInAgain(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
  // Load penuh sengaja (bukan router.push): lihat docstring.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(
    "/login?redirect=" + encodeURIComponent(location.pathname + location.search),
  );
}

/** Dialog "sesi berakhir" (sekali per kedaluwarsa) + banner permanen sesudah "Close". Halaman di
 * bawahnya tetap terbaca; `guardedFetch` memastikan tidak ada request yang lolos. */
export function SessionExpiredHost() {
  const state = useSessionState();
  const [prev, setPrev] = useState(state);
  const [dismissed, setDismissed] = useState(false);
  const signInRef = useRef<HTMLButtonElement>(null);

  // Dibuka hanya pada transisi ke `expired` (bukan tiap render); 401 lanjutan tidak mengubah state.
  if (prev !== state) {
    setPrev(state);
    if (state === "expired") setDismissed(false);
  }

  if (state !== "expired") return null;

  return (
    <>
      <Dialog open={!dismissed} onOpenChange={(o) => !o && setDismissed(true)}>
        <DialogContent
          role="alertdialog"
          showCloseButton={false}
          initialFocus={signInRef}
          className="sm:max-w-[480px]"
        >
          <DialogHeader>
            <DialogTitle>Your session has ended</DialogTitle>
            <DialogDescription>
              For security, sessions end automatically, or when your password, role or client access
              changes. Sign in again to continue on this page.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDismissed(true)}>
              Close
            </Button>
            <Button ref={signInRef} onClick={() => void signInAgain()}>
              Sign in again
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {dismissed && (
        <Notice
          tone="warning"
          title="Your session has ended"
          className="mb-4"
          action={
            <Button size="sm" onClick={() => void signInAgain()}>
              Sign in again
            </Button>
          }
        >
          Nothing on this page can load or save until you sign in again.
        </Notice>
      )}
    </>
  );
}
