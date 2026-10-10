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
