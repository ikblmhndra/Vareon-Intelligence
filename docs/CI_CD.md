# CI/CD

**CI** (`.github/workflows/ci.yml`): every push to `main` and every PR runs lint, mypy, pytest
(including integration), the web build, the API contract check, compose validation, and an image build + smoke.

**CD** (`.github/workflows/deploy.yml`): as soon as CI for a **push to `main`** is green, production is updated
automatically. It can also be triggered manually (Actions > Deploy > Run workflow).

```
merge PR -> main --CI green--> Deploy (self-hosted runner on the production host)
                                 git merge --ff-only <sha> in the production checkout
                                 tools/ops/deploy.sh:
                                   backup Postgres -> tag running images :prev -> build
                                   -> up -d (migrate first) -> wait until healthy
                                   -> on failure: rollback.py to :prev + Telegram alarm
```

Why a self-hosted runner: the production host (`10.8.20.78`) has a private IP, and GitHub's cloud runners cannot
reach it. The runner pulls jobs from GitHub over an **outbound** connection (HTTPS), so no inbound port or
SSH needs to be opened.

## Setup (once)

1. **Runner on the production host.** The runner in use is **`nameless.selfhosted`** (Settings > Actions >
   Runners), with the default labels `self-hosted`, `Linux`, `X64`. `runs-on` selects by **label**, not by runner
   name, so the deploy job asks for `[self-hosted, Linux, X64]`. Requirements:
   - the runner is installed **on the production host** (not another machine: the deploy script uses the local
     Docker and the production checkout there);
   - it runs as the user that owns the production checkout and is in the `docker` group (it must be able to run
     `docker compose` without sudo).
   If a second self-hosted runner is ever added to this repo, add a dedicated label (e.g. `cti-prod`) to this
   runner via Settings > Actions > Runners > runner > Labels, and add it to `runs-on` in `deploy.yml` and
   `tests/unit/test_deploy_pipeline.py` too; otherwise the deploy job may land on the other runner.
   New runner: follow the commands behind the *New self-hosted runner* button; never paste the token into
   chat/tickets.
2. **Repo variable** `CTI_PROD_DIR` = path of the production checkout (e.g. `/opt/cti-platform`), under Settings >
   Secrets and variables > Actions > *Variables*. That checkout holds `.env`, `docker/stack.env`, and
   `secrets/` (none of them are in git).
3. **The production checkout must be able to `git fetch origin` non-interactively** as the runner user (deploy key
   or credential helper) and be clean on the `main` branch. `--ff-only` refuses if the checkout has diverged.
4. **`production` environment** (Settings > Environments). Optional but recommended: *Required reviewers*,
   so every deploy waits for a one-click approval.
5. **Branch protection for `main`**: require the CI status check and PR review. Without it, anyone who
   can push to `main` can deploy to production automatically.
6. **Test it before relying on it**, on the production host:
   ```bash
   make deploy ARGS='--dry-run'     # prints the plan, changes nothing
   ```
   then run the workflow manually once and watch it.

## What `deploy.sh` does (also runnable by hand: `make deploy`)

Before upgrading prod across several releases, follow `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md` (per-release checks in
`docs/prod-upgrade/<version>.md`).

| Step | On failure -> |
|---|---|
| back up Postgres (`/var/backups/cti`, change with `CTI_BACKUP_DIR`) | deploy aborted, nothing has changed yet |
| tag the images of the **currently running** containers as `:prev` | -- |
| `docker compose build` | aborted, the old stack is untouched |
| `docker compose up -d` (the `migrate` service upgrades the schema first) | rollback to `:prev` + alarm |
| wait for `/healthz` and all containers to be healthy (max 300 s) | rollback to `:prev` + alarm |

- `:prev` is taken from the running containers, not from the `latest` tag, so a failed deploy does not
  overwrite the rollback anchor with a broken image.
- Automatic rollback uses `tools/ops/rollback.py` **without `--yes`**: if the rollback would need
  `alembic downgrade` (which can drop columns/tables), the script stops and raises a Telegram alarm (topic
  `debug`) with manual instructions (`docs/CUTOVER_RUNBOOK.md` section 7). A DB downgrade is always a human decision.
- The deploy result (OK or failed) is reported to the Telegram `debug` topic using the `.env` in the production checkout.

## Limitations to know about

- **There is no staging.** The only validation before production is CI. A migration that corrupts data is not
  caught here; the automatic backup before each deploy is the safety net.
- **`.env` / `docker/stack.env` are not in git.** If a PR adds a new key, set it on the production host
  **before** merging, otherwise the application refuses to start (and the deploy rolls back).
- **Self-hosted runner = code running on the production host.** Never use this runner
  (`runs-on: self-hosted`) in a workflow triggered by PRs, and never open this repo to untrusted contributors without branch
  protection. A runner user in the `docker` group is equivalent to root on that host.
- One deploy at a time (`concurrency` + `flock`). A running deploy is not cancelled by a new commit;
  the next commit waits its turn.
- To disable CD temporarily: Actions > Deploy > *Disable workflow* (or stop the runner service).
