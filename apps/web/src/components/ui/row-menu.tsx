"use client";

import { MoreHorizontalIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface RowMenuProps {
  /** Nama tombol pemicu untuk pembaca layar (mis. "Actions for CVE-2026-1234"). */
  label: string;
  items: readonly { label: string; onSelect: () => void; destructive?: boolean; hidden?: boolean }[];
}

/** Menu aksi baris (titik tiga). Tidak merender apa pun bila semua item `hidden`. */
export function RowMenu({ label, items }: RowMenuProps) {
  const visible = items.filter((i) => !i.hidden);
  if (visible.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={label} />}>
        <MoreHorizontalIcon aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {visible.map((i) => (
          <DropdownMenuItem
            key={i.label}
            variant={i.destructive ? "destructive" : "default"}
            onClick={i.onSelect}
          >
            {i.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
