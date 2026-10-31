# Default reference data (fresh deployment without the old Mongo)

Three small collections the new platform needs for its features to work, copied as-is from the legacy
Mongo dump (`mongodump`, layout `<database>/<collection>.bson`). The contents are public data, not secrets:

| File | Contents | Rows | Target table |
|---|---|---|---|
| `threatintel/groups.bson` | dictionary of threat actor names (sources: malpedia, eternal-library, threat-card, mstic, orkl, ransomlook, mitre, etc.) | 3991 | `threat_actor_groups` |
| `threatintel/apac-people.bson` | APAC demonyms/nationalities (NOT people's names) | 30 | `monitored_people` |
| `news_db/ioc_allowlist.bson` | IPs/domains that must not be counted as IOCs | 9 | `ioc_allowlist_entries` |

Without `threat_actor_groups`, scoring finds no threat actors at all: the TA dropdown is empty and TA-based
PIRs always return 0 results (staging QA finding, 2026-10-01).

`tools/ops/fresh_deploy.sh` loads them automatically through `tools/seed/fase5_reference_data.py --dump-dir`.
Idempotent: re-running it does not duplicate rows and does not overwrite changes made in the UI.

To add or update: replace the `.bson` file with a new `mongodump` output (keep its name and location).
Other curated data (clients, techstack, monitored X accounts, PIRs, etc.) is NOT included -- it is entered
through the UI, or through `tools/seed/fase10_reference_data.py` if you have an old Mongo dump.

## MISP Galaxy snapshot (moved to `packages/cti-core/src/cti_core/entity/data/misp-galaxy/`)

`threat-actor.json`, `ransomware.json` and `malpedia.json` from [MISP Galaxy](https://github.com/MISP/misp-galaxy)
(CC0) are not in this folder: they ship as package data of `cti-core`, so the Docker images have
them too. Upstream commit, date and local changes are in that folder's `SOURCE`. Input of
`cti-entity merge-aliases`, which merges actor (`intrusion-set`) and malware/tool entities that a
Galaxy cluster lists as synonyms and adds the synonyms as aliases of existing entities (clusters
that match no entity create nothing). The weekly `entity.alias_sync` task stores a newer copy in
`reference_snapshots`; the command prefers that copy and falls back to the package data;
`--snapshot-dir DIR` overrides the package data. Run `--dry-run --csv <path>` first and review the
CSV before `--apply`. To refresh: download the three files again, update `SOURCE`, and rerun gitleaks
(`gitleaks dir packages/cti-core/src/cti_core/entity/data/misp-galaxy`).
