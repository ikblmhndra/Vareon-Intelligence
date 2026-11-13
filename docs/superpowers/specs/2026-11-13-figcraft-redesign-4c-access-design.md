# FigCraft redesign, sub-project 4c: Access (Login, session-expired dialog, Admin)

Date: 2026-11-13. Status: draft for review. Branch: `claude/figcraft-design-data`. Same one-PR release 0.8.16
(the CHANGELOG entry and the 0.8.16 runbooks are extended, no extra version bump).

## 1. Context and goal

Sub-projects 1, 2a, 2b, 3, 4a and 4b delivered the shell and the shared primitives in `apps/web/src/components/ui/`
(`StatTile`, `Chip`, `StatePanel`, `Notice` with a `destructive` tone, `SegmentedControl`, `Disclosure` with
`headingLevel`, `Sheet`, `NumberedPager`, `RowMenu`, `SearchInput`, `FilterSelect`, `SideNav`, `Table framed`),
`components/confirm-dialog.tsx::ConfirmDialog`, `PageHeader` with `kicker`, the browser-timezone formatters in
`lib/format.ts` (`fmtTime`, `fmtDateTime`, `fmtShortDate`, `fmtAgo`, `browserZoneName`),
`lib/use-page-title.ts::usePageTitle`, `lib/exec/query.ts::isClientError` and the `unwrap` / `noClientRetry` pair in
`lib/scrapers/queries.ts`. This spec is **4c: Login, the session-expired dialog and Admin**, the last part of
sub-project 4 (4a Content and 4b Operations are done).

FigCraft frames (light; dark variant in brackets): Login / L1 Split 2976 (3117), Login / States 47485 (47580),
Admin / A1 4380 (4894), Admin / Sub-tabs 47691 (48466), and the session-expired dialog inside Dashboard / States
32816 (33283; state 32948, dialog 32962). There is no frame for any Admin dialog, any Admin loading / empty /
error / no-access state, the Login pending, network, 502 and SSO states, or the reload path of a forced password
change.

Today all three are pre-redesign. Login has Indonesian copy, shows the raw API `detail` for every failure and
loses the HTTP status. A forced password change is a bare dialog rendered instead of the shell. A 401 in the
middle of a session silently replaces the page with `/login`. Admin is one route, `/admin/users`, stacking seven
`Card` sections.

Goal: deliver the **full mockup, keep every existing feature reachable** (L1-L10, A1-A23 in the gap inventory) and
add the three small backend items the mockup needs (B-A1, B-A2, B-L1). Backend lands first, then Login and session
handling, then Admin. The inventory behind this spec (`.superpowers/brainstorm/sp4-inventory.md`, not committed)
lists every frame element and its source; where they differ, this spec wins.

## 2. Decisions (binding, from the user)

Scope
- **S1** 4c covers `/login`, the forced password change, the mid-session 401 handling, and `/admin/*`.
- **S2** Full mockup; every pre-redesign feature stays reachable, re-homed where the mockup has no place (maps in
  6.1 and 6.4).
- **S3** Release stays 0.8.16, one PR; `CHANGELOG.md` (Indonesian), `docs/prod-upgrade/0.8.16.md` and
  `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` are extended. No migration, no `.env` key.
- **S4** The inventory decisions that shape 4c are accepted:

| Id | Decision |
|---|---|
| D2 | Real routes `/admin/users`, `/roles`, `/password-policy`, `/clients`, `/tokens`, `/audit`, `/keys`; `/admin` redirects to users; `SideNav` gains group headings; the masthead item keeps `match: "/admin"`. |
| D3 | Users page as drawn: four tiles, the users table, and the audit, policy, token and key mini-cards, each permission-gated and fetched on its own. |
| D4 | Reset password keeps the admin-typed, policy-validated password and now sets `force_pw_change` (B-A1); "Reset pending" derives from the flag. |
| D5 | Forced change stays on `/login` and reuses the typed password as `current_password`; then an automatic sign-in with the new password. The (app)-layout dialog stays as the reload fallback, in English. |
| D6 | A dialog over the current page replaces the hard redirect on a mid-session 401; "Sign in again" returns to the same place. |
| D7 | Login copy in English; signal cards static and `aria-hidden`; version footer from the web build version. |
| D8 | 429 sends `Retry-After` (B-L1); the button is disabled with a countdown; fallback one minute. |
| D9 | Audit export is a client-side CSV of the filtered rows, at most 5,000, hidden without `view_audit_log`. |
| D10 | Audit filters stay free text (no facets endpoint, B-A3 declined). |
| D11 | "Your session" card shows `signed_in_at` from `/auth/me` (B-A2); the IP is dropped. |
| D12 | Roles is a read-only matrix over every permission; "+ New role" stays; Delete moves to a menu on a non-system column. |
| D13 | Delete client and Revoke token stay as row-menu actions. |
| D14 | Third-party keys rows and banner as drawn; Edit and Revert stay dialogs because they carry the password. |
| D15 | Every Admin dialog uses the shared dialog anatomy; `StatePanel` covers no-access, error and empty. |
| D16 | Admin kicker "ADMINISTRATION · {ROLE}", derived from the signed-in role. |
| D32 | Browser time zone everywhere, with `browserZoneName()` where a zone is printed. |

Declined: B-A3 (audit facets) and B-A4 (server CSV). No contract regeneration is expected in 4c (section 5).

Choices this spec makes that the user did not spell out (each is flagged for review):
- **P1** The Users status control starts on "All", so nobody is hidden on first view.
- **P2** Clients keeps "CREATED" as a sixth column (a tooltip is not reachable by keyboard or touch).
- **P3** The new-token banner prints the token masked with a "Show" toggle; it reveals itself when the clipboard
  call fails.
- **P4** The forced-change screen has a "Cancel and sign out" link (the mockup has no way out).
- **P5** Right after sign-in the web fills `signed_in_at` from the browser clock; the next `/auth/me` replaces it
  with the token's `iat`. The login response schema is not touched.
- **P6** Fixed English copy for the Login failures that have no frame (network, 5xx, SSO 400, anything else).
- **P7** "Make every user change their password" asks for confirmation and says who is flagged (C12).
- **P8** The minimum-length field refuses values under 8 (the API accepts 4).
- **P9** Clients is listed for `manage_users` or `manage_clients`; a user with only `manage_users` (the admin
  role) now sees the table read-only (C11).
- **P10** The automatic sign-in waits 1,200 ms after the password change (section 9, "re-login race").
- **P11** A full page load with a dead cookie also keeps its place (`/login?redirect=`), and `proxy.ts` includes
  the query string in `redirect`.
- **P12** After "Close" a banner stays on the page, and the web stops sending API requests until the user signs in
  again.
- **P13** The session-expired body text (C6).
- **P14** Add user picks clients from a checkbox list; a non-superadmin sees only their own clients (the API
  refuses the others).
- **P15** A superadmin's row has no menu for a viewer who is not superadmin (the API returns 403).
- **P16** Every Admin page renders the same header (h1 "Admin"); page actions sit in the header on Users and next
  to the page heading elsewhere.
- **P17** Users page size 10; mini-card row limits 6 (audit), 4 (tokens), 7 (keys).
- **P18** Audit page size is fixed at 50; the CSV carries the timestamp in UTC.
- **P19** The version footer reads `NEXT_PUBLIC_APP_VERSION`, inlined at build time by `next.config.ts` from
  `package.json`. It is not a `.env` key.
- **P20** The MUST CHANGE PASSWORD tile sub line (C5).

## 3. Conflicts between inputs, and how they are resolved

- **C1 Language.** Login and the forced dialog are Indonesian; the mockup and the rest of the app are English.
  English (D7).
- **C2 401 text.** Banner "Username or password is incorrect"; API `detail` "Invalid credentials". The web maps the
  **status** to fixed copy and never prints `detail` on `/login` (table in 6.1).
- **C3 429 wait.** Banner "Wait 1 minute"; the API sends no `Retry-After`. B-L1 adds it; the copy prints the real
  number and falls back to "1 minute". The limiter is 10 attempts per 60 s per IP, which matches the 401 banner's
  "After 10 tries in a minute".
- **C4 Forced change has no current-password field**, but `POST /auth/change-password` requires one and then
  revokes every session. The screen sends the password typed at sign-in and signs in again afterwards (6.1). The
  reload fallback cannot know that password, so it keeps the field.
- **C5 "An administrator reset your password."** After B-A1 a reset does flag the user, but the policy toggle
  `force_all_change` flags users too, and the login response only carries a boolean. One wording that is true in
  both cases: "Your account needs a new password, after an administrator reset or a policy change. Pick one to
  continue." The tile sub line "set by an admin reset" becomes "must choose a new one at next sign-in" (P20). The
  tile's node name "after 5 failed sign-ins" (inventory C27) describes a lockout that does not exist and is
  ignored.
- **C6 Session length.** Mockup "sessions end after 12 hours or when an admin signs you out";
  `auth.jwt_expire_min` is 480 and configurable, and nothing "signs a user out": tokens are revoked by a password
  change or reset, a role or client change, or five wrong password confirmations. Body (P13): "For security,
  sessions end automatically, or when your password, role or client access changes. Sign in again to continue on
  this page."
- **C7 Session expired.** Mockup: dialog over the page, return to the same place. Code: hard redirect with no
  message and no `redirect`. The mockup wins (6.2).
- **C8 Time zone.** Mockup "TIME (WIB)" and a bare "Signed in 09:12"; convention is the browser zone (D32): "TIME
  ({browserZoneName()})" and "Signed in {fmtDateTime} {browserZoneName()}".
- **C9 Who sees Admin.** Kicker "ADMINISTRATION · SUPERADMIN" is sample text; the page gate is any of six
  permissions. The kicker prints the viewer's role in upper case.
- **C10 Side-nav badges.** The mockup shows counts (Users 24, Roles 5, …). They would cost five queries on every
  Admin page, the reason the masthead dropped its counts (inventory C31). No badges.
- **C11 Clients read vs write.** `GET /api/clients` needs `manage_users`; create, edit and delete need
  `manage_clients`. Today the section is shown only for `manage_clients`, so the admin role cannot see a list it is
  allowed to read, and a role with only `manage_clients` sees a table that fails. Resolved in 6.5 (P9).
- **C12 "Make every user change their password at next sign-in."** `flag_force_pw_change_all_non_admin` flags
  every account whose role is not exactly `admin`, superadmins included, and revokes no session. The label stays;
  the help text and the confirm say exactly that (6.5).
- **C13 Minimum length.** Mockup help "8 or more"; `PolicySettings.min_length` accepts 4-128. The field enforces
  8-128 (P8); a stored value under 8 is shown and must be raised before Save.
- **C14 Roles matrix.** Mockup columns ADMIN / ANALYST / SOC / EXEC / CLIENT_VIEWER, 12 rows of "29", its own
  descriptions, ticks that look editable. Code: system roles `superadmin`, `admin`, `analyst`; 30 permissions with
  API descriptions; no update endpoint. Columns come from `GET /api/roles`, rows and ALLOWS text from
  `GET /api/roles/permissions`, the count in the footnote is the length of that list, cells are not interactive
  (D12).
- **C15 Audit sample names.** A1 prints dotted actions (`secret.update`); real ones are snake_case. The table
  prints the API value.
- **C16 Token display.** Mockup `vrn_live_••••…7Qx2` and prefix `vrn_9f3a…`; a real token is `vrn_` plus 43
  URL-safe characters and `token_prefix` is its first 12. The banner masks as "{first 8}••••{last 4}"; the PREFIX
  column prints "{token_prefix}…". "Store it in Splunk's secret store." becomes "Store it in the consumer's secret
  store."
- **C17 Token scopes and statuses.** Footnote "articles:read · iocs:read · cves:read" is sample; the real scopes
  are `indicators:read`, `intel:read`, `hunt:read`. STATUS has three values, `active`, `expired`, `revoked`, not
  the mockup's two.
- **C18 Key edit form.** The mockup edits inline without a password; the API requires `current_password` on
  every set and clear. Dialogs stay (D14); the mockup's button label "Save and test" is used because `PUT` probes
  the vendor before saving.
- **C19 A1 duplicates** the policy, token, key and audit summaries that have their own pages. Kept (D3); each
  mini-card links to its page and shares that page's query key.
- **C20 Header actions.** A1 puts "Export audit log" and "+ Add user" in the page header, the sub-tab frames put
  "+ New role" next to a crumb. Resolved by `AdminFrame` (6.3, P16).
- **C21 Clients "–".** The mockup prints "–" in the default row; USERS always prints the computed number.
- **C22 SSO text.** API 400 `detail` "This account uses SSO. Please sign in via the SSO button."; the web has no
  SSO button. Fixed copy instead (6.1, P6).

## 4. Backend

Conventions. Three small changes in `routers/auth.py`, `rate_limit.py` and `cti_core` `AsyncUserRepo`. No new
route, so `tests/unit/test_route_permissions.py` is untouched. Comments and docstrings in Indonesian, matching
the files. None of the three changes a `response_model`.

### 4.1 B-A1 An admin reset forces a password change
- **Contract.** No schema change. `POST /api/auth/users/{username}/reset-password` still returns `{"ok": true}`.
  Behaviour: after it, the target has `force_pw_change = true`; `GET /api/auth/users` reports it, the next login
  returns `force_pw_change: true` with an `fpc` token, and `deps.get_current_user` answers 403 "Password change
  required" on everything outside `_ALLOWED_WHILE_FORCED` until `POST /api/auth/change-password` succeeds.
- **Logic.** `AsyncUserRepo.reset_password(self, username: str, password_hash: str, *, force_change: bool) -> bool`
  sets `user.force_pw_change = force_change`. The argument is keyword-only and has no default, so each caller
  states its intent. `change_password` passes `force_change=False` (a self change ends the forced state, as
  today); `reset_user_password` passes `force_change=True`. Token revocation, the SSO 400, policy validation, the
  superadmin guard and the audit row (`reset_password`) are unchanged. The docstring records why: the admin knows
  the password they typed.
- **Not changed.** `POST /api/auth/users` (Add user) does not flag the new account; `flag_force_pw_change_all_non_admin`
  keeps its filter. An admin who resets their own account through this endpoint is flagged like anyone else; the
  self-service Change Password dialog is the path that does not flag.
- **Tests.** `tests/integration/test_auth_repositories.py`: `test_reset_password_clears_force_pw_change` is
  replaced by `test_reset_password_self_change_clears_force_pw_change` (`force_change=False` on a flagged user →
  False) and `test_reset_password_admin_reset_sets_force_pw_change` (`force_change=True` on an unflagged user →
  True, hash replaced). `tests/integration/test_auth_router_snapshot.py`: `test_reset_user_password` additionally
  logs in as the target with the new password and asserts `force_pw_change is True` in the login body;
  new `test_change_password_clears_force_pw_change` (reset, login, `change-password` with the login token → 200,
  then a second login returns `force_pw_change: false`); new `test_forced_user_is_blocked_until_change` (the `fpc`
  token gets 403 with `detail` "Password change required" on `GET /api/auth/users`, and 200 on
  `GET /api/auth/policy` and `GET /api/auth/me`).

### 4.2 B-A2 `/auth/me` reports when the session started
- **Contract.** `GET /api/auth/me` (untyped dict) gains `signed_in_at: str | None`, the token's `iat` as ISO 8601
  UTC (`2026-11-13T02:12:00+00:00`). `None` when the claim is missing or not an integer. No other key changes.
- **Logic.** `me` takes `authorization: str | None = Header(None)` (as `logout` does), reads
  `decode_token(authorization.split(" ", 1)[1]).get("iat")` and converts with
  `datetime.datetime.fromtimestamp(iat, datetime.UTC).isoformat()`. `require_auth` has already accepted the header,
  so the decode cannot fail. `AuthedUser` is not extended: `iat` would then leak into every `{**user}`.
- **Meaning.** The API issues no refresh token, so `iat` is the sign-in time of this session.
- **Tests.** `test_auth_router_snapshot.py`: `_NORMALIZE` gains `r"(.*\.)?signed_in_at$": (str,)` and `test_me`
  uses the matcher; run with `--snapshot-update` for this file only and review the diff (one new key). New
  `test_me_signed_in_at_matches_token_iat`: decode the token from `auth_header()` and compare.

### 4.3 B-L1 Login 429 sends `Retry-After`
- **Contract.** The 429 of `POST /api/auth/login` carries the header `Retry-After: {seconds}`, an integer from 1
  to 60. Body unchanged (`"Too many login attempts. Try again in a minute."`).
- **Logic.** `rate_limit.py::retry_after_seconds(redis, key, *, window_seconds=60) -> int`: `ttl = await
  redis.ttl(f"ratelimit:{key}")`; return `ttl` when `1 <= ttl <= window_seconds`, else `window_seconds` (Redis
  answers -2 for a missing key and -1 for a key without expiry). `login` raises `HTTPException(429, detail=…,
  headers={"Retry-After": str(await retry_after_seconds(redis, f"login:{ip}"))})`. `is_rate_limited` is unchanged
  (its other callers in `routers/secrets.py` are not touched). The window is fixed: the key is created with a 60 s
  expiry on the first attempt and later attempts only increment it, so the TTL is the exact time until the
  counter resets, and attempts made while locked do not extend it.
- **Web.** `app/api/auth/login/route.ts` copies `Retry-After` from the upstream response to its own failure
  response (6.1).
- **Tests.** `tests/unit/test_auth_security.py::test_retry_after_seconds_clamps_ttl` with a stub Redis whose `ttl`
  returns -2, -1, 0, 37 and 999 → 60, 60, 60, 37, 60. `test_auth_router_snapshot.py::test_login_rate_limited_sends_retry_after`:
  eleven posts with a wrong password; the first ten are 401, the eleventh is 429 with an integer `Retry-After`
  between 1 and 60 (the conftest `_FakeRedis` already implements `ttl`).

### 4.4 Documentation touched
- `CHANGELOG.md`, 0.8.16 entry (Indonesian). *Ditambahkan:* halaman Admin dipecah menjadi tujuh rute dengan
  navigasi samping (Users, Roles, Password policy, Clients, API tokens, Audit log, Third-party keys), ringkasan di
  halaman Users, ekspor CSV audit log; dialog "Your session has ended" menggantikan pengalihan diam-diam ke
  `/login` saat sesi berakhir; login 429 mengirim `Retry-After` dan tombol menghitung mundur; `/api/auth/me`
  mengirim `signed_in_at`. *Diubah:* reset password oleh admin kini mewajibkan pengguna itu memilih password baru
  saat login berikutnya (`force_pw_change`); halaman login berbahasa Inggris dan tidak lagi menampilkan pesan
  mentah dari API; ganti password wajib dilakukan langsung di halaman login. A "Catatan 0.8.16 (Access)" line:
  tanpa migrasi, tanpa key `.env` baru; pengguna yang sudah ada tidak terpengaruh.
- `docs/prod-upgrade/0.8.16.md` and `docs/PROD_UPGRADE_0.8.11_TO_0.8.16.md` (English). *Migrations:* none from 4c.
  *Settings:* none. *Behaviour change:* an admin password reset now flags the account; the user must choose a new
  password at the next sign-in and gets 403 "Password change required" from every other endpoint until then.
  **Existing users are unaffected**: no row is updated by the deploy, only resets made after it set the flag. Any
  account that a script signs in with (username and password) must not be reset from the Admin page without
  completing the change by hand afterwards. *Contract:* `GET /api/auth/me` adds `signed_in_at`; login 429 adds
  `Retry-After`; `docs/openapi.json` is unchanged. *URLs:* `/admin/users` still works; the other sections moved to
  their own routes. *Post-deploy check:* sign in, open `/admin/users` and confirm the "Your session" card shows a
  sign-in time; reset a test account and confirm its STATUS reads "Reset pending". *Rollback:* image rollback only;
  flags set while 0.8.16 ran stay set and the old forced dialog still handles them.
- `docs/ARCHITECTURE.md` is not changed (it does not describe the web session handling).

## 5. Migration summary

None. 4c adds no table, no column, no index and no `Settings` field, so `.env.example` and `.env.prod.template`
are unchanged and the Alembic head stays `c4e8a1f2b9d6`. `NEXT_PUBLIC_APP_VERSION` is set inside `next.config.ts`
at build time and appears in no env file. Contract: `uv run python tools/export_openapi.py` must produce no diff;
if it does, the change touched a schema by mistake. One syrupy snapshot changes (`test_me`).

## 6. UI

Global rules (as 2b to 4b). Desktop 1440 first (content width 1328). Multi-column rows collapse to one column below
1024 px (`lg:`). No `backdrop-blur`. Colours only through tokens; text on tints uses `text-X-text`. Focus ring
`focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`.
Minimum text 11 px (`text-2xs`). Base UI, not Radix. Usernames in tables, client ids, permission keys, role names,
token prefixes, audit actions and key fragments in `font-code` (`font-mono` is not monospace here; the current
`font-mono` uses in `components/admin/*` and `change-password-dialog.tsx` are replaced). The mockup's wide
separators are rendered " · ". Fixed copy below is verbatim from the frames unless a C-rule says otherwise. All
times are browser zone through `lib/format.ts`; the raw `split("T")` / `replace("T", " ")` strings and
`formatWhen` in the admin sections are removed.

Chips. Roles: `Chip kind="flag"` with the role name; `superadmin` uses the warning tint it has today. User status:
"Active" → `kind="status" value="ok"`, "Reset pending" → `value="watch"`, "Never signed in" → neutral flag. Token
status: `active` → ok, `expired` → watch, `revoked` → action. Key source: `db` → "db · overrides .env" (ok),
`env` → ".env" (neutral), `unset` → "not set" (watch).

Constraints carried over from earlier sub-projects (each is a review checklist item):
1. A nested layout with a string `metadata.title` resets the root title template. `app/(app)/admin/layout.tsx`
   uses `{ default: "Admin", template: "%s · ${PLATFORM_NAME}" }` and stops rendering `PageHeader`; each page calls
   `usePageTitle("{Page} · Admin")`. `/login` keeps its string title and calls `usePageTitle("Choose a new
   password")` on the forced-change screen.
2. Check `response.ok`, not just `if (error)`: every query and mutation in `components/admin/*`, the change-password
   call and the audit export go through `unwrap` (`lib/scrapers/queries.ts`), which throws `new Error(detail ??
   fallback, { cause: response.status })`. The hooks in `components/admin/hooks.ts` that throw `HTTP {status}`
   today move to it. An empty-body 502 must not read as success.
3. Do not retry 4xx and do not poll after one: every query uses `retry: noClientRetry`. No Admin query sets
   `refetchInterval`; if one is added later it must return `false` while `isClientError(query.state.error)`.
4. No interactive element nested inside another. Table rows have no `onClick`; row actions live in a `RowMenu`
   cell or are sibling buttons. Mini-card rows are plain text; the card's link is in its header. The signal cards
   on `/login` contain no control.
5. A `table-fixed` table needs explicit column widths (given per table below).
6. `SelectItem` children are a single string and every `Select` passes `items` (role select, TLP, expiry, the
   provider choice fields in the key dialog, the role and client filters through `FilterSelect`).
7. Gate on the real backend permission, never a stricter or looser one. The table in 6.3 is copied from the
   router dependencies and is the only source for `useCan` calls; Third-party keys is `user.role === "superadmin"`
   because the API uses `require_superadmin`.
8. Theme tokens only; every dialog is checked in light and dark.
9. Never `router.replace` to the URL that is already current. The only Admin URL state is `?new=1` on
   `/admin/tokens`, removed once after the dialog opens; filters and tabs are component state.
10. No `Date.now()` in render. "Now" for "signed in this week" and "expires in N days" is read inside the
    `queryFn` and returned with the data; the 429 countdown stores its deadline in the submit handler and ticks in
    an effect; the CSV file name is built in the click handler.
11. Seed and fixture data use the API's `Literal` values exactly: key `source` `db | env | unset`, test `status`
    `OK | FAIL | SKIP | NOTE`, token `status` `active | expired | revoked`, TLP `clear | green | amber |
    amber+strict | red`, scopes `indicators:read | intel:read | hunt:read`. TypeScript unions in the admin
    components use the generated schema types, not hand-written strings.
12. Secrets never leave memory: passwords and the new API token are held in component state or a closure only.
    They are never written to `localStorage`, `sessionStorage`, a cookie, the URL, the query cache or mutation
    `variables` (mutation functions read state from the closure, as `change-password-dialog.tsx` does today; the
    token mutation keeps `gcTime: 0`).
13. Every pre-redesign feature stays reachable; the PR carries a checklist L1-L10 and A1-A23 (tables in 6.1, 6.4).

### 6.1 Login (frames 2976, 47485)

- **Files.** `app/login/page.tsx` (page, sign-in form, forced-change form), `app/api/auth/login/route.ts`,
  `components/providers/auth-provider.tsx`, `lib/auth/password-policy.ts`, `next.config.ts` (P19).
- **`login()` contract** (`AuthContextValue`). Returns `{ ok: true; forcePwChange: boolean }` or `{ ok: false;
  status: number; retryAfterS: number | null }`. `status` is the HTTP status of `/api/auth/login`; a thrown
  `fetch` still rejects, as today. `retryAfterS` is `Retry-After` parsed as a base-10 integer and kept only when
  it is between 1 and 3600, else `null`. On success `login()` first calls `queryClient.cancelQueries({ queryKey:
  ME_QUERY_KEY })` (an in-flight `/api/auth/me` made with the old cookie must not overwrite the new user), then
  `setQueryData` with the response plus `signed_in_at: new Date().toISOString()` when the response has none (P5),
  then `resetSessionExpired()` (6.2). `detail` is no longer returned: nothing on `/login` prints it (C2).
- **Route handler.** On an upstream failure it returns the payload and status as today and adds the upstream
  `Retry-After` header when present. Success path unchanged.
- **Layout.** `main` is `grid min-h-dvh md:grid-cols-2`. Below `md` the brand panel is a short band with the
  wordmark and the headline; the paragraph, signal cards, coordinates line and panel footer are hidden (L10).
- **Brand panel** (`bg-hero`, hero tokens only). `WorldDots` as today (`dynamic`, `ssr: false`, `aria-hidden`).
  Top: `BrandMark` and `PLATFORM_NAME`, under it "THREAT INTELLIGENCE PLATFORM". A row with "06°12′S 106°49′E" and
  "APAC COVERAGE" preceded by a live dot (`aria-hidden`; its pulse is disabled under `prefers-reduced-motion`).
  `<h1>` "Threat intelligence, briefed daily." Paragraph "News, ransomware, CVEs and threat actors from across
  APAC, ranked by what matters to your organisation." Footer "Vareon Intelligence" (`PLATFORM_NAME`). Three signal
  cards, static, inside one `aria-hidden="true"` container, absolutely placed over the map as drawn: "CVE-2026-0119"
  / "KEV · CVSS 9.8" / "2h ago"; "RANSOMWARE" / "New victim · PH" / "5h ago"; "UNC5221" / "Active campaign" /
  "today". They are decoration, not data; the three hero bullets of today are removed (replaced by the
  paragraph).
- **Form panel, sign-in stage.** Masthead line "{PLATFORM_NAME} · Authorized users only". Kicker "SIGN IN",
  `<h2>` "Welcome back", "Use your Vareon account." Field "Username" (`autoComplete="username"`, required).
  Field "Password" (`autoComplete="current-password"`, required) with a text button "Show" / "Hide" inside the
  field's right edge (`type="button"`, `aria-pressed`, `aria-controls` the input; it switches the input `type`
  between `password` and `text`). Primary button "Sign in", full width; while pending "Signing in…" and disabled.
  Below: "Forgot your password? Contact your platform admin." Panel footer: "Sign-in activity is logged." and
  "{PLATFORM_NAME} · v{NEXT_PUBLIC_APP_VERSION}".
- **Failures.** The banner is a `Notice` inside a `role="alert"` wrapper, above the fields. Both inputs keep their
  values; focus moves to the password field. A new submit clears the banner.

| Case | Tone | Title | Body |
|---|---|---|---|
| 401 | destructive | "Username or password is incorrect" | "Check both and try again. After 10 tries in a minute, sign-in pauses briefly." |
| 429 | warning | "Too many sign-in attempts" | "Wait {wait} before trying again. Your administrator can reset the password if you forgot it." |
| 400 | warning | "This account signs in with SSO" | "Password sign-in is not available for it. Contact your platform admin." |
| 502 and any other 5xx | destructive | "The sign-in service is not responding" | "Try again in a moment." |
| `fetch` rejects | destructive | "Cannot reach the server" | "Check your connection and try again." |
| any other status | destructive | "Sign-in failed" | "Try again. If it keeps failing, contact your platform admin." |

- **429 countdown.** `seconds = retryAfterS ?? 60`. `{wait}` is "1 minute" when `seconds` is 60, else "{seconds}
  seconds"; it is the value at the moment of the response and does not tick (the alert is announced once). The
  submit handler stores `deadline = Date.now() + seconds * 1000`; an effect ticks once a second and keeps
  `remaining` in state. While `remaining > 0` the button is disabled and reads "Try again in {remaining} s"; at 0
  the banner is removed and the button reads "Sign in". The inputs stay editable throughout.
- **Success.** `forcePwChange` false → `router.push(safeRedirect(searchParams.get("redirect")))`. `safeRedirect`
  is unchanged: only a path starting with one `/` and not `//` or `/\` is accepted, anything else becomes
  `/dashboard` (L4). `forcePwChange` true → the form panel switches to the forced-change stage; the URL does not
  change.
- **Form panel, forced-change stage** (D5, frame 47485). Kicker "SIGN IN", `<h2>` "Choose a new password", text per
  C5. Fields "New password" and "Confirm new password" (`autoComplete="new-password"`, each with its own "Show"
  toggle). Under the first, the rule list from `passwordRules(value, policy)` (6.7): one line per active rule,
  "✓" when met and "○" when not (the glyph is `aria-hidden`; each line carries visually hidden "met" / "not met"),
  wording "At least {min_length} characters", "An uppercase letter", "A lowercase letter", "A number", "A
  symbol". The policy comes from `usePasswordPolicy()` (`GET /api/auth/policy`, public and allowed while forced).
  Under the second field, when it is not empty and differs: "Passwords do not match." (`role="alert"`,
  `aria-describedby` on the input). Primary button "Save and continue", disabled until every rule is met and the
  two values are equal. Link button "Cancel and sign out" (P4): calls `logout(redirect)` and returns to the sign-in
  stage with both stages' fields cleared. Every `logout` call made on `/login` passes the current `redirect`
  parameter when there is one (6.2), so the destination survives.
- **Forced-change submit**, in this order:
  1. Button reads "Saving…". `api.POST("/api/auth/change-password", { body: { current_password, new_password } })`
     where `current_password` is the password typed at sign-in, still held in the page's state.
  2. On 200: the sign-in password state is cleared. Button reads "Signing you in…". Wait 1,200 ms (P10), then
     `login(username, newPassword)`.
  3. `login` ok → clear the new-password state and `router.push(safeRedirect(…))`, whatever `forcePwChange` says
     (if the flag were still set, the (app)-layout fallback takes over; no loop on `/login`).
  4. `login` not ok → back to the sign-in stage, username kept, password empty, with a neutral `Notice` "Password
     changed" / "Sign in with your new password." If the status is 429 the countdown above also applies.
  Failures of step 1 (the stage stays, fields kept, except where noted):

| Status | Shown |
|---|---|
| 422 | destructive `Notice` "That password does not meet the policy" with the API `detail` as body ("Password missing: …"); the rule list is the usual guard, this covers a policy changed in between |
| 400 | back to the sign-in stage after `logout()`, with "Sign in again" / "Your sign-in password changed while this page was open." |
| 401 | back to the sign-in stage (the cookie is already cleared by 6.2), with "Your session has ended" / "Sign in again to choose a new password." |
| 429 | destructive `Notice` "Too many attempts" / "Try again in a few minutes." |
| other, or `fetch` rejects | destructive `Notice` "Could not save the password" / "Try again." |

- **Password lifetime** (constraint 12). The sign-in password lives in the page's `useState` from typing until
  step 2, a cancel, a failed-to-sign-in return, or unmount, whichever comes first. The new password lives until
  step 3 or 4. Neither is passed as mutation `variables`.
- **Reload fallback** (L7). A reload of `/login` with the `fpc` cookie is redirected to `/dashboard` by `proxy.ts`;
  `app/(app)/layout.tsx` then renders `ChangePasswordDialog forced` instead of the shell, as today. Restyled
  (6.6): title "Choose a new password", the C5 sentence, fields "Current password", "New password" with the rule
  list, footer "Sign out" and "Save". On success it calls `logout()` and the user signs in by hand (it has no
  redirect to return to).
- **Feature map.**

| # | Pre-redesign feature | New home |
|---|---|---|
| L1 | Username / password sign-in with a pending state | Sign-in stage; "Signing in…" |
| L2 | Server error shown in an alert (raw `detail`) | Failure table by status; `detail` is no longer printed |
| L3 | Network failure message | "Cannot reach the server" row |
| L4 | `?redirect=` with the open-redirect guard | Unchanged `safeRedirect`; also used after the forced change |
| L5 | Hero panel with map | Brand panel (bullets replaced by the paragraph and signal cards) |
| L6 | Cookie guard and already-signed-in redirect | `proxy.ts`, unchanged except that `redirect` includes the query (P11) |
| L7 | Forced password change (blocking dialog, current + new password, Sign out) | Forced-change stage on `/login`; the same dialog, restyled, on reload |
| L8 | 401 mid-session → silent hard redirect | Session-expired dialog (6.2) |
| L9 | `force_pw_change` blocks every API call except change-password | Unchanged (`deps.py`) |
| L10 | Mobile: hero details hidden below `md` | Same rule, applied to the new panel content |

### 6.2 Session expired (frame 32816, D6)

- **Store.** `lib/auth/session-expired.ts`, a module-level store read with `useSyncExternalStore`: state `active |
  expired | signing-out`. `markSessionExpired()` moves `active` → `expired` and does nothing from any other state.
  `markSigningOut()` sets `signing-out`. `resetSessionExpired()` sets `active`. `useSessionState()` returns the
  state.
- **`lib/api/client.ts`.**
  - `createClient` gets `fetch: guardedFetch`. While the state is not `active`, `guardedFetch` does not touch the
    network and resolves to `new Response(JSON.stringify({ detail: "Your session has ended. Sign in again." }),
    { status: 401, headers: { "content-type": "application/json" } })`. So after the first 401 no further request
    reaches the API, polling pages stop producing traffic, and a write fails with that sentence in its usual
    error toast.
  - `onResponse`: on a 401 while the state is `active`, call `markSessionExpired()` synchronously, then `await
    fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined)` (kept: it denylists the token and
    clears the cookie; without it `proxy.ts` bounces `/login` back to `/dashboard`). No navigation. In any other
    state `onResponse` returns the response untouched. The `sessionExpiredHandled` flag and the
    `window.location.href` assignment are removed.
- **`AuthProvider`.** The `/api/auth/me` query gets `enabled: state === "active"`, so a window-focus refetch after
  the cookie is cleared cannot turn the user into `null` and unmount the page under the dialog. `logout()` calls
  `markSigningOut()` first (a 401 that lands during a deliberate sign-out opens no dialog) and accepts an optional
  `redirectTo: string`: when given it pushes `/login?redirect=${encodeURIComponent(redirectTo)}`, else `/login`.
- **Host.** `components/session-expired.tsx::SessionExpiredHost`, rendered by `app/(app)/layout.tsx` inside
  `AppShell`, before `children`. It is not mounted on `/login`.
  - When the state becomes `expired` it opens a `Dialog` (480 wide, `role="alertdialog"`): title "Your session has
    ended", description per C6, footer "Close" (outline) and "Sign in again" (primary, initial focus). The dialog
    opens once per expiry: later 401s cannot reopen it because the state no longer changes and the open flag is
    set only on the transition.
  - **"Sign in again"**: re-sends `POST /api/auth/logout` (idempotent; covers a first attempt that failed), then
    `window.location.assign("/login?redirect=" + encodeURIComponent(location.pathname + location.search))`. A full
    load on purpose: it discards client state and resets the store.
  - **"Close"**, Escape and a click outside: the dialog closes and focus returns to the page. The page stays as it
    was, so the user can read or copy what is on screen; nothing on it can load or save. While the state is
    `expired` and the dialog is closed, the host renders a `Notice tone="warning"` at the top of the content:
    "Your session has ended" / "Nothing on this page can load or save until you sign in again." with the action
    button "Sign in again" (same handler). The banner cannot be dismissed.
- **Full page loads** (P11). The interceptor only sees `api` calls. On a full load with a dead cookie `proxy.ts`
  lets the request through, `/api/auth/me` answers 401, the status becomes `unauthenticated` and
  `app/(app)/layout.tsx` calls `logout(location.pathname + location.search)`: the user lands on `/login?redirect=…`
  with no dialog, because there is no page worth keeping. That effect does nothing while the store is
  `signing-out`: a deliberate sign-out also makes the status `unauthenticated`, and it must end on plain `/login`,
  not carry the previous user's path. A load without any cookie is redirected by `proxy.ts`
  itself, which now sets `redirect` to `pathname + search`.
- **Not covered.** Direct `fetch` calls that bypass `api` (file downloads in `lib/csv.ts`) report their own error;
  the next `api` call opens the dialog.

### 6.3 Admin shell (frames 4380, 47691)

- **Routes.** `app/(app)/admin/page.tsx` → `redirect("/admin/users")`. Seven pages, each a client view wrapped in
  `AdminFrame`: `users`, `roles`, `password-policy`, `clients`, `tokens`, `audit`, `keys`. `nav-items.ts` is
  unchanged (`href: "/admin/users"`, `match: "/admin"`).
- **`components/admin/admin-frame.tsx::AdminFrame`** (`{ page, headerActions?, children }`):
  - **Page gate** (A22): passes when `useCan` is true for at least one of `manage_users`, `manage_roles`,
    `manage_policy`, `view_audit_log`, `manage_clients`, `manage_api_tokens` (the list of today, unchanged).
    Otherwise it renders only `StatePanel no-access` "Admin access required" / "Your role ({role}) cannot open
    this page."
  - `PageHeader` kicker "ADMINISTRATION · {ROLE}" (`user.role.toUpperCase()`, C9), h1 "Admin", description
    "People, roles, tenants and keys. Every change here is written to the audit log.", `actions` =
    `headerActions`.
  - Below, a two-column grid (`lg:grid-cols-[240px_1fr]`, one column below `lg` with the nav first): left the
    `SideNav` and the session card, right `children`.
  - **Side nav** (`aria-label="Admin sections"`), groups and gates:

| Group | Item | Route | Listed when | Reads | Writes |
|---|---|---|---|---|---|
| ACCESS | Users | `/admin/users` | always (inside the page gate) | `GET /auth/users`: `manage_users` | add, role, clients: `manage_users`; reset: `reset_password` |
| ACCESS | Roles | `/admin/roles` | always | `GET /roles`, `/roles/permissions`: any signed-in user | create, delete: `manage_roles` |
| ACCESS | Password policy | `/admin/password-policy` | `manage_policy` | `GET /auth/policy`: public | `PUT`: `manage_policy` |
| TENANTS | Clients | `/admin/clients` | `manage_users` or `manage_clients` | `GET /clients`: `manage_users` | create, edit, delete: `manage_clients` |
| TENANTS | API tokens | `/admin/tokens` | `manage_api_tokens` | `manage_api_tokens` | `manage_api_tokens` |
| SECURITY | Audit log | `/admin/audit` | `view_audit_log` | `view_audit_log` | – |
| SECURITY | Third-party keys | `/admin/keys` | role is `superadmin` | superadmin | superadmin |

    A group with no listed item is not rendered. No count badges (C10). A page opened by URL without its "Listed
    when" condition renders `StatePanel no-access` "You need the {permission} permission" ("Only a superadmin can
    manage third-party keys" for keys) in place of its content; the frame still renders.
  - **Session card** "YOUR SESSION" (D11): `Avatar` with the initials, the username, "{role} · {clients}" where
    `{clients}` is "all clients" for `superadmin`, else the client ids joined by ", " (the first three, then
    "+{n}"), and "Signed in {fmtDateTime(signed_in_at)} {browserZoneName()}. Token revoked on sign-out." When
    `signed_in_at` is missing only "Token revoked on sign-out." is printed. No IP.
- Pages other than Users start with a heading row: `<h2>` with the page name, its one-line description, and the
  page's primary action on the right (P16).

### 6.4 Users page (frame 4380, D3)

- **Header actions.** "Export audit log" (outline; only with `view_audit_log`; runs the export of 6.5 with empty
  filters) and "+ Add user" (primary; only with `manage_users`; opens the Add user dialog, which replaces the
  inline form).
- **Fetching.** Each widget owns its query, is not created without its permission (`enabled`), renders its own
  skeleton and error, and never blocks another widget. Query keys are shared with the full pages, so opening a
  page afterwards costs nothing: `["admin","users"]`, `["admin","roles"]`, `["admin","clients"]`,
  `["admin","audit-log",{page:1,pageSize:6,user:"",action:""}]`, `["auth","policy"]`, `["admin","api-tokens"]`,
  `["admin","secrets"]`. A superadmin therefore sends seven requests on this page; a user whose only admin
  permission is `view_audit_log` sends two (audit and policy).
- **Tiles** (`StatTile`, not clickable; a tile without its permission is not rendered, and the grid is
  `lg:grid-cols-4` with the remaining tiles left-aligned).

| Label | Needs | Value | Sub | Tone |
|---|---|---|---|---|
| USERS | `manage_users` | number of users | "{n} signed in this week" (`last_sign_in` within the last 7 × 24 h) | neutral |
| MUST CHANGE PASSWORD | `manage_users` | users with `force_pw_change` | "must choose a new one at next sign-in"; "nobody is flagged" for 0 | warning above 0, else success |
| API TOKENS | `manage_api_tokens` | "{n} active" (`status == "active"`) | soon = active tokens whose `expires_at` is within 30 days: 0 → "none expire within 30 days"; 1 → "1 expires in {d} days"; more → "{soon} expire within 30 days" | warning when soon > 0, else success |
| THIRD-PARTY KEYS | superadmin | "{set} / {total}" (set = `source != "unset"`) | "{f} failed its last test · {u} not set" (f = `last_test_ok === false`); "all set, none failing" when both are 0 | destructive when f > 0, else warning when u > 0, else success |

- **Users card.** Title "Users", subtitle "Who can sign in, what they can see, and for which client". Without
  `manage_users` the card body is `StatePanel no-access` "You need the manage_users permission to see users".
  - Toolbar: `SearchInput` "Search username…" (case-insensitive substring, in memory); `FilterSelect` "All roles"
    (role names from `GET /api/roles`); `FilterSelect` "All clients" (client ids from `GET /api/clients`, label
    "{name}"); `SegmentedControl` "Active | Reset pending | All" (`aria-label` "User status", default "All", P1).
    "Active" lists rows whose STATUS is Active, "Reset pending" those whose STATUS is Reset pending, "All"
    everything.
  - `Table framed`, `table-fixed`, widths USER 24% | ROLE 14% | CLIENT 20% | CREATED 12% | LAST SIGN IN 14% |
    STATUS 12% | (menu) 4%:
    - USER: `Avatar` initials and the username.
    - ROLE: role chip.
    - CLIENT: "All clients" for role `superadmin` (`title` lists the assigned ids); otherwise the first two client
      ids as neutral chips and "+{n}" with the full list in `title` (A1).
    - CREATED: `fmtShortDate(created_at)`.
    - LAST SIGN IN: `fmtAgo(last_sign_in)` with `title` `fmtDateTime`; "–" when null.
    - STATUS, first match wins: `force_pw_change` → "Reset pending"; `last_sign_in` null → "Never signed in"; else
      "Active".
    - Menu: `RowMenu` ("Actions for {username}") with "Reset password" (needs `reset_password`), "Change role" and
      "Edit clients" (need `manage_users`). When the row's role is `superadmin` and the viewer's is not, or when no
      item is allowed, the cell is empty (P15).
  - Footer: `NumberedPager`, 10 rows a page (P17), `summary` "Showing {from}-{to} of {filtered}"; next to it the
    hint "⋯ › Reset password makes the user choose a new one at next sign-in". Changing the search or a filter
    returns to page 1. No match: `StatePanel empty` "No user matches these filters" with "Clear filters".
- **Mini-cards**, two rows of two (`lg:grid-cols-2`); a card without its permission is not rendered.
  - "Audit log" / "Latest admin and sign-in events", header link "View all →" (`/admin/audit`); needs
    `view_audit_log`. `table-fixed` TIME 22% | USER 22% | ACTION 30% | TARGET 26%, the six newest rows, TIME =
    `fmtTime` when the row is from the browser's current day as computed in the `queryFn`, else `fmtShortDate`.
  - "Password policy" / "Applies at the next password change", header link "Edit" (`/admin/password-policy`, only
    with `manage_policy`); the card itself needs no permission. Rows "Minimum length" → "{n} characters",
    "Uppercase letter", "Lowercase letter", "Number", "Symbol" → "Required" / "Not required", built from the
    policy fields.
  - "API tokens" / "For SIEM pulls; a token never sees above its TLP", header link "+ New token"
    (`/admin/tokens?new=1`); needs `manage_api_tokens`. `table-fixed` NAME 28% | TOKEN 24% | MAX TLP 16% | EXPIRES
    16% | LAST USED 16%, the four newest active tokens; footnote "Scopes: indicators:read · intel:read ·
    hunt:read. The full token is shown once, at creation." (C17). Empty: "No active token."
  - "Third-party keys" / "{total} providers · {shown} shown · db overrides .env", header link "View all →"
    (`/admin/keys`); superadmin only. The first seven providers in API order: label, source chip, and "Test failed ·
    {fmtAgo}" (destructive text) / "ok · {fmtAgo}" / "not tested".
- **Feature map** (all Admin pages).

| # | Pre-redesign feature | New home |
|---|---|---|
| A1 | Users table: role badge, client badges, created, last sign-in | Users card (plus avatar and STATUS) |
| A2 | Add User (username, policy-validated password, role incl. the superadmin-only option, clients) | "+ Add user" dialog; clients become a checkbox list |
| A3 | Reset Password (admin-typed, policy-validated, `reset_password`) | Row menu → dialog; now flags the account (B-A1) |
| A4 | Change Role | Row menu → dialog |
| A5 | Edit Clients (checkbox list) | Row menu → dialog |
| A6 | Roles list with system badge and permission badges | Roles matrix: one column per role, "SYSTEM" chip in the column header, ticks |
| A7 | Add Role dialog (permission checkboxes) | "+ New role" dialog, permissions grouped |
| A8 | Delete Role (confirm) | Column-header menu on non-system roles → confirm |
| A9 | Password policy form, force-all-change, "users flagged" feedback | Password policy page |
| A10 | Audit log with user / action filters and page size | Audit log page; page size fixed at 50 (select dropped, approved) |
| A11 | Clients table with countries and created | Clients page (CREATED kept, USERS added) |
| A12 | Add / Edit client (country multi-select) | "+ Add client" and row "Edit" → dialog |
| A13 | Delete client (confirm) | Row menu → confirm |
| A14 | API tokens table with status | API tokens page |
| A15 | Create token (TLP, expiry, scopes) and show-once Copy dialog | "+ New token" dialog; show-once banner with "Copy token" |
| A16 | Revoke token (confirm) | Row menu → confirm |
| A17 | Third-party keys list: source, last4, test status | Third-party keys page; mini-card on Users |
| A18 | Edit key (fields + current password) | "Edit" / "Override" / "Set" → dialog |
| A19 | Revert key to .env (current password) | "Revert" → dialog |
| A20 | Test key (OK / FAIL / SKIP / NOTE) | "Test" button; result inline in the row |
| A21 | Master-key-missing notice | `Notice` on the keys page |
| A22 | Page-level access gate and per-section gates | `AdminFrame` gate; nav and page gates per the table in 6.3 |
| A23 | Self-service Change Password dialog (avatar menu) | Unchanged entry point; dialog restyled (6.6) |

### 6.5 The other Admin pages (frame 47691)

- **Roles** (D12, C14). Heading "Roles" / "What each role is allowed to do. Roles are created and deleted, not
  edited." Action "+ New role" (`manage_roles`). Matrix in an `overflow-x-auto` wrapper, `table-fixed` with pixel
  widths because the column count varies: PERMISSION 220 px | ALLOWS 320 px | 112 px per role. Role columns: every
  role from `GET /api/roles` except `superadmin`, system roles first (`admin`, `analyst`), then custom roles by
  name. Column header: the role name in `font-code`, the display name under it, a "SYSTEM" chip for system roles,
  and for a non-system role with `manage_roles` a `RowMenu` ("Actions for {name}") holding "Delete role". Rows: the
  30 permissions from `GET /api/roles/permissions` in API order, under four group rows (`<th colSpan>`): "NEWS AND
  INTELLIGENCE" (`view_news` to `wisemap_access`), "OPERATIONS" (`manage_rfi`, `manage_pir`), "COMMUNICATION"
  (`view_newsletter` to `manage_tweets`), "PLATFORM ADMINISTRATION" (`view_audit_log` to `manage_api_tokens`). The
  grouping is a static map in `lib/admin/permission-groups.ts`; a key the map does not know falls into a last
  group "OTHER", so a new backend permission still shows. PERMISSION = the key in `font-code`, ALLOWS = the API
  description. A cell shows "✓" (`aria-hidden`) with visually hidden "allowed" when the role holds the
  permission, else is empty with visually hidden "not allowed". Cells are text, not controls. Footnote: "{count}
  permissions in total. superadmin is not editable and passes every check."
- **Password policy** (A9). Heading "Password policy" / "Applies at the next password change". Field "Minimum
  length" (number, 8-128, C13) with help "8 or more. Longer beats more symbol rules." Four checkboxes "Require an
  uppercase letter", "Require a lowercase letter", "Require a number", "Require a symbol". Checkbox "Make every
  user change their password at next sign-in" with help "Flags every account except those with the admin role,
  superadmins included. Sessions that are open now keep working until they end." (C12); it is unticked on load
  and after every save. Preview card "WHAT USERS SEE": the rule list of 6.1 rendered for the form's current values
  with every rule unmet, and the line "Shown under every new-password field." Button "Save policy". When the
  force-all box is ticked, Save first opens `ConfirmDialog` "Make every user change their password?" / the help
  sentence / "Save and flag users" (P7). Success: toast "Policy saved", or "Policy saved · {flagged_users} users
  must change their password" when the box was ticked; the `["auth","policy"]` and `["admin","users"]` queries are
  invalidated.
- **Clients** (D13, C11). Heading "Clients" / "Tenants and the countries each one watches." Action "+ Add client"
  (`manage_clients`). `table-fixed` CLIENT ID 20% | NAME 22% | COUNTRIES 28% | USERS 8% | CREATED 12% | (actions)
  10%: client id in `font-code`; countries as neutral chips, "–" when none; USERS = the number of rows in
  `["admin","users"]` whose `client_ids` contain the id (the same permission as the list, so it is always
  available with it; a skeleton while it loads); CREATED = `fmtShortDate` (P2); actions (only with
  `manage_clients`) = text button "Edit" and a `RowMenu` with "Delete" (destructive; absent on `default`, which the
  API refuses to delete). Without `manage_users` the table is replaced by `StatePanel no-access` "You need the
  manage_users permission to list clients" and "+ Add client" stays available. Empty: `StatePanel empty` "No
  client yet".
- **API tokens** (D13). Heading "API tokens" / "For SIEM pulls; a token never sees above its TLP". Action "+ New
  token". `?new=1` opens the Create dialog once and is then removed with `router.replace("/admin/tokens")`.
  - **Banner**, after a token is created, above the table: `Notice tone="warning"`, title "Copy the token for
    “{name}” now", body "{masked} · it will not be shown again. Store it in the consumer's secret store." with
    `{masked}` per C16 in `font-code`, a text button "Show" / "Hide" that swaps the masked text for a read-only
    input holding the full token (`aria-label` "API token", selects itself on focus), and the buttons "Copy token"
    and "Done". "Copy token" → `navigator.clipboard.writeText`; success prints "Copied."; failure reveals the
    input and prints "Copy failed. Select the token and copy it manually." (the dev instance is plain HTTP, where
    the clipboard API does not exist). The token lives in the page's state only (constraint 12); "Done", leaving
    the page or creating another token discards it for good. This banner replaces the "Token created" dialog.
  - Table, `table-fixed` NAME 16% | PREFIX 13% | SCOPES 19% | MAX TLP 10% | CREATED BY 12% | EXPIRES 11% | LAST USED
    10% | STATUS 6% | (menu) 3%: PREFIX "{token_prefix}…"; SCOPES joined by " · "; MAX TLP as "TLP:AMBER" etc.;
    CREATED BY = the username with `fmtShortDate(created_at)` under it in `text-2xs`; EXPIRES = `fmtShortDate` or
    "never", and for an active token within 30 days of expiry a second line "in {d} days" in warning text; LAST
    USED = `fmtAgo` or "never"; STATUS chip; `RowMenu` with "Revoke" (destructive) on active tokens only. Empty:
    `StatePanel empty` "No API token yet".
- **Audit log** (D9, D10). Heading "Audit log" / "Every admin action and sign-in, newest first." Toolbar: two
  text inputs drawn like the mockup's selects, with visible labels "User" and "Action" and placeholder "all"
  (free text sent as `user` and `action`, debounced 400 ms as today; a change returns to page 1), and "Export CSV"
  on the right. `table-fixed` TIME 16% | USER 13% | ACTION 18% | TARGET 15% | DETAIL 26% | IP 12%: the first header
  reads "TIME ({browserZoneName()})" and its cells `fmtDateTime`; ACTION in `font-code`; TARGET "–" when null;
  DETAIL = the object's entries as "key: value" joined by " · " (nested values as JSON), wrapping, "–" when null;
  IP in `font-code`, "–" when empty. `NumberedPager` over `total`, 50 rows a page (P18). Empty: `StatePanel empty`
  "No audit entry matches these filters".
  - **Export CSV** (`lib/admin/audit-export.ts`). Uses the filters as debounced at the click. Fetches
    `GET /api/auth/audit-log?page={n}&page_size=200` sequentially from page 1 until it has `min(total, 5000)` rows
    (at most 25 requests), through `unwrap`. While it runs the button is disabled and reads "Exporting… {got} /
    {target}"; leaving the page aborts it. Any failed page aborts the export with a toast "Export failed: {message}"
    and no file. Columns `timestamp_utc` (the API's ISO string), `user`, `action`, `target`, `detail`
    (`JSON.stringify`, empty when null), `ip`, built with `toCsv` and saved with `downloadCsv` (`lib/csv.ts`, which
    guards formula cells) as `audit-log-{YYYYMMDD}-{HHmm}.csv` in browser time. When `total` exceeds 5,000 the
    toast after the download reads "Exported the newest 5,000 of {total} rows. Narrow the filters to get the
    rest."; otherwise "Exported {n} rows".
- **Third-party keys** (D14). Heading "Third-party keys" / "{n} providers · db overrides .env".
  - Banner (`Notice`): "Changing or reverting a key asks for your current password" / "Set here to override the
    .env value; Revert removes the override so the .env value applies again." Under it, muted, the sentences the
    page has today: "Keys saved here are encrypted in the database and take effect within about 30 seconds,
    without a restart. A saved key is never shown again (only its last four characters). Keep the .env value
    equal to the active key or blank, and never leave a revoked key there."
  - When `enabled` is false (A21): `Notice tone="destructive"` "The server has no encryption key" / "Keys cannot
    be changed here (SECRETS_ENCRYPTION_KEYS is not set). Showing the .env status only."
  - One row per provider in API order (ten today), not a table: label; source chip; key summary "••••{last4}" of
    the first secret field that has one, "–" otherwise; the field names joined by " · " in `font-code`; test status
    "Test ok · {fmtAgo(last_test_at)}", "Test failed · {fmtAgo}" (destructive text) or "Not tested yet"; and the
    buttons: source `db` → "Test", "Edit", "Revert"; `env` → "Test", "Override"; `unset` → "Set". "Edit",
    "Override" and "Set" open the same dialog and are disabled when `enabled` is false or the provider has an
    `error`; "Revert" is also shown when the provider has an `error`, whatever its source. A provider `error`
    prints the existing sentence under the chip ("Saved override ignored: the server has no encryption key. Using
    .env." / "Saved override cannot be read; using .env here (running workers may keep the last good key until
    restarted)."). After "Test" the row shows "Testing…" and then the result in place of the stored status: a chip
    with `OK` (ok), `FAIL` (action), `SKIP` or `NOTE` (neutral) and the `detail` text; a request error shows as
    `NOTE` "Test could not run: {message}" (A20). Each button has an `aria-label` naming the provider.

### 6.6 Dialogs (D15)

Shared anatomy, applied to every dialog below and to `ConfirmDialog`: `DialogTitle` in `font-heading`; a
`DialogDescription` saying what will happen; fields with a real `<label htmlFor>` and `text-sm` inputs; errors as
a `Notice tone="destructive"` inside the dialog under a `role="alert"` wrapper, never only a toast; footer with
"Cancel" (outline) left of one primary button, which shows a pending label and is disabled while the request
runs. Success closes the dialog, shows a toast and invalidates the listed query; failure keeps the dialog open
with its fields. A 403 prints "You need the {permission} permission". New-password fields show the rule list of
6.1 and enable the primary button only when every rule is met. Dialogs are mounted only while open, so their
state starts from the current data.

| Dialog | Title | Description | Fields | Primary | Success toast |
|---|---|---|---|---|---|
| Add user | "Add user" | "The account can sign in right away with this password." | Username (2-50); Password + rules; Role (`Select`; `superadmin` offered only to a superadmin); Clients (checkbox list from `GET /api/clients`, limited to the viewer's own `client_ids` unless superadmin, "default" pre-ticked, at least one, P14) | "Add user" | "{username} added" |
| Reset password | "Reset password for {username}?" | "They are signed out everywhere and must choose a new password at their next sign-in." | Temporary password + rules | "Reset password" | "{username} must choose a new password at next sign-in" |
| Change role | "Change role for {username}" | "Changing the role signs the user out." | Role (`Select`, same rule as Add user) | "Save role" | "{username} is now {role}" |
| Edit clients | "Clients for {username}" | "Changing clients signs the user out." | Checkbox list, at least one, same limit as Add user | "Save clients" | "Clients updated for {username}" |
| New role | "New role" | "A role cannot be edited later; delete it and create it again." | Role ID (2-40, `a-z 0-9 _ -`); Display name (1-60); permission checkboxes under the four group headings, each with its API description | "Create role" | "Role {name} created" |
| Delete role (confirm, destructive) | "Delete role {name}?" | "{n} users have this role. Move them to another role first." when n > 0 (primary disabled), else "The role is removed. This cannot be undone." | – | "Delete role" | "Role {name} deleted" |
| Add / Edit client | "Add client" / "Edit {client_id}" | "Countries decide which regional content this tenant sees." | Client ID (add only; 1-64, `a-z 0-9 _ -`); Display name (1-128); Countries (the existing `CountryMultiSelect`) | "Add client" / "Save client" | "Client {client_id} added" / "saved" |
| Delete client (confirm, destructive) | "Delete client {client_id}?" | "Its users lose access to this tenant. This cannot be undone." | – | "Delete client" | "Client {client_id} deleted" |
| New token | "New API token" | "The full token is shown once, right after you create it." | Name (1-200); Max TLP (`Select`, five values); Expires (`Select`: 365 days, 90 days, Never); Scopes (three checkboxes with today's help text, at least one) | "Create token" | none (the banner appears) |
| Revoke token (confirm, destructive) | "Revoke {name}?" | "Requests with this token fail from now on. This cannot be undone." | – | "Revoke token" | "{name} revoked" |
| Edit key | "Edit {label}" / "Override {label}" / "Set {label}" | "The new value is tested with the provider before it is saved." | One field per provider field (secret fields: password inputs with placeholder "Leave blank to keep the current key"; choice fields: `Select`); "Your current password" (required, C18) | "Save and test" | "{label} saved", or a warning toast "Saved, but the key was not verified ({status}): {detail}" when the probe is not OK |
| Revert key | "Revert {label} to .env?" | "The saved override is deleted and the .env value applies again." | "Your current password" (required) | "Revert" | "{label} reverted to .env" |
| Change password (A23) | "Change password" | "You are signed out everywhere afterwards and sign in with the new password." | Current password; New password + rules | "Save" | "Password changed. Sign in with your new password." (then `logout()`) |
| Change password, forced (L7) | "Choose a new password" | the C5 sentence | Current password; New password + rules | "Save" (footer left: "Sign out") | same, then `logout()`; not dismissible |

Delete role counts the users holding the role from `["admin","users"]` (a viewer with `manage_roles` but without
`manage_users` gets the second sentence and the API's answer). The guard matters because `users.role_name` is a
foreign key without `ON DELETE`: deleting an assigned role fails in the database, and the router does not turn
that into a 4xx.

A wrong current password in the two key dialogs and the two password dialogs is an API error like any other and
prints its `detail`; after five of them the API revokes the session and the next request opens the session-expired
dialog (6.2).

### 6.7 States

- **Login.** Pending: 6.1. No loading state for the page itself. The forced-change stage renders the rule list
  from the default policy (minimum 8, all four rules) until `/api/auth/policy` answers; if that request fails the
  defaults stay and the server's 422 is the guard.
- **Admin, every page and widget.** Loading: skeleton of the table or card (`aria-hidden`) with one
  `role="status"` "Loading {thing}". Error: `StatePanel error` "Failed to load {thing}" with "Retry"
  (`role="alert"`). 403 on a read (a role changed while the page was open): `StatePanel no-access` "You need the
  {permission} permission". Empty: the `StatePanel empty` named per page. A failed widget on the Users page shows
  its own error and leaves the others alone; a failed tile shows "–" with the sub line "failed to load".
- **Mutations.** Described in 6.6; buttons outside dialogs ("Test", "Export CSV", "Save policy") are disabled and
  relabelled while pending.

### 6.8 New primitives and domain pieces (existing ones reused as they are)

1. **`SideNav` gains `groups`** (`components/ui/side-nav.tsx`): `groups?: readonly { heading: string; items:
   readonly { href: string; label: string }[] }[]`, an alternative to `items` (exactly one of the two is passed).
   Each group renders its heading (`text-2xs`, upper case, muted, with an `id`) and a `<ul aria-labelledby>` of the
   same links as today; a group with no item renders nothing. The active rule (`pathname.startsWith(href)`) and
   the link styles are unchanged. Permission filtering is the caller's job: `AdminFrame` builds the groups with
   `useCan`. `SideNav` has no other caller today.
2. **`lib/auth/session-expired.ts`** (store) and **`components/session-expired.tsx::SessionExpiredHost`** (6.2).
3. **`lib/auth/password-policy.ts::passwordRules(password, policy)`** → `{ label: string; met: boolean }[]` in the
   order length, uppercase, lowercase, number, symbol, only for rules the policy requires; and
   **`components/password-rules.tsx::PasswordRules`**, the list used on `/login`, in every new-password dialog and
   in the policy preview. `validatePasswordClient` and `policyHint` are removed once nothing imports them.
4. **`lib/admin/permission-groups.ts`**, **`lib/admin/audit-export.ts`**, and
   **`lib/admin/user-status.ts::userStatus(user)`** (`"active" | "reset-pending" | "never"`), all pure.
5. Admin components: `components/admin/admin-frame.tsx`, `session-card.tsx`, `users-view.tsx` with
   `users-overview.tsx` (tiles and mini-cards) and `user-dialogs.tsx`, `roles-view.tsx`, `password-policy-view.tsx`,
   `clients-view.tsx`, `tokens-view.tsx`, `audit-view.tsx`, `keys-view.tsx`. They are the seven `*-section.tsx`
   files of today, renamed and reworked; `hooks.ts` gains `useApiTokens` and `useSecrets` (the two queries that
   live inside their sections today) and moves to `unwrap` / `noClientRetry`.
6. Reused: `StatTile`, `Chip`, `StatePanel`, `Notice`, `SegmentedControl`, `SearchInput`, `FilterSelect`,
   `NumberedPager`, `RowMenu`, `ConfirmDialog`, `Avatar`, `Table framed`, `PageHeader`, `usePageTitle`,
   `lib/format.ts`, `lib/csv.ts`.

Replaced or removed: the single `app/(app)/admin/users/page.tsx` stack, the inline "Add User" form, the "Token
created" dialog, the page-size select and `SimplePager` in the audit log, the "Admin access required" `Card`,
`HERO_POINTS` and the Indonesian strings on `/login`, `sessionExpiredHandled` and the hard redirect in
`lib/api/client.ts`.

## 7. Out of scope

- Login: SSO sign-in, "remember me", self-service password reset by email, a lockout per account, a "your session
  expired" message on `/login` after a full-load expiry, mobile layouts beyond the `md` collapse.
- Sessions: refresh tokens, a sliding expiry, a list of active sessions, an admin "sign this user out" action,
  showing the sign-in IP (D11), intercepting 401s of direct `fetch` downloads.
- Admin: editing a role's permissions (no endpoint), deleting or disabling a user (no endpoint), a clean API
  error for deleting a role that is still assigned, flagging a newly
  added user, generated passwords, an audit facets endpoint (B-A3), a server-side or audited audit export (B-A4),
  side-nav count badges, filters in the URL, sorting columns, bulk actions, changing which accounts
  `force_all_change` flags, inline key editing.
- Any change to permissions, roles, the rate limits or `jwt_expire_min`.

## 8. Verification

- **Backend tests.** `uv run pytest tests/integration/test_auth_repositories.py
  tests/integration/test_auth_router_snapshot.py tests/unit/test_auth_security.py` (Docker for the first two), with
  `--snapshot-update` once for `test_auth_router_snapshot.py` and the diff reviewed; then `uv run pytest
  tests/integration -k "auth or roles or clients or api_tokens or secrets"` and `uv run pytest tests/unit
  tests/contract packages` (deselect the two known Mac-only failures). Named tests: 4.1, 4.2, 4.3.
- **Static.** `uv run ruff check . && uv run ruff format --check .`; `uv run mypy packages/cti-core/src
  packages/cti-scraper/src` (covers the new keyword-only argument and its two callers' side of the repo).
- **Contract.** `uv run python tools/export_openapi.py` produces no diff.
- **Web.** `pnpm lint`; `pnpm exec next typegen && pnpm exec tsc --noEmit`; `pnpm build` (the build also proves
  `NEXT_PUBLIC_APP_VERSION` resolves and `/login` still prerenders inside its `Suspense`). The pure helpers have no
  unit runner; check in QA: `safeRedirect` with `/x`, `//evil`, `/\evil`, `https://evil` and an encoded path with
  a query; the `Retry-After` parser with "37", "0", "abc" and a missing header; `passwordRules` against a policy
  with every rule off; `userStatus` for the three cases.
- **Visual and behaviour (local).** Isolated compose project `qacve`, API via uvicorn, web via `pnpm dev`. Seed:
  a superadmin, an admin, an analyst with no admin permission, a custom role holding only `view_audit_log`, one
  holding only `manage_clients`, a user who never signed in, an SSO user (no password hash), three clients, tokens
  in all three statuses with one expiring within 30 days, key overrides in `db`, `env` and `unset` with one failed
  test. Checks:
  - Login: 401 copy and kept inputs; eleven wrong attempts → 429 with the countdown reaching 0 and matching
    `redis-cli TTL ratelimit:login:{ip}`; API stopped → the 5xx copy; SSO user → the 400 copy; `?redirect=` honoured
    and `//evil` refused; Show / Hide; the version footer equals `package.json`.
  - Forced change: reset a user from Admin, sign in as them → the stage appears without a URL change, ticks follow
    typing, mismatch error, "Save and continue" lands on the redirect target and the first API call there is 200
    (the 1,200 ms wait works); repeat ten times to exercise the same-second case; reload in the middle → the
    fallback dialog in English; "Cancel and sign out" returns to sign-in with no cookie; the passwords appear
    nowhere in `localStorage`, `sessionStorage`, the URL or the React Query devtools cache.
  - Session expired: with a page open, `redis-cli SET revoked_user:{name} {now}` → on the next request the dialog
    appears once over the same page; the network panel shows one logout call and no further API request while it
    is open; "Close" leaves the banner; a write then toasts the session sentence; "Sign in again" → `/login?redirect=`
    with path and query → back on the same URL after sign-in; a polling page (Scrapers) left open for three minutes
    after expiry sends nothing; a full reload with the revoked cookie lands on `/login?redirect=…`; signing out
    from the avatar menu never shows the dialog; after signing in again without a full reload, API calls work.
  - Admin, per seeded role: nav items and pages match the table in 6.3; a hidden page opened by URL shows
    no-access; the analyst sees "Admin access required"; the audit-only role lands on Users with the Users card
    in its no-access state, no tile, and only the audit and policy mini-cards; the clients-only role can add a client and sees the no-access table.
  - Admin, as superadmin: every A1-A23 row of the feature map exercised once; STATUS and the MUST CHANGE PASSWORD
    tile change after a reset; the force-all confirm and its toast; the roles matrix with a custom role and a
    permission count equal to the API's; token banner Copy on `localhost` and the manual fallback on a plain-HTTP
    host; CSV export of a filtered set and of more than 5,000 rows (seed 5,200) with the truncation toast, opened
    in a spreadsheet to confirm a cell starting with `=` is inert; keys page with the master key unset.
  - Screenshots at 1440 and 1000 px, light and dark, against 2976 / 3117, 47485 / 47580, 4380 / 4894, 47691 /
    48466 and the dialog in 32816 / 33283. Keyboard pass (side nav, tiles are not focusable, toolbar, row menus,
    every dialog, the session dialog's focus and Escape). No nested interactive element in a users row, a token
    row, a key row or a role column header. The tab title keeps the "· {PLATFORM_NAME}" suffix on all seven Admin
    routes. A 403 and a 404 are not retried; an empty-body 502 shows the error state.
- **Delivery.** Commit per backend item, then Login, session handling, the Admin shell, and one commit per Admin
  page; merge into `origin/Dev` (standing approval). On dev 172.25.1.77: read-only checks of all seven routes and
  the session card with the `claude` account. No reset, role change, policy save, token creation or key change on
  dev without the user's go; the sign-in checks that need a password are done by the user.

## 9. Risks

- **Reusing the typed password across the forced change.** The sign-in password stays in page memory longer than
  today: from submit until the change succeeds or is abandoned, typically under a minute, bounded by the page's
  life. It is never placed in storage, a cookie, the URL, the query cache or mutation variables (constraint 12),
  so a reload drops it and the fallback dialog asks for it again. It is as exposed to a script running in the page
  as the password field itself already is; the change adds time, not a new channel. A user who walks away on that
  screen leaves a typed password in memory and a signed-in but restricted session; "Cancel and sign out" and the
  token's own expiry end it.
- **Re-login race after session revocation.** `revoke_user_tokens` stores the revocation time in whole seconds and
  `is_revoked` rejects every token with `iat <= that second`. A sign-in in the same second as the password change
  gets a token that is already revoked, and the user would meet the session-expired dialog on their first click.
  Hence the 1,200 ms wait: it is elapsed time, so the server's clock has passed the next second boundary whatever
  the browser clock says. If the wait were removed or the API's comparison changed, the failure is loud (a dialog),
  not silent. The second sign-in also counts against the per-IP limiter; at the limit the user gets the "Password
  changed" notice with the countdown instead of a dead end. A window-focus refetch of `/api/auth/me` during the
  wait is cancelled by `login()` before it writes the new user.
- **401 dialog versus the proxy redirect.** Two paths end a session and they look different on purpose: an `api`
  call from a mounted page opens the dialog; a full page load never mounts a page, so it goes straight to
  `/login?redirect=…`. `proxy.ts` only checks that a cookie exists, so a dead cookie still reaches the layout and
  costs one `/api/auth/me` round trip before the redirect. If the logout call fails, the dead cookie survives and
  `proxy.ts` would bounce `/login` to `/dashboard`; "Sign in again" re-sends the logout for that reason, and if
  that fails too the user loops once through `/dashboard` → `/login`, as today.
- **A page that stays open after "Close".** It shows stale data and cannot save. The banner says so and the
  synthetic 401 gives every failed write the same sentence, but text typed into a form after expiry is lost unless
  the user copies it. Blocking requests client-side also means a session that was revoked by mistake cannot
  recover without a sign-in, which is the correct outcome for a revoked token.
- **One shared 401 rule.** Every proxied 401 is treated as "session ended". Today only `deps.get_current_user`
  returns 401; an endpoint that later uses 401 for something else (a wrong password is 400 and 403 today) would
  sign users out. Reviewers of new routes need to know this.
- **`Retry-After` source.** The value is the TTL of `ratelimit:login:{ip}`. It is exact for the fixed window, but
  it is keyed by client IP: users behind one NAT share the counter and the wait, and `clientIpHeaders` must keep
  forwarding the real address or everyone shares one bucket. A missing or odd TTL falls back to 60 on the server
  and a missing header to 60 in the browser, so the button can never stay disabled forever; the browser also
  refuses values above 3600. The countdown runs on the browser clock: a suspended laptop may show time left after
  the window has passed, and the next submit simply works.
- **B-A1 changes what a reset does.** Admins who reset a password and tell the user "this is your password" now
  hand over a temporary one; the dialog, the toast, the table hint and the runbook say so. Accounts used by
  scripts break after a reset until someone completes the change by hand. An admin resetting their own account
  from the table is flagged too. Existing rows are untouched. Rolling back the image keeps flags that were set,
  and the pre-0.8.16 forced dialog still clears them.
- **`force_all_change` reach.** It flags superadmins but not the `admin` role (legacy filter, unchanged) and
  revokes nothing; the confirm text states both so the toggle is no longer a surprise. The "Reset pending" status
  and the tile then count policy-flagged users as well, which is why their wording does not mention a reset.
- **Cost of the lazy tile fetches.** The Users page sends up to seven requests for a superadmin where the old page
  sent about as many for its stacked sections, so the total is flat; the difference is that `/api/secrets` and
  `/api/api-tokens` are now requested on the landing page instead of far below the fold. Each is one small query
  without polling, shared by key with its full page. `GET /api/auth/users` returns every user unpaged; filtering
  and paging are in memory, fine for tens to low hundreds of accounts. If the landing page becomes slow, the
  fallback already offered in D3 is to drop the token and key mini-cards.
- **Size of the CSV export.** Up to 25 sequential requests of 200 rows and a few megabytes held in memory, on a
  click. Offset paging over a table that is being written means a row can repeat or be missed at a page boundary
  when events land during the export, and the newest-5,000 cut silently favours recent rows unless the user reads
  the toast. The export is a read through the normal endpoint and is not itself written to the audit log (B-A4
  declined). "Export audit log" on the Users page starts the unfiltered, largest case.
- **The API token banner.** The only copy of the token is in page state; a reload, a navigation or a second
  "Create" loses it and the token must be revoked and recreated. Masking protects against shoulder surfing, not
  against a script in the page.
- **Client-side `signed_in_at` (P5).** For up to a minute after sign-in the card shows the browser's time, then
  the token's; with a skewed browser clock the value visibly shifts once.
- **Largest regression surface: the Admin split.** Seven routes replace one, about ten dialogs are rebuilt and
  the gates move from "section rendered or not" to nav, page and control. The gate table in 6.3 and the per-role
  QA pass are the guard; the admin role gaining a read-only Clients page (P9) is the one intended visibility
  change.
- **Deviations from the frames**, listed for the reviewer: no nav badges (C10), English fixed copy where the
  mockup had sample or untrue text (C5, C6, C12, C16, C17, C22), three token statuses, dialogs instead of the
  inline key editor (C18), the extra CREATED column (P2), "Cancel and sign out" (P4), the banner after "Close"
  (P12).
