"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import {
  useApiTokens,
  useAdminUsers,
  useAuditLog,
  useSecrets,
} from "@/components/admin/hooks";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Skeleton } from "@/components/ui/skeleton";
import { StatePanel } from "@/components/ui/state-panel";
import { StatTile } from "@/components/ui/stat-tile";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCan } from "@/lib/auth/permissions";
import { usePasswordPolicyQuery } from "@/lib/auth/password-policy";
import { fmtAgo, fmtShortDate, fmtTime } from "@/lib/format";

const DAY_MS = 86_400_000;
const AUDIT_PARAMS = { page: 1, pageSize: 6, user: "", action: "" };

type Tone = "neutral" | "destructive" | "warning" | "success";

function TileSlot({
  q,
  label,
  render,
}: {
  q: { data: unknown; isPending: boolean; isError: boolean };
  label: string;
  render: () => ReactNode;
}) {
  if (q.data === undefined && q.isPending) {
    return (
      <div role="status">
        <Skeleton aria-hidden className="h-[104px] w-full" />
        <span className="sr-only">Loading {label}</span>
      </div>
    );
  }
  if (q.data === undefined && q.isError) return <StatTile label={label} value="–" sub="failed to load" />;
  return render();
}

/** Empat tile angka; tiap tile punya query sendiri, hanya dibuat bila permission-nya ada, dan tidak
 * bisa difokus (tanpa `onSelect`). "Sekarang" selalu `nowMs` dari queryFn, bukan `Date.now()` saat render. */
export function UsersTiles() {
  const can = useCan();
  const { user: me } = useAuth();
  const canUsers = can("manage_users");
  const canTokens = can("manage_api_tokens");
  const isSuper = me?.role === "superadmin";
  const users = useAdminUsers(canUsers);
  const tokens = useApiTokens(canTokens);
  const secrets = useSecrets(isSuper);
  if (!canUsers && !canTokens && !isSuper) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {canUsers && (
        <TileSlot
          q={users}
          label="USERS"
          render={() => {
            const { users: rows, nowMs } = users.data!;
            const week = rows.filter(
              (u) => u.last_sign_in && nowMs - new Date(u.last_sign_in).getTime() <= 7 * DAY_MS,
            ).length;
            return <StatTile label="USERS" value={rows.length} sub={`${week} signed in this week`} />;
          }}
        />
      )}
      {canUsers && (
        <TileSlot
          q={users}
          label="MUST CHANGE PASSWORD"
          render={() => {
            const n = users.data!.users.filter((u) => u.force_pw_change).length;
            return (
              <StatTile
                label="MUST CHANGE PASSWORD"
                value={n}
                sub={n > 0 ? "must choose a new one at next sign-in" : "nobody is flagged"}
                tone={n > 0 ? "warning" : "success"}
              />
            );
          }}
        />
      )}
      {canTokens && (
        <TileSlot
          q={tokens}
          label="API TOKENS"
          render={() => {
            const { tokens: rows, nowMs } = tokens.data!;
            const active = rows.filter((t) => t.status === "active");
            const left = active
              .filter((t) => t.expires_at && new Date(t.expires_at).getTime() - nowMs <= 30 * DAY_MS)
              .map((t) => Math.ceil((new Date(t.expires_at!).getTime() - nowMs) / DAY_MS));
            const sub =
              left.length === 0
                ? "none expire within 30 days"
                : left.length === 1
                  ? `1 expires in ${left[0]} days`
                  : `${left.length} expire within 30 days`;
            return (
              <StatTile
                label="API TOKENS"
                value={`${active.length} active`}
                sub={sub}
                tone={left.length > 0 ? "warning" : "success"}
              />
            );
          }}
        />
      )}
      {isSuper && (
        <TileSlot
          q={secrets}
          label="THIRD-PARTY KEYS"
          render={() => {
            const ps = secrets.data!.providers;
            const set = ps.filter((p) => p.source !== "unset").length;
            const failed = ps.filter((p) => p.last_test_ok === false).length;
            const unset = ps.length - set;
            const tone: Tone = failed > 0 ? "destructive" : unset > 0 ? "warning" : "success";
            return (
              <StatTile
                label="THIRD-PARTY KEYS"
                value={`${set} / ${ps.length}`}
                sub={
                  failed === 0 && unset === 0
                    ? "all set, none failing"
                    : `${failed} failed its last test · ${unset} not set`
                }
                tone={tone}
              />
            );
          }}
        />
      )}
    </div>
  );
}

function MiniCard({
  title,
  subtitle,
  link,
  children,
}: {
  title: string;
  subtitle: string;
  link?: { href: string; label: string };
  children: ReactNode;
}) {
  const id = `mini-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section aria-labelledby={id} className="rounded-2xl surface-raised p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 id={id} className="font-heading text-base font-bold text-foreground">{title}</h3>
          <p className="text-sm text-muted-foreground">{subtitle}</p>
        </div>
        {link && (
          <Link
            href={link.href}
            className="shrink-0 rounded-sm text-sm font-medium text-primary-text focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {link.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

function CardState({
  q,
  failed,
  children,
}: {
  q: { data: unknown; isPending: boolean; isError: boolean; refetch: () => unknown };
  failed: string;
  children: ReactNode;
}) {
  if (q.data === undefined && q.isPending) {
    return (
      <div role="status">
        <Skeleton aria-hidden className="h-40 w-full" />
        <span className="sr-only">Loading</span>
      </div>
    );
  }
  if (q.data === undefined && q.isError) {
    return (
      <StatePanel
        variant="error"
        title={failed}
        className="py-8"
        action={<Button variant="outline" size="sm" onClick={() => void q.refetch()}>Retry</Button>}
      />
    );
  }
  return <>{children}</>;
}

function AuditCard() {
  const audit = useAuditLog(AUDIT_PARAMS, true);
  return (
    <MiniCard
      title="Audit log"
      subtitle="Latest admin and sign-in events"
      link={{ href: "/admin/audit", label: "View all →" }}
    >
      <CardState q={audit} failed="Failed to load the audit log">
        {audit.data && audit.data.logs.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No events yet.</p>
        ) : (
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[22%]">Time</TableHead>
                <TableHead className="w-[22%]">User</TableHead>
                <TableHead className="w-[30%]">Action</TableHead>
                <TableHead className="w-[26%]">Target</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {audit.data?.logs.map((l, i) => (
                <TableRow key={`${l.timestamp}-${i}`}>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(l.timestamp).getTime() >= audit.data.dayStartMs
                      ? fmtTime(l.timestamp)
                      : fmtShortDate(l.timestamp)}
                  </TableCell>
                  <TableCell className="truncate font-code text-xs">{l.user}</TableCell>
                  <TableCell className="truncate font-code text-xs">{l.action}</TableCell>
                  <TableCell className="truncate font-code text-xs text-muted-foreground">{l.target_id ?? "–"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardState>
    </MiniCard>
  );
}

function PolicyCard() {
  const can = useCan();
  const policy = usePasswordPolicyQuery();
  const p = policy.data;
  const rows: [string, string][] = !p
    ? []
    : [
    ["Minimum length", `${p.min_length} characters`],
    ["Uppercase letter", p.require_upper ? "Required" : "Not required"],
    ["Lowercase letter", p.require_lower ? "Required" : "Not required"],
    ["Number", p.require_number ? "Required" : "Not required"],
    ["Symbol", p.require_symbol ? "Required" : "Not required"],
  ];
  return (
    <MiniCard
      title="Password policy"
      subtitle="Applies at the next password change"
      link={can("manage_policy") ? { href: "/admin/password-policy", label: "Edit" } : undefined}
    >
      <CardState q={policy} failed="Failed to load the password policy">
      <dl className="divide-y divide-border text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 py-2">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      </CardState>
    </MiniCard>
  );
}

function TokensCard() {
  const tokens = useApiTokens(true);
  const data = tokens.data;
  const newest = data?.tokens
    .filter((t) => t.status === "active")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 4);
  return (
    <MiniCard
      title="API tokens"
      subtitle="For SIEM pulls; a token never sees above its TLP"
      link={{ href: "/admin/tokens?new=1", label: "+ New token" }}
    >
      <CardState q={tokens} failed="Failed to load API tokens">
        {newest && newest.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">No active token.</p>
        ) : (
          <Table className="table-fixed">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[28%]">Name</TableHead>
                <TableHead className="w-[24%]">Token</TableHead>
                <TableHead className="w-[16%]">Max TLP</TableHead>
                <TableHead className="w-[16%]">Expires</TableHead>
                <TableHead className="w-[16%]">Last used</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {newest?.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="truncate text-xs">{t.name}</TableCell>
                  <TableCell className="truncate font-code text-xs text-muted-foreground">{t.token_prefix}…</TableCell>
                  <TableCell className="truncate font-code text-xs">{t.max_tlp}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{t.expires_at ? fmtShortDate(t.expires_at) : "–"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {t.last_used_at ? fmtAgo(t.last_used_at, data!.nowMs) : "–"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="pt-3 text-xs text-muted-foreground">
          Scopes: indicators:read · intel:read · hunt:read. The full token is shown once, at creation.
        </p>
      </CardState>
    </MiniCard>
  );
}

function KeysCard() {
  const secrets = useSecrets(true);
  const all = secrets.data?.providers ?? [];
  const shown = all.slice(0, 7);
  return (
    <MiniCard
      title="Third-party keys"
      subtitle={
        secrets.data
          ? `${all.length} providers · ${shown.length} shown · db overrides .env`
          : "Provider keys · db overrides .env"
      }
      link={{ href: "/admin/keys", label: "View all →" }}
    >
      <CardState q={secrets} failed="Failed to load third-party keys">
        <ul className="divide-y divide-border text-sm">
          {shown.map((p) => (
            <li key={p.key} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 truncate text-foreground">{p.label}</span>
              <span className="flex shrink-0 items-center gap-2">
                {p.source === "db" ? (
                  <Chip kind="status" value="ok">db</Chip>
                ) : p.source === "env" ? (
                  <Chip kind="flag" value="env">.env</Chip>
                ) : (
                  <Chip kind="status" value="watch">not set</Chip>
                )}
                {p.last_test_ok === false ? (
                  <span className="text-xs text-destructive-text">Test failed · {fmtAgo(p.last_test_at)}</span>
                ) : p.last_test_ok === true ? (
                  <span className="text-xs text-muted-foreground">ok · {fmtAgo(p.last_test_at)}</span>
                ) : (
                  <span className="text-xs text-muted-foreground">not tested</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </CardState>
    </MiniCard>
  );
}

/** Empat kartu ringkas; kartu tanpa permission-nya tidak dirender (dan querynya tidak dibuat). */
export function UsersMiniCards() {
  const can = useCan();
  const { user: me } = useAuth();
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {can("view_audit_log") && <AuditCard />}
      <PolicyCard />
      {can("manage_api_tokens") && <TokensCard />}
      {me?.role === "superadmin" && <KeysCard />}
    </div>
  );
}
