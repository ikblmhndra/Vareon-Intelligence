"use client";

import { useRef, useState } from "react";
import { useTheme } from "next-themes";

import { ChangePasswordDialog } from "@/components/change-password-dialog";
import { ChangelogDialog } from "@/components/changelog-dialog";
import { useAuth } from "@/components/providers/auth-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Menu avatar di utility bar: menampung aksi global yang dulu tersebar di topbar (Changelog,
 * toggle tema, user menu). Kedua dialog dirender DI LUAR `DropdownMenuContent` karena popup menu
 * di-unmount saat menutup -- dialog di dalamnya akan ikut hilang begitu item diklik. */
export function AvatarMenu() {
  const { user, logout } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const [pwOpen, setPwOpen] = useState(false);
  const [changelogOpen, setChangelogOpen] = useState(false);
  // Item menu pemicu dialog sudah di-unmount saat dialog menutup: kembalikan fokus ke avatar.
  const triggerRef = useRef<HTMLButtonElement>(null);

  if (!user) return null;

  const nextTheme = resolvedTheme === "dark" ? "light" : "dark";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          ref={triggerRef}
          aria-label={`Account menu for ${user.username}`}
          className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-full bg-surface text-xs font-semibold text-foreground outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          {user.username.slice(0, 2).toUpperCase()}
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="text-sm font-semibold text-foreground">
              {user.username}
              <span className="block text-2xs font-normal text-muted-foreground">{user.role}</span>
            </DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setPwOpen(true)}>Change password</DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme(nextTheme)}>
            {`Theme: switch to ${nextTheme}`}
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setChangelogOpen(true)}>Changelog</DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => void logout()}>Log out</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ChangePasswordDialog open={pwOpen} onOpenChange={setPwOpen} finalFocus={triggerRef} />
      <ChangelogDialog
        open={changelogOpen}
        onOpenChange={setChangelogOpen}
        finalFocus={triggerRef}
      />
    </>
  );
}
