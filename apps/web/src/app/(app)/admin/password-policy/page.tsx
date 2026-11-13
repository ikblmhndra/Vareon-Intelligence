import type { Metadata } from "next";

import { PasswordPolicyView } from "@/components/admin/password-policy-view";

export const metadata: Metadata = { title: "Password policy · Admin" };

export default function AdminPasswordPolicyPage() {
  return <PasswordPolicyView />;
}
