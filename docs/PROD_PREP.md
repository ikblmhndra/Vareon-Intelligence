# Production preparation (Phase 10.F) -- 4 steps that can only be run on the production host

These four items need access to the old/new production hosts, which the assistant that wrote this
document does not have -- so this is a step-by-step guide to RUN MANUALLY, not something that
has already been executed. Do them in any order; the four are independent of each other.

> Same ground rules as the other documents: never paste/copy the contents of `.env`, `config.yml`,
> or any secret value into chat/tickets/logs. Check that something exists with `grep -q "^KEY=." file`, not
> by printing its value.

---

## 1. Mongo backup + restore drill (checklist "Mongo backup <24 h, restore tested")

Mongo (`mongod`) runs LOCALLY on the old production host (from `legacy/config.yml`: the `threatintel` cluster,
plus the `news_db` database used by `ScraperNewsWeb`). Tools: Mongo's own `mongodump`/`mongorestore` --
no new tool needed, they are enough for this one-off need.

```bash
# --- on the old production host ---
BACKUP_DIR=/var/backups/mongo-cti/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"

# Dump BOTH databases (news_db is used by ScraperNewsWeb, threatintel by the scrapers) --
# --uri reads credentials from the environment/config, do NOT write them on the command line (they show up in
# `ps`/shell history if written literally).
mongodump --uri="$MONGO_URI" --db=news_db     --out="$BACKUP_DIR"
mongodump --uri="$MONGO_URI" --db=threatintel --out="$BACKUP_DIR"

# Check that size + collection count look sane (compare with the previous day)
du -sh "$BACKUP_DIR"
ls "$BACKUP_DIR/news_db" | wc -l

# Copy it OFF the host (same disk = not a backup) -- adjust the destination
rsync -a "$BACKUP_DIR" user@other-host:/backups/mongo-cti/
```

**Restore drill** (prove the dump can actually be restored, not just that "the file exists"):

> ⚠️ **The commands below differ from the first version of this document** -- 2 traps were found when the drill
> was actually run (2026-09-30, staging), and both MUST be avoided:
>
> 1. `mongorestore --nsFrom=... --nsTo=... "$BACKUP_DIR/news_db"` (pointing DIRECTLY at the
>    per-db folder) **DOES NOT WORK** -- `mongorestore` cannot infer the db name from a folder given
>    directly as `--dir`/positional; the result is "don't know what to do with file" and 0 documents
>    restored. It has to be `--dir="$BACKUP_DIR"` (the PARENT folder that holds both `news_db/` + `threatintel/`),
>    so `mongorestore` detects the db name from the subfolder name.
> 2. BUT if that parent `--dir` folder holds more than one database (our case: `news_db`
>    AND `threatintel`) and you only set `--nsFrom`/`--nsTo` WITHOUT `--nsInclude`,
>    `mongorestore` still PROCESSES EVERYTHING in the folder -- whatever matches the `nsFrom` pattern is remapped to
>    the test name, and whatever does NOT match (the other database in the same folder) is still restored under its ORIGINAL
>    NAME. The effect is that a restore to `news_db_restore_test` silently ALSO writes to the real
>    `threatintel` (and vice versa in the second command) -- on staging `news_db`/`threatintel` happened to be
>    empty so no data was overwritten, but in production (which holds the REAL databases, not
>    empty ones) this can overwrite real data. **`--nsInclude` is MANDATORY**, not optional.

```bash
# Restore into a TEMPORARY database on the SAME Mongo instance (not overwriting the real news_db).
# --dir MUST be the PARENT folder ($BACKUP_DIR, not $BACKUP_DIR/news_db), and --nsInclude MUST
# be present so the other database in the same folder is not restored under its original name.
mongorestore --uri="$MONGO_URI" \
    --nsInclude="news_db.*" --nsFrom="news_db.*" --nsTo="news_db_restore_test.*" \
    --dir="$BACKUP_DIR"
mongorestore --uri="$MONGO_URI" \
    --nsInclude="threatintel.*" --nsFrom="threatintel.*" --nsTo="threatintel_restore_test.*" \
    --dir="$BACKUP_DIR"

# Compare document counts per key collection with the originals (or, if the original database is
# empty/missing as on staging, compare with a count taken straight from the dump file:
# `bsondump --quiet "$BACKUP_DIR/news_db/$col.bson" | wc -l`)
for col in articles cve_tracker iocs scraper_runs; do
  orig=$(mongosh "$MONGO_URI" --quiet --eval "db.getSiblingDB('news_db').$col.countDocuments()")
  test=$(mongosh "$MONGO_URI" --quiet --eval "db.getSiblingDB('news_db_restore_test').$col.countDocuments()")
  echo "$col: original=$orig restore=$test"
done

# Clean up the temporary databases
mongosh "$MONGO_URI" --quiet --eval "db.getSiblingDB('news_db_restore_test').dropDatabase()"
mongosh "$MONGO_URI" --quiet --eval "db.getSiblingDB('threatintel_restore_test').dropDatabase()"
```

**Already run & passed (2026-09-30, staging, container `cti-mongo`):** dump `20260930T120307Z`
(58 MB `news_db` + 22 MB `threatintel`, from `/home/nameless/backups/mongo-cti/`). Restoring both
dbs took **2 seconds** in total (205,446 documents). All 9 key collections were checked to match EXACTLY the counts
taken straight from the dump file (`bsondump`, because `news_db`/`threatintel` on staging are empty, so there is no
"original" to compare against): `articles` 8834, `cve_tracker` 667, `iocs` 23956, `scraper_runs` 9330,
`users` 7, `clients` 2, `techstack` 32, `groups` 3995, `hash` 398 -- zero difference. The test databases
were cleaned up (`dropDatabase`, run manually twice by the user because the automatic classifier
refused consecutive `dropDatabase()` calls as a "mass delete" even after confirmation in chat).
**Note:** this drill was on STAGING (not the actual old production host this document
targets) -- it proves the restore MECHANISM is right and that `mongorestore` is fully installed; it is not a
substitute for a drill in production. It is also the SOURCE of the dump used for the cutover warm start
(runbook 3, step 4) -- do not throw it away.

**How to get the dump into the container if `docker cp` fails** (found on staging: the
`docker-entrypoint-initdb.d/init.js` mount in `cti-mongo` got stuck as an empty directory -- not a file
as it should be -- which makes ANY `docker cp` into this container fail with a mount error, even though
the container itself runs healthy. Not fixed at the source, and not touched in this session because it is
outside the restore drill's scope): use `tar` streaming through `docker exec -i` instead, which does not
hit the same mount check --
```bash
tar -C "$BACKUP_DIR" -cf - news_db threatintel | docker exec -i cti-mongo tar -C /tmp/restore-drill -xf -
```

---

## 2. Rundeck snapshot (D-1, not a drill -- read-only, safe to run any time)

The tool already exists (`tools/ops/rundeck_schedule.py`, see its docstring) and is documented in
`docs/CUTOVER_RUNBOOK.md` section 2.3. A summary here so you do not have to jump back and forth:

```bash
export RD_URL=http://10.8.20.78:4440       # IP from legacy/config.yml, not a secret
export RD_PROJECT=Threat-Information
read -s RD_TOKEN                            # Rundeck API token -- typed interactively, NOT in shell history
export RD_TOKEN

python3 tools/ops/rundeck_schedule.py snapshot --out rundeck-before-cutover.json
python3 tools/ops/rundeck_schedule.py status   --snapshot rundeck-before-cutover.json   # must be N/N
```

Keep `rundeck-before-cutover.json` off the production host AND out of the repo (it holds job names, not
secrets, but still do not commit it). This is what `disable`/`enable` use on cutover day (runbook 3)
and for rollback to the old stack (section 3 below). **Take a NEW snapshot exactly at D-1** -- the one in
`docs/legacy/rundeck-jobs-map.json` is a Phase 0 recording and may be stale.

Never tested against the REAL Rundeck (only a fake API in the unit tests) -- step 2 below
doubles as its first trial against production Rundeck.

---

## 3. Rollback drill to the old stack in <5 minutes (in PRODUCTION, at least once before go-live)

This is a DRILL, not just reading a document -- runbook section 7.3 explains WHAT is done; the steps
below actually RUN it with a stopwatch, in a quiet hour (not working hours), WITHOUT
an actual cutover intent (the new stack does not even need to be running for this drill -- it is enough
to prove the OLD stack can be switched off and on through this procedure).

```bash
# 0. Prerequisite: the Rundeck snapshot (section 2) exists and is still accurate (active jobs have not changed
#    since the snapshot was taken -- if in doubt, take a new snapshot)
python3 tools/ops/rundeck_schedule.py status --snapshot rundeck-before-cutover.json   # note N/N

# 1. Note the start time
date -u

# 2. DISABLE the schedule (exactly cutover procedure step 2)
python3 tools/ops/rundeck_schedule.py disable --snapshot rundeck-before-cutover.json
python3 tools/ops/rundeck_schedule.py status  --snapshot rundeck-before-cutover.json   # must be 0/N

# 3. (simulating "the new platform is called off" -- for this drill you may skip actually stopping/starting the
#    cti-web/nlp_worker/iocSyncer units if the old stack IS still the active one;
#    if the new platform is running in parallel, stop it first: docker compose ... stop
#    beat worker worker-browser worker-nlp nginx)

# 4. RE-ENABLE the schedule (this is what is measured -- "rollback to the old stack")
python3 tools/ops/rundeck_schedule.py enable --snapshot rundeck-before-cutover.json
python3 tools/ops/rundeck_schedule.py status --snapshot rundeck-before-cutover.json   # must be N/N again

# 5. Note the end time
date -u
```

**After the drill:** write the result into `docs/CUTOVER_RUNBOOK.md` section 7.3, on the line
"write the time: `____ minutes` (target <5)" -- replace it with the real number. If it took more than 5 minutes or
a job failed to enable/disable, that is a finding to fix BEFORE go-live, not something
to ignore.

---

## 4. Scheduled Postgres backup + off-host copy (NEW production host)

### 4a. systemd timer (the unit files exist, not installed yet)

```bash
# On the new production host, working directory = where docker-compose.yml + docker/stack.env live
sudo cp docker/ops/cti-pg-backup.service docker/ops/cti-pg-backup.timer /etc/systemd/system/
# Adjust WorkingDirectory in cti-pg-backup.service if the location is not /opt/cti-platform
sudo systemctl daemon-reload
sudo systemctl enable --now cti-pg-backup.timer

# Verify the schedule is installed
systemctl list-timers cti-pg-backup.timer

# Test once manually (do not wait for 02:30)
sudo systemctl start cti-pg-backup.service
journalctl -u cti-pg-backup -n 30 --no-pager
ls -la /var/backups/cti      # a new dump must appear, chmod 600
```

A failure triggers a Telegram alarm on the `debug` topic automatically (`--on-failure-cmd` in the unit file) -- this test
therefore also proves the alarm path, not just the backup.

### 4b. Off-host copy (NOT automated yet -- this is the remaining gap)

A backup on the same disk as its Postgres is not a backup (if that disk/host breaks, the backup is
lost too). Two options, pick one:

**Option A -- cron `rsync` to another host** (simplest; needs a one-way SSH key from the production host to the
storage host, read-write ONLY to the backup directory):

```bash
# On the production host, root's crontab (or a user with read access to /var/backups/cti)
# Runs 15 minutes after the backup timer (02:30 + buffer)
crontab -e
# add:
45 2 * * * rsync -a --delete /var/backups/cti/ backup-host:/backups/cti-platform/ 2>&1 | logger -t cti-backup-offhost
```

**Option B -- `rclone` to object storage** (S3-compatible etc., if there is no suitable second host):

```bash
rclone config          # once, interactive -- enter the storage provider's credentials
# then a cron with the same pattern:
45 2 * * * rclone sync /var/backups/cti/ remote:cti-platform-backups/ 2>&1 | logger -t cti-backup-offhost
```

**Once installed (option A or B):** verify it once by running the cron entry manually, check
the files really appear at the destination, then update `docs/CUTOVER_RUNBOOK.md` section 6 -- replace the line
"Off-host: ... not automated yet" with the method used + its schedule.

---

## After all four are done

Update the cutover checklist in `docs/PROGRESS.md` ("Checklist cutover") and the related lines in
`docs/CUTOVER_RUNBOOK.md` section 10 ("What is NOT yet proven") -- do not let those two documents say
"not yet" when this one says "done".
