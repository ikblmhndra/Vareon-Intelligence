# `apps/web` -- CTI Platform frontend

Next.js App Router + TypeScript. Phase 8 (a rewrite of `ScraperNewsWeb`'s old
vanilla JS/Jinja2) -- see `docs/PROGRESS.md` for per-group status and
`CLAUDE.md` for the shadcn/ui gotchas (Base UI, not Radix).

## Running dev

Needs `cti-api` (FastAPI) running first on `API_BASE_URL` (default
`http://localhost:8000`, `.env.local`) -- Next.js acts as a BFF (Backend For
Frontend): the browser never calls `cti-api` directly, everything goes through
`app/api/proxy/[...path]` (read `src/proxy.ts` + `src/lib/auth/session.ts`
for the architectural reasoning, decision #3 in `docs/PROGRESS.md` Phase 8).

```bash
pnpm install
pnpm dev
```

## Regenerating the API types

`src/lib/api/schema.d.ts` is generated from `docs/openapi.json` (repo root,
produced in Phase 7.7). Re-run it after the backend adds or changes an endpoint:

```bash
pnpm run gen:api
```
