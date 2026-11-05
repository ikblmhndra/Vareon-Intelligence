# P7e Hunting Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate hunting packs (CIM `tstats` SPL for IOCs, matching SigmaHQ rules with
attribution, IOC CSVs, zip) for a story or an entity, served to the web (JWT) and to machines
(`/api/v2`, scope `hunt:read`, TLP per token), plus an on-demand LLM hunt hypothesis in the web.

**Architecture:** Packs are built at read time: async collectors gather techniques (tiered) and
active indicators, a pure builder renders SPL/Sigma/CSV/zip. SigmaHQ rules live in a new
`sigma_rules` table filled from a committed release zip at API bootstrap and refreshed weekly by a
Celery task; `hunt_hypotheses` stores LLM drafts.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, FastAPI, Celery, PyYAML, Next.js 16 +
shadcn/ui on Base UI, TanStack Query.

**Spec:** `docs/superpowers/specs/2026-11-04-p7e-hunting-packs-design.md` (read it first; section
numbers below refer to it).

## Global Constraints

- Release 0.8.11, **no version bump**; the CHANGELOG entry goes under the existing `## [0.8.11]` (Indonesian).
- **No new required `.env` key**; the only new key `SIGMA__SYNC_ENABLED` defaults to `true` and appears commented in `.env.example` and `.env.prod.template`.
- Do not touch `packages/cti-enrich/**` or `apps/worker/src/cti_worker/tasks/enrich.py` (P7g).
- Migration chains on head `1387fae00908`; DDL only, no data step; downgrade drops both tables.
- Code identifiers English; comments/docstrings Indonesian; docs English; commit messages English conventional ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Ruff line length 100; mypy strict for `packages/cti-core/src`.
- SPL chunk size **200** values; entity indicator cap **2,000**; entity window default **90** days (1-365).
- Sigma load guards: refuse when the zip is unreadable, **< 1,000** valid rules, or **< 80%** of the stored count.
- Sigma statuses kept: `stable, test, experimental`; paths containing `deprecated` or `unsupported` skipped.
- Every Sigma rule shown or exported carries `author` and the link `https://github.com/SigmaHQ/sigma/blob/<release>/<path>`; the zip includes `LICENSE.Detection.Rules.md` and DRL 1.1 attribution in `README.md`.
- Only indicators with `state == "active"`; tokens additionally `tlp in tlp_allowed(max_tlp)`.
- The LLM hypothesis never appears in SPL, Sigma, the zip, or `/api/v2`; no indicator values are sent to the LLM.
- Web: shadcn/ui on Base UI (`render={...}`, not `asChild`), no `backdrop-blur`, checked light/dark/375 px.
- Downloading the SigmaHQ zip (Task 3) needs the user's explicit approval at that moment.
- Local QA DB only via `POSTGRES_PORT=55434 REDIS_PORT=56380 docker compose -p qap7e up -d postgres redis`; never `deploy-postgres-1`.
- `tests/contract/test_golden.py::test_golden_trendmicro` fails locally only: deselect it.

## Review Focus

1. A story with indicators but no techniques (or an empty Sigma table) must still return a valid pack with `sigma: []`, not 500. Owned by Task 6 (`test_story_pack_without_techniques`).
2. IPv6 values and values with spaces or quotes must be quoted correctly in SPL. Owned by Task 5 (`test_spl_quotes_ipv6_and_spaces`).
3. Indicator types without a CIM mapping must not crash the builder; they appear in `iocs` under `other` with no SPL. Owned by Task 5 (`test_unmapped_type_goes_to_other`).
4. Repeated bootstrap (several uvicorn processes, restarts) must load Sigma once. Owned by Task 3 (`test_bootstrap_sigma_idempotent`).
5. A release zip with a top-level folder or `\` separators must still load. Owned by Task 2 (`test_parse_strips_top_folder`).

---

### Task 1: Tables `sigma_rules`, `hunt_hypotheses` (models + migration)

**Files:**
- Create: `packages/cti-core/src/cti_core/db/models/hunt.py`
- Modify: `packages/cti-core/src/cti_core/db/models/__init__.py` (export)
- Create: `alembic/versions/<rev>_hunt_packs.py` (`down_revision = "1387fae00908"`)
- Modify: `packages/cti-core/pyproject.toml` (add `pyyaml>=6.0`; `uv lock` must resolve to the locked 6.0.3, no new download)
- Test: `tests/integration/test_hunt_tables.py`

**Interfaces:**
- Produces: `SigmaRule` (columns exactly as spec 3.1; `id: uuid.UUID` PK; `techniques: list[str]` with GIN index `ix_sigma_rules_techniques`), `HuntHypothesis` (spec 3.2; unique `uq_hunt_hypotheses_anchor` on `(anchor_type, anchor_id)`, CHECK `ck_hunt_hypotheses_anchor_type`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_hunt_tables_roundtrip(db_session):
    db_session.add(
        SigmaRule(
            id=uuid.uuid4(),
            title="t",
            author="a",
            level="high",
            status="test",
            ruleset="core",
            logsource={"product": "windows"},
            techniques=["T1059.001"],
            path="rules/x.yml",
            release="r2026-07-01",
            yaml="title: t",
        )
    )
    db_session.add(
        HuntHypothesis(anchor_type="story", anchor_id=1, text="h", model="m", generated_by="u")
    )
    await db_session.flush()
    rows = (
        await db_session.execute(
            select(SigmaRule.id).where(SigmaRule.techniques.contains(["T1059.001"]))
        )
    ).all()
    assert len(rows) == 1


async def test_hunt_hypothesis_anchor_type_check(db_session):
    db_session.add(
        HuntHypothesis(anchor_type="article", anchor_id=1, text="h", model="m", generated_by="u")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/test_hunt_tables.py -q` → FAIL (ImportError).
- [ ] **Step 3: Implement** the models and a hand-written migration in the style of `1387fae00908_entity_model.py`.
- [ ] **Step 4: Run** `uv run pytest tests/integration/test_hunt_tables.py tests/integration/test_migrations_match_models.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(core): add sigma_rules and hunt_hypotheses tables`.

---

### Task 2: Sigma zip parser and loader (`cti_core/hunt/sigma.py`)

**Files:**
- Create: `packages/cti-core/src/cti_core/hunt/__init__.py`, `packages/cti-core/src/cti_core/hunt/sigma.py`
- Test: `tests/unit/test_sigma_parse.py`, `tests/integration/test_sigma_load.py`

**Interfaces:**
- Consumes: `SigmaRule`, `ReferenceSnapshot`.
- Produces:
  - `SIGMA_SNAPSHOT = "sigma"`, `MIN_RULES = 1000`, `MAX_SHRINK = 0.2`
  - `@dataclass ParsedRule(id: uuid.UUID, title: str, author: str, level: str, status: str, ruleset: str, logsource: dict[str, str], techniques: list[str], path: str, yaml: str)`
  - `@dataclass ParsedSigma(rules: list[ParsedRule], skipped: dict[str, str])` (path → reason)
  - `class SigmaLoadError(Exception)`
  - `parse_sigma_zip(data: bytes) -> ParsedSigma` (pure; raises `SigmaLoadError` when not a zip)
  - `techniques_from_tags(tags: list[str]) -> list[str]` (`attack.t1059.001` → `T1059.001`; tactic, group and software tags ignored; sorted, unique)
  - `@dataclass SigmaLoadResult(release: str, rules: int, skipped: int, sha256: str)`
  - `load_sigma_zip(session: Session, data: bytes, *, release: str, source_url: str) -> SigmaLoadResult` (sync `Session`; raises `SigmaLoadError` on a guard; replaces all rows; merges `ReferenceSnapshot(name="sigma", sha256=..., content={release, rules, skipped, source_url, last_error: None})`; does not commit)
  - `record_sigma_error(session: Session, error: str) -> None` (sets `content["last_error"]` on the existing snapshot row; no-op when there is none)

Paths: replace `\` with `/`, strip everything before the first `rules/` or `rules-emerging-threats/` segment, ignore files outside both. Ruleset `emerging-threats` for `rules-emerging-threats/...`, else `core`. Missing `author` → `""`.

- [ ] **Step 1: Write failing unit tests** (zips built in memory with `zipfile`; helper `_rule(uid, tags, status="test", level="high") -> str` returns rule YAML)

```python
def test_techniques_from_tags():
    assert techniques_from_tags(
        ["attack.execution", "attack.t1059.001", "attack.T1059", "attack.g0016", "cve.2021-1"]
    ) == ["T1059", "T1059.001"]


def test_parse_good_and_skipped():
    p = parse_sigma_zip(
        _zip(
            {
                "rules/windows/a.yml": _rule(U1, ["attack.t1059.001"]),
                "rules/windows/b.yml": "title: no id\nlogsource: {}\nlevel: high\nstatus: test\n",
                "deprecated/windows/c.yml": _rule(U2, []),
                "rules/windows/d.yml": _rule(U3, [], status="deprecated"),
            }
        )
    )
    assert [r.id for r in p.rules] == [U1]
    assert p.rules[0].ruleset == "core" and p.rules[0].techniques == ["T1059.001"]
    assert set(p.skipped) == {"rules/windows/b.yml", "rules/windows/d.yml"}


def test_parse_strips_top_folder():
    p = parse_sigma_zip(
        _zip({"sigma_all_rules\\rules-emerging-threats\\2024\\x.yml": _rule(U1, ["attack.t1190"])})
    )
    assert p.rules[0].path == "rules-emerging-threats/2024/x.yml"
    assert p.rules[0].ruleset == "emerging-threats"


def test_parse_not_a_zip():
    with pytest.raises(SigmaLoadError):
        parse_sigma_zip(b"nope")
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_sigma_parse.py -q` → FAIL.
- [ ] **Step 3: Implement** `parse_sigma_zip` and `techniques_from_tags` with `yaml.safe_load`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Write failing integration tests** (sync session fixture as used by `tests/integration/test_entity_alias_sync.py`; `_zip_n(n)` builds `n` valid rules)

```python
def test_load_replaces_rows(sync_db):
    r = load_sigma_zip(sync_db, _zip_n(1200), release="r1", source_url="u")
    assert r.rules == 1200
    assert sync_db.scalar(select(func.count()).select_from(SigmaRule)) == 1200
    snap = sync_db.get(ReferenceSnapshot, "sigma")
    assert snap.content["release"] == "r1" and snap.content["last_error"] is None


def test_load_refuses_below_minimum(sync_db):
    with pytest.raises(SigmaLoadError):
        load_sigma_zip(sync_db, _zip_n(999), release="r1", source_url="u")


def test_load_refuses_shrink_and_keeps_rows(sync_db):
    load_sigma_zip(sync_db, _zip_n(2000), release="r1", source_url="u")
    with pytest.raises(SigmaLoadError):
        load_sigma_zip(sync_db, _zip_n(1500), release="r2", source_url="u")
    assert sync_db.scalar(select(func.count()).select_from(SigmaRule)) == 2000


def test_record_error(sync_db):
    load_sigma_zip(sync_db, _zip_n(1200), release="r1", source_url="u")
    record_sigma_error(sync_db, "HTTPError: 503")
    assert sync_db.get(ReferenceSnapshot, "sigma").content["last_error"] == "HTTPError: 503"
```

- [ ] **Step 6: Run** `uv run pytest tests/integration/test_sigma_load.py -q` → FAIL; implement `load_sigma_zip` (`delete(SigmaRule)`, then inserts in batches of 500) and `record_sigma_error`; run → PASS.
- [ ] **Step 7: Run** `uv run mypy packages/cti-core/src && uv run ruff check packages/cti-core` → clean.
- [ ] **Step 8: Commit** `feat(core): parse and load SigmaHQ release zips`.

---

### Task 3: Committed snapshot, bootstrap and `cti-sigma` CLI

**Files:**
- Create: `packages/cti-core/src/cti_core/hunt/data/sigma/sigma_all_rules.zip`, `SOURCE`, `LICENSE.Detection.Rules.md`
- Create: `packages/cti-core/src/cti_core/hunt/cli.py`
- Modify: `packages/cti-core/pyproject.toml` (`cti-sigma = "cti_core.hunt.cli:main"`; make sure the hatch build includes `hunt/data/**`, as it does for `entity/data`)
- Modify: `apps/api/src/cti_api/main.py` (`bootstrap_reference_rows`)
- Test: `tests/unit/test_sigma_snapshot.py`, `tests/integration/test_sigma_bootstrap.py`

**Interfaces:**
- Consumes: Task 2 `load_sigma_zip`, `parse_sigma_zip`, `MIN_RULES`.
- Produces: `SNAPSHOT_DIR: Path`, `read_source() -> dict[str, str]` (keys `release`, `url`, `sha256`, `downloaded`; `SOURCE` holds `key: value` lines), `ensure_sigma_rules(session: Session) -> SigmaLoadResult | None` (loads the committed zip only when `sigma_rules` is empty; else None).

- [ ] **Step 1: Ask the user for approval** to download `https://github.com/SigmaHQ/sigma/releases/download/r2026-07-01/sigma_all_rules.zip` (3,172,748 bytes) and `https://raw.githubusercontent.com/SigmaHQ/Detection-Rule-License/main/LICENSE.Detection.Rules.md`. Stop until approved. Then `curl -fL` both into the snapshot directory, compute `shasum -a 256`, write `SOURCE`.
- [ ] **Step 2: Write failing tests**

```python
def test_committed_snapshot_matches_source():
    src = read_source()
    data = (SNAPSHOT_DIR / "sigma_all_rules.zip").read_bytes()
    assert hashlib.sha256(data).hexdigest() == src["sha256"]
    assert len(parse_sigma_zip(data).rules) >= MIN_RULES


async def test_bootstrap_sigma_idempotent(db_session):
    await bootstrap_reference_rows(db_session)
    n1 = await db_session.scalar(select(func.count()).select_from(SigmaRule))
    await bootstrap_reference_rows(db_session)
    assert n1 >= 1000
    assert await db_session.scalar(select(func.count()).select_from(SigmaRule)) == n1
```

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement.** In `bootstrap_reference_rows`, after the advisory lock and before `ensure_system_roles` (which commits): `await session.run_sync(ensure_sigma_rules)` inside a `try` that logs `sigma_bootstrap_failed` with the exception and continues. CLI `cti-sigma import ZIP --release TAG` (typer, `cti_core.entity.cli` style) loads, commits and prints the result.
- [ ] **Step 5: Run** both tests and `uv run pytest tests/integration -k bootstrap -q` → PASS.
- [ ] **Step 6: Commit** `feat(core): ship pinned SigmaHQ snapshot and load it at API start`.

---

### Task 4: Weekly `sigma.sync` task and `SigmaSettings`

**Files:**
- Modify: `packages/cti-core/src/cti_core/config.py` (`class SigmaSettings(_StrictModel): sync_enabled: bool = True`; `Settings.sigma: SigmaSettings = Field(default_factory=SigmaSettings)`)
- Modify: `.env.example`, `.env.prod.template` (commented `# SIGMA__SYNC_ENABLED=true` with one explanatory line, next to `ENTITY__ALIAS_SYNC_ENABLED`)
- Create: `apps/worker/src/cti_worker/tasks/sigma.py`
- Modify: `apps/worker/src/cti_worker/celery_app.py` (import the module), `apps/worker/src/cti_worker/beat.py` (`"sigma-sync": {"task": "sigma.sync", "schedule": crontab(hour=3, minute=30, day_of_week=0), "options": {"queue": QUEUE_MAINTENANCE}}`)
- Test: `tests/integration/test_sigma_sync.py`, `tests/unit/test_beat_schedule.py` (extend)

**Interfaces:**
- Consumes: `load_sigma_zip`, `record_sigma_error`, `SigmaLoadError`.
- Produces: `RELEASES_URL = "https://api.github.com/repos/SigmaHQ/sigma/releases/latest"`, `ASSET_NAME = "sigma_all_rules.zip"`, `MAX_BYTES = 20 * 1024 * 1024`, `sync_sigma(session: Session, get_json: Callable[[str], dict[str, Any]], get_bytes: Callable[[str], bytes]) -> dict[str, Any]` returning `{"status": "unchanged" | "loaded" | "failed", "release": str | None, "rules"?: int, "error"?: str}`; Celery task `sigma.sync` returning `{"skipped": "disabled"}` when `sync_enabled` is false.

- [ ] **Step 1: Write failing tests** (`_boom` raises; fake fetchers)

```python
def test_sync_unchanged(sync_db):
    load_sigma_zip(sync_db, _zip_n(1200), release="r1", source_url="u")
    out = sync_sigma(sync_db, lambda u: {"tag_name": "r1", "assets": []}, _boom)
    assert out["status"] == "unchanged"


def test_sync_loads_new_release(sync_db):
    load_sigma_zip(sync_db, _zip_n(1200), release="r1", source_url="u")
    rel = {"tag_name": "r2", "assets": [{"name": ASSET_NAME, "browser_download_url": "z"}]}
    out = sync_sigma(sync_db, lambda u: rel, lambda u: _zip_n(1300))
    assert out == {"status": "loaded", "release": "r2", "rules": 1300}


def test_sync_failure_keeps_rows_and_records_error(sync_db):
    load_sigma_zip(sync_db, _zip_n(1200), release="r1", source_url="u")
    out = sync_sigma(sync_db, lambda u: {"tag_name": "r2", "assets": []}, _boom)
    assert out["status"] == "failed"
    assert sync_db.get(ReferenceSnapshot, "sigma").content["last_error"]
    assert sync_db.scalar(select(func.count()).select_from(SigmaRule)) == 1200


def test_task_disabled(monkeypatch):
    monkeypatch.setenv(
        "SIGMA__SYNC_ENABLED", "false"
    )  # plus settings cache reset as other tests do
    assert sigma_task.sync() == {"skipped": "disabled"}
```

  `test_beat_schedule.py`: `"sigma-sync"` exists with queue `maintenance`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Real fetchers use `httpx` (timeout 60 s, `follow_redirects=True`, `User-Agent: vareon-intelligence`); `get_bytes` streams and raises past `MAX_BYTES`. Wrap `load_sigma_zip` in `session.begin_nested()` so a refused load leaves no partial rows; on any exception record the error and return `failed`. The task commits.
- [ ] **Step 4: Run** the new tests plus `uv run pytest tests/unit/test_config.py tests/unit/test_env_prod_template.py tests/unit/test_beat_schedule.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(worker): weekly SigmaHQ release sync`.

---

### Task 5: Pure pack builder (`cti_api/services/hunt_builder.py`)

**Files:**
- Create: `apps/api/src/cti_api/services/hunt_builder.py`
- Test: `tests/unit/test_hunt_builder.py`

**Interfaces:**
- Produces (plain frozen dataclasses, no ORM):
  - `Tier = Literal["primary", "inferred", "llm"]`
  - `AnchorIn(type: Literal["story", "entity"], id: int, title: str, entity_type: str | None)`
  - `TechniqueIn(attack_id: str, name: str, tier: Tier)`
  - `IndicatorIn(type: str, value: str, valid_until: datetime | None, tlp: str)`
  - `SigmaIn(id: str, title: str, level: str, status: str, author: str, ruleset: str, path: str, release: str, techniques: tuple[str, ...], logsource: dict[str, str])`
  - `CIM_MAP: tuple[CimDataset, ...]`, `CimDataset(key: str, types: frozenset[str], datamodel: str, fields: tuple[str, ...])`, exactly the spec 5.3 table; keys `network_traffic`, `dns`, `web_domain`, `web_url`, `endpoint_processes`, `endpoint_filesystem`, `email`; datamodel strings `Network_Traffic.All_Traffic`, `Network_Resolution.DNS`, `Web.Web`, `Web.Web`, `Endpoint.Processes`, `Endpoint.Filesystem`, `Email.All_Email`
  - `CHUNK = 200`
  - `merge_tiers(items: Iterable[TechniqueIn]) -> list[TechniqueIn]` (strongest tier per id, `primary` > `inferred` > `llm`; sorted by id)
  - `spl_quote(value: str) -> str | None` (None when the value contains `*` or any character below 0x20)
  - `SplSearch(dataset: str, chunk: int, value_count: int, query: str)`; `build_spl(indicators: list[IndicatorIn]) -> tuple[list[SplSearch], int]` (searches, skipped value count)
  - `SigmaMatch(id, title, level, status, author, ruleset, link, techniques, logsource, match: Literal["exact", "sub", "parent"], via_technique: str)`; `select_sigma(techniques: list[TechniqueIn], rules: list[SigmaIn], include: set[str]) -> list[SigmaMatch]` (one entry per rule with its best match kind; order per spec 5.3)
  - `group_iocs(indicators: list[IndicatorIn]) -> dict[str, list[IndicatorIn]]` (per dataset key; an indicator appears in each matching dataset; unmapped types under `"other"`; values sorted)
  - `HuntPack` with the fields of spec 5.3 "HuntPack (JSON)"; `build_pack(anchor: AnchorIn, techniques: list[TechniqueIn], indicators: list[IndicatorIn], sigma_rules: list[SigmaIn], *, include: set[str], sigma_release: str | None, truncated: bool, now: datetime) -> HuntPack`
  - `pack_zip(pack: HuntPack, sigma_yaml: dict[str, str], license_text: str) -> bytes`

SPL per dataset and chunk: the template in spec 5.3, fields ORed (`<field> IN (<values>)`), `by` the dataset's fields, final `| convert ctime(first_seen) ctime(last_seen)`. IOC CSV header `type,value,valid_until,tlp` (`csv` module).

- [ ] **Step 1: Write failing tests**

```python
def test_spl_chunks_at_200():
    ips = [IndicatorIn("ip", f"10.0.{i // 256}.{i % 256}", None, "clear") for i in range(450)]
    searches, skipped = build_spl(ips)
    assert [s.value_count for s in searches] == [200, 200, 50] and skipped == 0
    assert searches[0].query.startswith("| tstats summariesonly=false count")
    assert "from datamodel=Network_Traffic.All_Traffic" in searches[0].query
    assert "All_Traffic.src IN (" in searches[0].query
    assert "All_Traffic.dest IN (" in searches[0].query


def test_spl_quotes_ipv6_and_spaces():
    assert spl_quote('a"b\\c') == '"a\\"b\\\\c"'
    assert spl_quote("2001:db8::1") == '"2001:db8::1"'
    assert spl_quote("http://x/a b") == '"http://x/a b"'
    assert spl_quote("http://x/*") is None and spl_quote("a\nb") is None


def test_skipped_values_counted():
    _, skipped = build_spl([IndicatorIn("url", "http://x/*", None, "clear")])
    assert skipped == 1


def test_domain_goes_to_dns_and_web():
    s, _ = build_spl([IndicatorIn("domain", "evil.example", None, "clear")])
    assert {x.dataset for x in s} == {"dns", "web_domain"}


def test_hashes_go_to_both_endpoint_datasets():
    s, _ = build_spl([IndicatorIn("sha256", "a" * 64, None, "clear")])
    assert {x.dataset for x in s} == {"endpoint_processes", "endpoint_filesystem"}


def test_unmapped_type_goes_to_other():
    ind = IndicatorIn("mutex", "x", None, "clear")
    assert group_iocs([ind]) == {"other": [ind]}
    assert build_spl([ind]) == ([], 0)


def test_merge_tiers_keeps_strongest():
    out = merge_tiers([TechniqueIn("T1059", "x", "llm"), TechniqueIn("T1059", "x", "primary")])
    assert out == [TechniqueIn("T1059", "x", "primary")]


def test_select_sigma_match_kinds_and_order():
    t = [
        TechniqueIn("T1059", "", "primary"),
        TechniqueIn("T1566.001", "", "primary"),
        TechniqueIn("T1190", "", "llm"),
    ]
    rules = [
        _sig("a", ["T1059.001"], level="medium"),
        _sig("b", ["T1566"], level="high"),
        _sig("c", ["T1059"], level="critical", ruleset="emerging-threats"),
        _sig("d", ["T1190"], level="critical"),
    ]
    got = select_sigma(t, rules, include=set())
    assert [(m.id, m.match) for m in got] == [("b", "parent"), ("a", "sub"), ("c", "exact")]
    assert "d" in [m.id for m in select_sigma(t, rules, include={"llm"})]
    assert got[0].link == "https://github.com/SigmaHQ/sigma/blob/r1/rules/b.yml"


def test_pack_zip_members_and_attribution():
    z = zipfile.ZipFile(io.BytesIO(pack_zip(_pack(), {"a": "title: a"}, "DRL TEXT")))
    names = set(z.namelist())
    assert {"README.md", "LICENSE.Detection.Rules.md", "sigma/a.yml"} <= names
    assert any(n.startswith("spl/") for n in names) and any(n.startswith("iocs/") for n in names)
    readme = z.read("README.md").decode()
    assert "Detection Rule License 1.1" in readme and "author" in readme.lower()


def test_build_pack_is_deterministic():
    assert build_pack(**_args()) == build_pack(**_args())
```

  (`_sig(id, techniques, level="high", status="test", ruleset="core")` uses `release="r1"`, `path=f"rules/{id}.yml"`.)
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_hunt_builder.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `uv run ruff check apps/api` clean.
- [ ] **Step 5: Commit** `feat(api): pure hunting pack builder (CIM SPL, Sigma selection, zip)`.

---

### Task 6: Collectors, web and machine endpoints, scope `hunt:read`

**Files:**
- Create: `apps/api/src/cti_api/services/hunt_pack.py`, `apps/api/src/cti_api/schemas/hunt.py`
- Create: `apps/api/src/cti_api/routers/hunt_packs.py` (v1, JWT), `apps/api/src/cti_api/routers/v2_hunt_packs.py`
- Modify: `apps/api/src/cti_api/main.py` (include routers), `apps/api/src/cti_api/machine_auth.py` (`API_TOKEN_SCOPES` += `"hunt:read"`)
- Modify (regenerated): `docs/openapi.json`, `apps/web/src/lib/api/schema.d.ts`
- Test: `tests/integration/test_hunt_packs_api.py`

**Interfaces:**
- Consumes: Task 5 builder; `inferred_ttps.for_article(session, article) -> list[InferredEntity]`; `EntityMention`, `Entity`, `Relationship`, `Indicator` (`state` hybrid), `IndicatorSource`, `Story`, `Article`, `SigmaRule`, `ReferenceSnapshot`; `tlp_allowed(max_tlp)` from `cti_core.indicator.marking`; `require_token`, `require_permission`.
- Produces:
  - `ENTITY_ANCHOR_TYPES = ("intrusion-set", "malware", "tool", "campaign", "attack-pattern")`, `ENTITY_INDICATOR_CAP = 2000`
  - `class AnchorNotFound(Exception)`, `class AnchorMerged(Exception)` (attribute `into_id: int`)
  - `Collected(anchor: AnchorIn, techniques: list[TechniqueIn], indicators: list[IndicatorIn], truncated: bool)`
  - `collect_story(session, story_id: int, *, max_tlp: str | None) -> Collected`; `collect_entity(session, entity_id: int, *, days: int, max_tlp: str | None) -> Collected` (`max_tlp=None` = no TLP filter, web)
  - `get_pack(session, anchor_type: Literal["story", "entity"], anchor_id: int, *, include: set[str], days: int, max_tlp: str | None) -> HuntPack`
  - `get_pack_zip(session, ...same params...) -> bytes` (loads `SigmaRule.yaml` for the selected rules and the committed `LICENSE.Detection.Rules.md`)
  - Routes `GET /api/hunt-packs/{anchor_type}/{anchor_id}` (`require_permission("view_ioc")`) and `GET /api/v2/hunt-packs/{anchor_type}/{anchor_id}` (`require_token("hunt:read")`); query `include: list[Literal["inferred", "llm"]] = []`, `days: int = Query(90, ge=1, le=365)`, `format: Literal["json", "zip"] = "json"`; zip response `application/zip`, `Content-Disposition: attachment; filename="hunt-<anchor_type>-<id>.zip"`. `AnchorNotFound` → 404; `AnchorMerged` → 404 whose details carry `merged_into_id` (v2 through the existing `/api/v2` error handler, v1 as `detail={"message": ..., "merged_into_id": ...}`).
  - Response schema `HuntPackOut` mirrors `HuntPack`; the JSON pack never carries Sigma YAML (only the zip does).

Collector rules: spec 5.1 and 5.2. Inferred: each `InferredEntity.techniques` item → `TechniqueIn(attack_id, name, "inferred")`. Story members: `Article.story_id == story_id`. Entity indicators: indicators whose `indicator_sources.article_id` is an article with an `EntityMention` of the entity and whose story `last_seen_at` (or, without a story, the article's `published_at`) is within `days`, union indicators with a non-revoked `indicates` relationship to the entity; ordered by `last_seen_at desc`, `limit 2001` to detect truncation. Sigma candidates: `SigmaRule.techniques && <ids incl. parents of sub-techniques>` (GIN `&&`), plus rules with `T####.%` children for parent techniques (`EXISTS (select from unnest(techniques) t where t like 'T1059.%')`), then filtered by `select_sigma`.

- [ ] **Step 1: Write failing tests** (seed helpers from `tests/integration/entity_support.py`; token helper as in `tests/integration/test_v2_indicators.py`; Sigma rows seeded directly)

```python
async def test_story_pack_tiers_and_active_only(client, web_headers, seeded_story):
    # seeded_story: explicit T1059, llm T1190, actor whose ATT&CK `uses` T1566;
    # ip 198.51.100.7 active, domain revoked, url expired; Sigma rules for T1059 and T1190
    body = (await client.get(f"/api/hunt-packs/story/{seeded_story.id}", headers=web_headers)).json()
    assert {t["attack_id"]: t["tier"] for t in body["techniques"]} == {
        "T1059": "primary", "T1566": "inferred", "T1190": "llm"}
    assert [i["value"] for i in body["iocs"]["network_traffic"]] == ["198.51.100.7"]
    assert all(m["via_technique"] != "T1190" for m in body["sigma"])

async def test_story_pack_include_llm_adds_sigma(...):
    body = (await client.get(f"/api/hunt-packs/story/{sid}?include=llm", headers=h)).json()
    assert any(m["via_technique"] == "T1190" for m in body["sigma"])

async def test_story_pack_without_techniques(...):  # indicators only, no sigma rows
    assert r.status_code == 200 and r.json()["sigma"] == []

async def test_v2_tlp_filter(...):  # amber 203.0.113.9 in the story, token max_tlp=clear
    assert r.status_code == 200 and "203.0.113.9" not in r.text

async def test_v2_scope_required(...):  # token with only indicators:read
    assert r.status_code == 403

async def test_entity_pack_relationships_and_window(...):
    # intrusion-set with ATT&CK `uses` T1059; indicator from a story 30 d ago in, 200 d ago out
async def test_entity_pack_truncated(...):  # 2,001 indicators -> 2,000 and truncated is True
async def test_merged_entity_404(...):
    assert r.status_code == 404
    assert r.json()["error"]["details"]["merged_into_id"] == target_id
async def test_unsupported_entity_type_404(...):  # a `location` entity
async def test_zip_format(...):
    assert r.headers["content-type"] == "application/zip"
    assert "sigma/" in "".join(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
```

- [ ] **Step 2: Run** `uv run pytest tests/integration/test_hunt_packs_api.py -q` → FAIL.
- [ ] **Step 3: Implement** the service, schemas and routers; add the scope.
- [ ] **Step 4: Run** the new tests plus `uv run pytest tests/unit/test_route_permissions.py tests/integration/test_v2_indicators.py tests/integration/test_taxii.py -q` → PASS.
- [ ] **Step 5: Regenerate contract**: `uv run python tools/export_openapi.py && (cd apps/web && pnpm run gen:api)`; `git diff --stat` shows only hunt-pack additions and the scope enum.
- [ ] **Step 6: Commit** `feat(api): hunting pack endpoints for web and machine API`.

---

### Task 7: On-demand LLM hunt hypothesis

**Files:**
- Create: `apps/api/src/cti_api/services/hunt_hypothesis.py`
- Modify: `apps/api/src/cti_api/routers/hunt_packs.py`, `apps/api/src/cti_api/schemas/hunt.py`, contract files
- Test: `tests/integration/test_hunt_hypothesis.py`

**Interfaces:**
- Consumes: `collect_story`/`collect_entity` (Task 6), `get_llm_client(task="hunt_hypothesis")`, `prompt_version` (as `services/ta_profile.py`), `HuntHypothesis`, the audit-log helper used by `POST /api/entities/{id}/profile`.
- Produces: `_call_llm(user_msg: str) -> str`; `generate_hypothesis(session, anchor_type: Literal["story", "entity"], anchor_id: int, *, username: str) -> HuntHypothesis`; routes `GET /api/hunt-packs/{anchor_type}/{anchor_id}/hypothesis` (`view_ioc`, 404 when none) and `POST` (`manage_intel`, audit action `hunt_hypothesis_generate`); schema `HuntHypothesisOut(text: str, model: str, generated_at: datetime, generated_by: str)`.

System prompt (English): write 3-5 hunt hypotheses for a SOC, each with the behaviour to look for, the data needed and the ATT&CK id; plain text. User message: title; story summary or entity description truncated to 2,000 characters; `primary` techniques as `T#### Name` lines; dataset keys that have indicators. `_call_llm` runs via `asyncio.to_thread`. Any LLM exception → 502 and the stored row is unchanged.

- [ ] **Step 1: Write failing tests** (monkeypatch `hunt_hypothesis._call_llm`)

```python
async def test_generate_and_read(client, analyst_headers, viewer_headers, seeded_story, monkeypatch):
    seen: dict[str, str] = {}
    def fake(msg: str) -> str:
        seen["m"] = msg
        return "H1"
    monkeypatch.setattr(hunt_hypothesis, "_call_llm", fake)
    url = f"/api/hunt-packs/story/{seeded_story.id}/hypothesis"
    r = await client.post(url, headers=analyst_headers)
    assert r.status_code == 200 and r.json()["text"] == "H1"
    assert "198.51.100.7" not in seen["m"] and "T1059" in seen["m"]
    assert (await client.get(url, headers=viewer_headers)).json()["text"] == "H1"

async def test_regenerate_replaces(...):  # second POST -> still one row, new text
async def test_llm_error_502_keeps_row(...):
async def test_post_needs_manage_intel(...):  # viewer -> 403
async def test_hypothesis_not_in_v2_pack(...):
    assert "hypothesis" not in r.text.lower()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; regenerate the contract.
- [ ] **Step 5: Commit** `feat(api): on-demand LLM hunt hypothesis`.

---

### Task 8: Data health Sigma block

**Files:**
- Modify: `apps/api/src/cti_api/services/data_health.py`, `apps/api/src/cti_api/schemas/data_health.py`, contract files
- Test: the integration test file that covers `/api/data-health` today (extend it)

**Interfaces:**
- Produces: `SigmaHealthOut(release: str | None, rules: int, fetched_at: str | None, last_error: str | None, status: Literal["ok", "amber", "red"])` as `DataHealthOut.sigma`. `red` when 0 rules; `amber` when `fetched_at` is older than 60 days or `last_error` is set; else `ok`.

- [ ] **Step 1: Write failing tests** for the three statuses (seed `SigmaRule` rows and `ReferenceSnapshot("sigma")`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; regenerate the contract.
- [ ] **Step 5: Commit** `feat(api): show Sigma snapshot health`.

---

### Task 9: Web — Hunt panel, entity tab, newsroom section, Data health card, token scope

**Files:**
- Create: `apps/web/src/components/hunt/hunt-panel.tsx` (props `{ anchorType: "story" | "entity"; anchorId: number }`), `apps/web/src/components/hunt/hunt-hypothesis.tsx`
- Modify: `apps/web/src/components/entities/entity-view.tsx` (`TabKey` `"hunt"`, shown for the five anchor entity types), `apps/web/src/components/newsroom/article-modal.tsx` (`<HuntPanel anchorType="story" anchorId={...} />` next to `InferredTtpsSection` when the article has a story), `apps/web/src/components/data-health/data-health-view.tsx` (Sigma card), the API token create form under `apps/web/src/app/(app)/admin/api-tokens/` (scope option `hunt:read`, label "Hunting packs")

Behaviour (spec 7.1): checkboxes `inferred`/`llm` refetch with `include`; one card per SPL search with header `<dataset> · <n> values` and a copy button; Sigma table (title, level, status, author, link in a new tab, logsource); *Download pack* fetches `?format=zip` through `/api/proxy` and saves the blob; per-dataset CSV built client-side from `iocs`; attribution line "Sigma rules by their authors, licensed under the Detection Rule License 1.1" with links to SigmaHQ and the licence; a note when `truncated`; when `counts.skipped_values > 0`, a note that values containing `*` were left out of SPL. Hypothesis panel: stored draft with an "LLM draft" badge, model and time; *Draft hypothesis* / *Regenerate* only for users with `manage_intel`. In the newsroom the section is hidden when the pack has no techniques and no indicators.

- [ ] **Step 1: Implement** with the existing patterns (`entity-attack-tab.tsx` for data fetching through the proxy, `TabPills`, `Badge`, `Dialog` per `apps/web/CLAUDE.md`).
- [ ] **Step 2: Verify**: `export PATH="$(ls -d ~/.local/share/fnm/node-versions/*/installation/bin | tail -1):$PATH"; cd apps/web && pnpm lint && pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm build` → all pass.
- [ ] **Step 3: Manual check** on the isolated `qap7e` stack with seeded data: entity Hunt tab and newsroom section in light, dark and 375 px; copy, zip download, include toggles, hypothesis button.
- [ ] **Step 4: Commit** `feat(web): hunting pack panel on entities and stories`.

---

### Task 10: Docs and release notes

**Files:**
- Modify: `CHANGELOG.md` (`## [0.8.11]`, Indonesian P7e bullets); `docs/prod-upgrade/0.8.11.md` (P7e content under all eight headings: two tables, optional `SIGMA__SYNC_ENABLED`, after deploy `select count(*) from sigma_rules` and the Data health Sigma card, outbound `api.github.com`/`github.com` only for the weekly sync, `cti-sigma import` for hosts without outbound access, rollback leaves the tables); the 0.8.11 part of `docs/PROD_UPGRADE_0.8.2_TO_0.8.11.md`; `docs/LLM_ASSIST_REDESIGN.md` (section 4 item 6 and the section 5 P7+ row: P7e built for 0.8.11, link to the spec); the P7e row of the table in `docs/superpowers/specs/2026-10-28-p7a-indicator-lifecycle-design.md`; `docs/ARCHITECTURE.md` (one paragraph on hunting packs and the Sigma sync); the P7e spec status line ("approved, built for 0.8.11").
- Test: existing doc/config tests.

- [ ] **Step 1: Edit the docs.**
- [ ] **Step 2: Full check**: `uv run ruff check . && uv run ruff format --check . && uv run mypy packages/cti-core/src packages/cti-scraper/src && uv run pytest tests/unit tests/contract packages -q --deselect tests/contract/test_golden.py::test_golden_trendmicro` → pass; `uv run pytest tests/integration -q` in the background (~7 min) → pass.
- [ ] **Step 3: Commit** `docs: document P7e hunting packs for 0.8.11`.

---

## After the tasks (each step needs the user's approval)

1. Merge `claude/p7e-hunting-packs` into `origin/Dev` (Dev already contains P7g), deploy on dev, and run the spec section 8 "Dev" checks (read-only queries, web pages).
2. Open the PR from `claude/p7e-hunting-packs` to `main`.
