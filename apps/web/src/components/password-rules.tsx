import type { PasswordPolicy } from "@/lib/api/loose-types";
import { passwordRules } from "@/lib/auth/password-policy";
import { cn } from "@/lib/utils";

/** Checklist aturan password yang update tiap ketikan; `id` untuk `aria-describedby`. */
export function PasswordRules({
  password,
  policy,
  id,
}: {
  password: string;
  policy: PasswordPolicy;
  id?: string;
}) {
  return (
    <ul id={id} className="flex flex-col gap-1 text-xs">
      {passwordRules(password, policy).map((r) => (
        <li
          key={r.label}
          className={cn("flex items-center gap-2", r.met ? "text-success-text" : "text-muted-foreground")}
        >
          <span aria-hidden>{r.met ? "✓" : "○"}</span>
          <span>
            {r.label}
            <span className="sr-only">{r.met ? " met" : " not met"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
