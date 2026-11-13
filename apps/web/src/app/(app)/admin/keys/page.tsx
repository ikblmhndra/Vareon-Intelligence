import type { Metadata } from "next";

import { KeysView } from "@/components/admin/keys-view";

export const metadata: Metadata = { title: "Third-party keys · Admin" };

export default function AdminKeysPage() {
  return <KeysView />;
}
