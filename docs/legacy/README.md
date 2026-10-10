# Legacy Artifacts

Things recorded from the old system in Phase 0. Some of them **cannot be
reconstructed** if the prod host is lost.

| File | Source | Commit? | Why it matters |
|---|---|---|---|
| `crontab.txt` | `dump_crontab.sh` | **yes** | Schedule of 206 scrapers. Was never in a repo. Also the only way to know which scrapers are live. |
| `../../legacy/static/` | `pull_static.sh` | **yes** | 27 JS files = the entire frontend. Gitignored in the old repo. Serves as the behavioural spec for the Next.js rewrite. |
| `../../legacy/config.yml` | `pull_config.sh` | **NO** | Contains credentials. Used to confirm DB/collection names. |

Do **not** put the Mongo dump from `backup_mongo.sh` here — keep it outside
the repo and off the prod host. Since the cutover starts from an empty DB, that
dump is the only archive of historical data.
