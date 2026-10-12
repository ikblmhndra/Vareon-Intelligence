/**
 * `/api/ta/stats` dan seluruh `/api/recap/*` balikin `dict[str, object]`
 * di backend (lihat `routers/ta_groups.py::ta_stats` dan
 * `routers/recap.py`) -- `schema.d.ts` generate tipe generik
 * `{[key: string]: unknown}` buat response-nya, gak ada shape asli.
 * Interface di bawah nge-declare shape RIIL yang dipakai (dicek langsung
 * dari `AsyncTARepo.get_ta_stats()` dan `cti_api.services.recap._to_dict`/
 * `SYSTEM_PROMPT` schema), bukan tebakan dari nama field lama.
 */

import type { components } from "./schema";

export interface NamedCount {
  name: string;
  count: number;
}

export interface TaStats {
  total_groups: number;
  total_whitelisted: number;
  manual_count: number;
  in_news_count: number;
  by_source: NamedCount[];
  top_in_news: NamedCount[];
}

export interface RecapTopStory {
  title: string;
  why_it_matters?: string;
  source?: string;
  /** Id artikel yang dipakai cerita ini dan URL-nya, ditulis KODE setelah grounding (PR 3). Recap
   * lama tidak punya keduanya: judulnya tampil tanpa tautan. */
  article_id?: number;
  url?: string;
}

export interface RecapTopTweet {
  author?: string;
  summary?: string;
  signal?: string;
}

export interface RecapActiveCampaign {
  theme?: string;
  article_count?: number;
  why_it_matters?: string;
}

export interface RecapLikelyEvent {
  /** `f1`, `f2`, ... menurut posisinya; kunci scorecard pekan berikutnya. Baris lama tidak punya. */
  id?: string;
  event?: string;
  basis?: string;
  confidence?: string;
}

export interface RecapBody {
  summary?: string;
  top_stories?: RecapTopStory[];
  top_tweets?: RecapTopTweet[];
  active_threat_actors?: string[];
  notable_cves?: string[];
  active_campaigns?: RecapActiveCampaign[];
  apac_signals?: string[];
}

export interface RecapForecast {
  summary?: string;
  likely_events?: RecapLikelyEvent[];
  watch_items?: string[];
}

export interface RecapCounts {
  articles?: number;
  tweets?: number;
  iocs?: number;
  cves?: number;
  campaigns?: number;
  new_threat_actors?: number;
}

/** Penunjuk ke satu recap mingguan (`quality.comparison.previous`, `quality.scorecard.reviewed`). */
export interface RecapWeekRef {
  date: string;
  period_start: string;
  period_end: string;
}

/** Selisih satu kunci `counts`. `delta_pct` null kalau pekan lalu 0 (tak ada persen yang berarti). */
export interface RecapCountDelta {
  current: number;
  previous: number;
  delta: number;
  delta_pct: number | null;
}

export interface RecapComparison {
  previous: RecapWeekRef;
  /** Kunci: `articles`, `tweets`, `iocs`, `cves`, `campaigns`, `new_threat_actors`. */
  counts: Record<string, RecapCountDelta>;
  new_this_week: { threat_actors?: string[]; campaigns?: string[]; cves?: string[] };
}

export type RecapDropReason = "not_in_input" | "malformed" | "no_article_id" | "unknown_article_id";

/** Satu item keluaran model yang dibuang cek grounding; `field` mis. `top_stories`, `notable_cves`. */
export interface RecapDropped {
  field: string;
  value: string;
  reason: RecapDropReason | (string & {});
}

export interface RecapGrounding {
  dropped: RecapDropped[];
  count: number;
}

export type RecapVerdict = "happened" | "partly" | "not_happened" | "unclear";

export interface RecapScorecardEvent {
  /** Id event forecast pekan sebelumnya (`f1`, ...): bagian URL override. */
  id: string;
  event: string;
  basis: string;
  confidence: string;
  /** Verdict MODEL; yang berlaku = `override?.verdict ?? verdict`. */
  verdict: RecapVerdict;
  evidence: string;
  override?: { verdict: RecapVerdict; by: string; at: string };
}

export interface RecapScorecard {
  /** Pekan yang forecast-nya di-review (pekan sebelum recap yang memuat scorecard ini). */
  reviewed: RecapWeekRef;
  events: RecapScorecardEvent[];
}

/** `RecapDoc.quality` (PR 3): tiap blok opsional (recap lama dan pekan pertama tidak punya). */
export interface RecapQuality {
  comparison?: RecapComparison;
  grounding?: RecapGrounding;
  scorecard?: RecapScorecard;
}

export interface RecapHitBucket {
  events: number;
  /** `events - unclear`: penyebut hit rate. */
  judged: number;
  unclear: number;
  /** `happened` = 1, `partly` = 0.5, jadi bisa pecahan. */
  hits: number;
  /** null kalau belum ada event yang dinilai (`judged` = 0). */
  rate_pct: number | null;
}

/** `hit_rate` di balasan `/latest`, `/{date}?kind=weekly`, dan override: 8 recap mingguan terakhir. */
export interface RecapHitRate {
  weeks: number;
  reviewed_weeks: number;
  first_week: string | null;
  last_week: string | null;
  overall: RecapHitBucket;
  by_confidence: { low: RecapHitBucket; med: RecapHitBucket; high: RecapHitBucket };
}

/** Amplop balasan `/latest`, `/{date}`, `/generate` dan override. `hit_rate` hanya ada di yang
 * mingguan (recap harian tidak punya scorecard) dan tidak ada di `/generate`. */
export interface RecapEnvelope {
  recap: RecapDoc | null;
  hit_rate?: RecapHitRate;
}

/** `weekly` = recap terjadwal satu pekan Senin-Minggu (UTC), `date` = Senin-nya; `daily` = satu
 * hari yang dipicu tangan. Dua jenis boleh berbagi `date`, jadi semua baca/pilih menyebut `kind`. */
export type RecapKind = "daily" | "weekly";

export interface RecapDoc {
  id: number;
  kind: RecapKind;
  date: string;
  period_start: string;
  period_end: string;
  headline: string;
  yesterday: RecapBody;
  forecast: RecapForecast;
  counts: RecapCounts;
  generated_at: string;
  model: string;
  /** `skipped`: pekan tanpa artikel/tweet/CVE, tidak ada panggilan LLM. */
  token_usage: { total_tokens?: number; skipped?: boolean };
  /** Selalu ada dari API, tapi `{}` di recap lama: semua bloknya opsional. */
  quality?: RecapQuality;
  raw_llm: string | null;
  cached: boolean;
}

export interface RecapListItem {
  date: string;
  kind: RecapKind;
  period_start: string;
  period_end: string;
  headline: string;
  counts: RecapCounts;
  generated_at: string;
}

/**
 * Grup C (`/xintel`, `/admin/users`) -- sisa endpoint yang response-nya
 * `dict[str,object]`/`list[dict[str,object]]` polos di backend (kebanyakan
 * `routers/auth.py`/`roles.py`/`clients.py` gak declare `response_model`
 * sama sekali). Shape dicek dari `_serialize()`/return dict tiap endpoint
 * langsung.
 */

export interface AuthorCount {
  author: string;
  count: number;
}

export interface TweetStats {
  total: number;
  top_authors: AuthorCount[];
}

export interface AdminUser {
  username: string;
  role: string;
  client_ids: string[];
  force_pw_change: boolean;
  last_sign_in: string | null;
  created_at: string;
}

export interface Permission {
  key: string;
  description: string;
}

export interface Role {
  name: string;
  display_name: string;
  permissions: string[];
  is_system: boolean;
  created_by: string | null;
  created_at: string;
}

export interface Client {
  client_id: string;
  name: string;
  countries: string[];
  created_at: string;
}

export interface AuditLogEntry {
  user: string;
  action: string;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  ip: string;
  timestamp: string;
}

export interface PasswordPolicy {
  min_length: number;
  require_upper: boolean;
  require_lower: boolean;
  require_number: boolean;
  require_symbol: boolean;
  hint?: string;
}

/**
 * Grup D (`/newsroom`) -- `RansomwareVictimOut` didefinisikan di
 * `schemas/ransomware.py` tapi router-nya (`GET /api/ransomware/victims`)
 * gak declare `response_model`, jadi model itu GAK NONGOL di
 * `openapi.json` sama sekali (`schema.d.ts` gak generate tipe-nya).
 * Field dicek langsung dari `_serialize()` di `routers/ransomware.py`.
 */
export interface RansomwareVictim {
  id: number;
  group_name: string;
  victim: string;
  domain: string | null;
  description: string | null;
  country_code: string | null;
  industry: string | null;
  published: string | null;
  discovered: string | null;
  post_url: string;
  ransom: string | null;
  data_size: string | null;
  screenshot: string | null;
}

/**
 * Grup E (`/cve` -- CVE core+ticket+lookup) -- `routers/cve.py` endpoint
 * di bawah gak declare `response_model`, shape dicek dari test snapshot
 * riil (`tests/integration/__snapshots__/test_cve_router_snapshot.ambr`)
 * BUKAN tebakan dari nama field lama -- lihat gotcha `CveTicket` vs
 * `CveTracker` keduanya punya field `active_exploitation` yang TIDAK
 * berelasi (satu bool machine-set, satu string soft-enum analyst-set).
 */
export interface CveTicket {
  ticket_id: string;
  cve_id: string;
  affected_asset: string;
  affected_version: string;
  fixed_version: string;
  asset_owner: string;
  owner_email: string;
  owner_team: string;
  active_exploitation: string;
  remediation_date_plan: string;
  remediation_status: string;
  actual_remediation_date: string;
  escalation_required: boolean;
  comments: string;
  risk_acceptance: string;
  closure_date: string;
  acknowledged_by: string;
  acknowledge_time: string;
}

/** `GET /{cve_id}/ticket` balikin `{}` kalau belum ada ticket (port
 * apa adanya legacy, bukan 404) -- bukan error state. */
export type CveTicketResponse = CveTicket | Record<string, never>;

export interface AckStatusMap {
  [cveId: string]: string;
}

export interface CisaLookupResult {
  checked: number;
  matched: number;
  catalog_size: number;
  matched_cves: string[];
}

export interface EpssLookupResult {
  checked: number;
  scored: number;
  no_data: number;
}

export interface ExploitLookupBulkResult {
  checked: number;
  with_exploits: number;
  total_found: number;
  errors: number;
  details: { cve_id: string; found: number; error?: string }[];
}

export interface ExploitLookupSingleResult {
  cve_id: string;
  found: number;
  error?: string;
}

export interface DraftEmailResult {
  email_id: string;
  method: string;
  subject: string;
  cve_count: number;
}

export interface BulkAcknowledgeResult {
  ok: boolean;
  acknowledged: number;
}

/** `bulk-false-positive` balikin HTTP 200 dengan `ok:false` buat
 * validasi gagal (bukan HTTPException) -- cek `.ok`, bukan status. */
export interface BulkFalsePositiveResult {
  ok: boolean;
  marked?: number;
  detail?: string;
}

/**
 * Grup E (`/cve` -- Tech Stack subview) -- `routers/techstack.py`
 * endpoint mutasi gak declare `response_model`.
 */
export interface TechStackActionResult {
  success: boolean;
  reason?: string;
  item?: components["schemas"]["TechStackOut"];
}

export interface TechStackSuccessFlag {
  success: boolean;
}

/**
 * Grup E (`/cve` -- Package Vulnerability subview) --
 * `routers/pkg_vuln.py` endpoint mutasi/aksi gak declare `response_model`.
 */
export interface PkgAddResult {
  success: boolean;
  id?: number;
  name?: string;
  ecosystem?: string;
  version?: string | null;
}

export interface PkgPatchResult {
  success: boolean;
  changed: boolean;
  rescan?: boolean;
  id?: number;
  name?: string;
  ecosystem?: string;
  version?: string | null;
}

export interface PkgDeleteResult {
  success: boolean;
  deleted?: string;
}

export interface PkgTaskStartedResult {
  started: boolean;
  package?: string;
  ecosystem?: string;
  version?: string | null;
}

export interface PkgVulnStats {
  packages: number;
  total_vulns: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  unacknowledged: number;
  kev_count: number;
}

export interface PkgVulnAckResult {
  success: boolean;
  acknowledged: boolean;
}

/**
 * Grup F (`/exec`) -- `routers/exec_dashboard.py` gak declare
 * `response_model` (return `dict[str, object]`), shape dicek dari
 * `services/exec_dashboard.py::get_exec_dashboard()`/
 * `get_exec_dashboard_v2()` + snapshot test
 * `tests/integration/__snapshots__/test_exec_dashboard_router_snapshot.ambr`.
 */
export interface ExecTrendSeries {
  data: number[];
  [key: string]: unknown;
}

export interface ExecNamedCount {
  name: string;
  count: number;
}

export interface ExecCveExposureRow {
  tech: string;
  total: number;
  critical: number;
  high: number;
  medium: number;
  max_cvss?: number | null;
  poc_count?: number;
}

/** v1 (`GET /api/exec/dashboard`, TANPA auth -- sengaja, lihat docstring
 * router). */
export interface ExecDashboardV1 {
  total_incidents: number;
  prev_total: number;
  unique_ta_count: number;
  prev_unique_ta: number;
  active_sectors: number;
  prev_active_sectors: number;
  months: string[];
  top_sectors: string[];
  top_countries: string[];
  sector_trend: ({ sector: string } & ExecTrendSeries)[];
  country_trend: ({ country: string } & ExecTrendSeries)[];
  ta_leaderboard: ExecNamedCount[];
  news_type_breakdown: ExecNamedCount[];
  sector_heatmap: { sector: string; months: { month: string; count: number }[] }[];
  heatmap_max: number;
  cve_exposure: ExecCveExposureRow[];
}

export interface ExecViewConfig {
  role: string;
  sections: {
    kpis: boolean;
    sector_risk: boolean;
    ta_leaderboard: boolean;
    exec_brief_button: boolean;
    source_reliability_spread: boolean;
    cluster_list: boolean;
    ioc_enrichment_hits: boolean;
    fp_feedback_queue: boolean;
    critical_cve_feed: boolean;
    live_ioc_stream: boolean;
    sigma_export_quick: boolean;
    spike_alerts: boolean;
  };
}

/** v2 (`GET /api/exec/dashboard-v2`, auth required) -- spread semua
 * field v1 + field di bawah. 4 field role-gated (`critical_cves`/
 * `recent_clusters_summary`/`pending_fp_queue`/
 * `source_reliability_spread`) SELALU ada tapi isinya `[]`/`{}` kalau
 * `view_config.sections.*` false buat role efektif -- cek section flag
 * itu buat bedain "gak berhak lihat" vs "emang belom ada data". */
export interface ExecDashboardV2 extends ExecDashboardV1 {
  prev_ta_names: string[];
  sector_risk_scores: { sector: string; risk_score: number }[];
  cve_exposure_v2: ExecCveExposureRow[];
  /** Total UTUH buat dua kartu KPI (BUKAN jumlah 10 tech di `cve_exposure_v2`): CVE berseverity
   * critical, dan CVE ber-flag KEV (semua severity). Cakupannya sama dengan tabel exposure
   * (lintas client, tanpa baris FP). */
  cve_kpis: { critical: number; kev: number };
  industry_spikes: {
    entity: string;
    date: string;
    count: number;
    baseline_mean: number;
    z_score: number;
    severity: "high" | "medium";
  }[];
  victim_country_trend: ({ country: string } & ExecTrendSeries)[];
  top_ttps: { id: string; name: string; count: number }[];
  ta_velocity: {
    actor: string;
    velocity_pct: number;
    last_month: number;
    avg_prev: number;
    total: number;
  }[];
  sector_cooccurrence: { sector_a: string; sector_b: string; count: number }[];
  newstype_trend: { months: string[]; series: ({ type: string } & ExecTrendSeries)[] };
  sector_actor_matrix: { sectors: string[]; actors: string[]; matrix: number[][]; max_val: number };
  ta_confidence: Record<string, number>;
  confirmed_incident_rate: number | null;
  view_config: ExecViewConfig;
  critical_cves: { cve_id: string; cve_score: number; cve_severity: string; cisa_kev: boolean; tech: string }[];
  recent_clusters_summary: {
    cluster_id: string;
    summary_title: string;
    size: number;
    threat_actors: string[];
    last_seen: string;
  }[];
  /** `id` ditambahin Fase 8 Grup F (2026-09-25) -- sebelumnya gak
   * ke-serialize, padahal wajib buat manggil `POST
   * /api/iocs/{ioc_id}/feedback` (kontrak baru). */
  pending_fp_queue: { id: number; value: string; type: string; last_seen: string; confidence_score: number }[];
  source_reliability_spread: Record<string, number>;
}

export interface ExecBriefResponse {
  brief: string;
  generated_at: string;
}

/**
 * `POST /api/iocs/{ioc_id}/feedback` -- request body typed penuh
 * (`FeedbackBody` di `schema.d.ts`), tapi response `ioc_feedback()`
 * gak declare `response_model`. Shape = `_serialize_detail()`
 * (`routers/iocs.py`).
 */
export interface IocFeedbackResponse {
  id: number;
  type: string;
  value: string;
  first_seen: string;
  last_seen: string;
  seen_count: number;
  tags: string[];
  threat_actors: string[];
  tp_count: number;
  fp_count: number;
  confidence_score: number;
  actionability_score: number;
  actionability_label: string;
  recommended_action: string;
  auto_suppressed: boolean;
  suppression_reason: string | null;
  sources: { url: string; source_name: string; context: string; article_id: number | null; first_seen: string }[];
  source_fp_warning?: {
    source_name: string;
    fp_rate: number;
    fp_count: number;
    total_iocs: number;
  };
}

/**
 * Grup G1 (`/intelligence` -- Risk Matrix, Early Warning) -- endpoint
 * `routers/intelligence.py` gak declare `response_model`. Shape dicek
 * dari `services/spike.py::get_spikes()`/`services/risk_matrix.py::
 * _compute_risk_matrix()` langsung.
 */
export interface SpikeEntry {
  entity: string;
  date: string;
  count: number;
  baseline_mean: number;
  z_score: number;
  severity: "high" | "medium";
}

export interface SpikesResponse {
  threat_actors: SpikeEntry[];
  countries: SpikeEntry[];
  industries: SpikeEntry[];
  overall: SpikeEntry[];
  generated_at: string;
  parameters: { lookback_days: number; z_threshold: number; recent_window: number };
}

export interface RiskMatrixCell {
  industry: string;
  country: string;
  risk_score: number;
  trend: "↑" | "↓" | "→";
  current_count: number;
  previous_count: number;
  top_actors: string[];
}

export interface RiskMatrixResponse {
  matrix: RiskMatrixCell[];
  industries: string[];
  countries: string[];
  generated_at: string;
}

/** Grup G1 (`/intelligence` -- Source Reliability) -- `GET /api/sr/stats`
 * gak declare `response_model` (`routers/source_reliability.py`). Shape
 * dicek dari `AsyncSourceReliabilityRepo.get_stats()`. */
export interface SrStats {
  total: number;
  by_grade: { grade: string; count: number }[];
}

/** `POST/PUT /api/sr/entries*` gak declare `response_model`. */
export interface SrActionResult {
  success: boolean;
  reason?: string;
  entry?: components["schemas"]["SREntryOut"];
}

/**
 * Grup G2 (`/intelligence` -- PIR + RFI) -- endpoint di bawah gak
 * declare `response_model`. Shape dicek dari `routers/pir.py`/
 * `routers/rfi.py` langsung (`_build_export_data()`/`{"deleted": bool}`).
 */
export interface PirExportData {
  pir: components["schemas"]["PIROut"];
  exported_at: string;
  total_articles: number;
  articles: {
    _id: string;
    title: string;
    url: string;
    posted_on: string | null;
    source: string;
    news_type: string | null;
    threat_actors: string[];
    impacted_industries: string[];
    mentioned_countries: string[];
    analyst_note: { note?: string; analyst?: string; updated_at?: string };
  }[];
}

export interface DeletedResult {
  deleted: boolean;
}

/**
 * Grup G3 (`/intelligence` -- MITRE heatmap + ATT&CK DB) --
 * `routers/mitre.py`/`routers/attack.py` gak declare `response_model`
 * di endpoint manapun (return `dict[str,object]`/`list[dict]` polos).
 * Shape dicek dari `AsyncMitreHeatmapRepo`/`AsyncAttackSyncRepo`/
 * `AsyncAttackQueryRepo` + model kolom langsung
 * (`packages/cti-core/src/cti_core/db/models/attack.py`).
 */
export interface MitreHeatmapTtp {
  id: string;
  name: string;
}

export interface MitreHeatmapResponse {
  rows: string[];
  ttps: MitreHeatmapTtp[];
  matrix: number[][];
  max_val: number;
}

export interface MitreArticle {
  _id: string;
  title: string;
  url: string;
  posted_on: string | null;
  source: string;
  news_type: string | null;
}

export interface MitreArticlesResponse {
  articles: MitreArticle[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttackDomainStatus {
  domain_key: string;
  domain?: string;
  label: string;
  stix_domain?: string;
  status: "never" | "syncing" | "success" | "error";
  version: string | null;
  mitre_modified?: string | null;
  last_attempted?: string | null;
  last_sync: string | null;
  error?: string | null;
  phase?: string | null;
  bytes_downloaded?: number | null;
  bytes_total?: number | null;
  download_pct?: string | null;
  technique_count?: number;
  tactic_count?: number;
  mitigation_count?: number;
  group_count?: number;
  software_count?: number;
  relationship_count?: number;
  delta_technique_count?: number | null;
  delta_group_count?: number | null;
  delta_software_count?: number | null;
  delta_mitigation_count?: number | null;
}

export interface AttackTechniqueRow {
  attack_id: string;
  name: string;
  url: string;
  tactics: string[];
  is_subtechnique: boolean;
  parent_id: string | null;
  platforms: string[];
  domains: string[];
}

export interface AttackTechniqueDetail extends AttackTechniqueRow {
  description: string;
  detection: string;
  mitigations: { mitigation_id: string; name: string; description: string }[];
  groups: { group_id: string; name: string }[];
  software: { software_id: string; name: string; software_type: string }[];
  sub_techniques: { attack_id: string; name: string }[];
}

export interface AttackTechniquesResponse {
  techniques: AttackTechniqueRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttackGroupRow {
  group_id: string;
  name: string;
  aliases: string[];
  url: string;
  domains: string[];
}

export interface AttackGroupDetail extends AttackGroupRow {
  description: string;
  techniques: { attack_id: string; name: string; tactics: string[]; context: string }[];
  software: { software_id: string; name: string; software_type: string }[];
}

export interface AttackGroupsResponse {
  groups: AttackGroupRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttackSoftwareRow {
  software_id: string;
  name: string;
  software_type: string;
  aliases: string[];
  url: string;
  platforms: string[];
  domains: string[];
}

export interface AttackSoftwareDetail extends AttackSoftwareRow {
  description: string;
  groups: { group_id: string; name: string }[];
  techniques: { attack_id: string; name: string }[];
}

export interface AttackSoftwareResponse {
  software: AttackSoftwareRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttackMitigationRow {
  mitigation_id: string;
  name: string;
  description: string;
  domains: string[];
}

export interface AttackMitigationsResponse {
  mitigations: AttackMitigationRow[];
  total: number;
  page: number;
  page_size: number;
}

export interface AttackSyncStartedResult {
  status: string;
  domains?: string[];
  domain?: string;
}

export interface IocSummary {
  id: number;
  type: string;
  value: string;
  first_seen: string;
  last_seen: string;
  seen_count: number;
  tags: string[];
  threat_actors: string[];
  tp_count: number;
  fp_count: number;
  confidence_score: number | null;
  actionability_score: number | null;
  actionability_label: string | null;
  recommended_action: string | null;
  auto_suppressed: boolean;
  suppression_reason: string | null;
}

export interface IocEnrichmentProvider {
  key: string;
  name?: string;
  verdict?: string;
  score?: number;
  malware_families?: string[];
  tags?: string[];
  raw?: Record<string, string | number | null>;
}

export interface IocEnrichment {
  updated_at?: string;
  providers?: IocEnrichmentProvider[];
}

export interface IocSource {
  url: string;
  source_name: string;
  context: string | null;
  article_id: number | null;
  first_seen: string;
}

export interface IocDetail extends IocSummary {
  enrichment: IocEnrichment | null;
  sources: IocSource[];
  source_fp_warning?: { source_name: string; fp_rate: number; fp_count: number; total_iocs: number };
}

export interface IocListResponse {
  iocs: IocSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface IocStats {
  total: number;
  by_type: { type: string; count: number }[];
}

export interface IocAllowlistEntry {
  id: number;
  type: string;
  value: string;
  note: string | null;
  added_by: string;
  added_at: string;
}

export interface IocAllowlistResponse {
  entries: IocAllowlistEntry[];
}

export interface IocFpBucket {
  total_iocs: number;
  fp_count: number;
  fp_rate: number;
}

export interface IocFpSuggestion {
  ioc_type: string;
  value: string;
  allowlist_type: string;
  fp_count: number;
}

export interface IocFpAnalytics {
  fp_by_source: Record<string, IocFpBucket>;
  fp_by_type: Record<string, IocFpBucket>;
  suggested_allowlist: IocFpSuggestion[];
  fp_trend: { date: string; fp_count: number; total_count: number; fp_rate: number }[];
}

export interface IocTaLink {
  name: string;
  article_count: number;
  is_watched: boolean;
  source: "manual" | "both" | "article";
  attack_group_id?: string;
  attack_group_name?: string;
  attack_group_aliases?: string[];
  attack_group_domains?: string[];
}

export interface IocTaLinksResponse {
  threat_actors: IocTaLink[];
}

export interface MindmapDocResponse {
  feature_type: string;
  doc_id: string;
  title: string;
  mermaid_syntax: string;
  custom_syntax: string | null;
  display_syntax: string;
  generated_at: string | null;
  edited_at?: string | null;
}

export interface TaStats {
  total_groups: number;
  total_whitelisted: number;
  manual_count: number;
  in_news_count: number;
  by_source: { name: string; count: number }[];
  top_in_news: { name: string; count: number }[];
}

export interface TaGroupActionResult {
  success: boolean;
  reason?: "whitelisted" | "duplicate";
}

export interface TaTimeline {
  actor: string;
  months: string[];
  article_counts: number[];
  tweet_counts: number[];
  ransom_counts: number[];
  total_counts: number[];
  dormancy_state: "ACTIVE" | "DORMANT" | "RESURGENT";
  last_active_month: string | null;
  state_transitions: { month: string; from: string; to: string }[];
}

export interface TaKnownMalware {
  name: string;
  type?: string;
  notes?: string | null;
}

export interface TaExploitedVuln {
  cve_id: string;
  product?: string;
  notes?: string | null;
  _confirmed?: boolean;
  _cve_score?: number | null;
  _cve_severity?: string | null;
  _cisa_kev?: boolean;
  _poc_available?: boolean;
}

export interface TaProfile {
  _actor_name?: string;
  _generated_at?: string;
  profile_metadata?: { analyst_confidence?: string; tlp_marking?: string; source_document?: string };
  identity?: {
    primary_name?: string;
    aliases?: string[];
    tracking_ids?: { mitre_group_id?: string | null; other_ids?: string[] };
    actor_type?: string;
    sponsoring_nation?: string | null;
    affiliated_group?: string | null;
    first_observed?: string | null;
    last_active?: string | null;
    active_status?: string;
  };
  motivation?: {
    primary_motivation?: string;
    secondary_motivations?: string[];
    strategic_objectives?: string[];
    targeting_approach?: string;
  };
  targeting_profile?: {
    targeted_sectors?: string[];
    targeted_geographies?: string[];
    targeted_organization_types?: string[];
    high_value_assets_targeted?: string[];
  };
  capability_assessment?: {
    sophistication_level?: string;
    development_capability?: string;
    known_malware?: TaKnownMalware[];
    known_tools?: string[];
    exploited_vulnerabilities?: TaExploitedVuln[];
    attack_techniques?: Record<string, string[]>;
  };
  infrastructure?: {
    c2_patterns?: string[];
    hosting_preferences?: string[];
    known_iocs?: { ips?: string[]; domains?: string[]; hashes?: string[]; urls?: string[] };
    infrastructure_reuse?: string;
    infrastructure_notes?: string | null;
  };
  campaign_history?: {
    campaign_name?: string | null;
    date_range?: string;
    targeted_sectors?: string[];
    source_reference?: string;
  }[];
  detection_and_defense?: {
    detection_opportunities?: { layer?: string; description?: string; mitre_technique_ref?: string | null }[];
    recommended_mitigations?: { mitigation?: string; mitre_mitigation_id?: string | null; priority?: string }[];
  };
  organizational_relevance?: {
    sector_relevance?: string;
    relevance_rationale?: string;
    monitoring_priority?: string;
    recommended_actions?: { timeframe?: string; action?: string }[];
  };
  intelligence_gaps?: string[];
  references?: { title?: string; source?: string; url?: string | null; date?: string | null }[];
}

export interface TaProfileResponse {
  exists: boolean;
  profile: TaProfile | null;
}

export interface TaProfileGenerateResult {
  success: boolean;
  profile: TaProfile;
}

export interface ClusterArticleRef {
  id: number;
  title: string;
  url: string;
  source: string;
  posted_on: string;
}

export interface ClusterEntry {
  cluster_id: string;
  cluster_name: string;
  article_count: number;
  source_count: number;
  sources: string[];
  confidence: "low" | "medium" | "high";
  first_date: string;
  last_date: string;
  re_emerged: boolean;
  articles: ClusterArticleRef[];
}

export interface ClustersResponse {
  clusters: ClusterEntry[];
  total: number;
}

export interface PrioritizedCve {
  cve_id: string;
  cvss_score: number | null;
  severity: string | null;
  cisa_kev: boolean;
  poc_available: boolean;
  actively_exploited: boolean;
  in_tech_stack: boolean;
  priority_score: number;
  priority_label: "critical_patch" | "high_priority" | "medium" | "low";
  patch_urgency: string;
}

export interface MatchedPir {
  id: number;
  title: string;
  description: string | null;
  priority: string;
  status: string;
  criteria: Record<string, string[]>;
}

export interface KillChainPhase {
  phase: string;
  covered: boolean;
  techniques: string[];
}

export interface KillChain {
  phases_covered: string[];
  phases_missing: string[];
  completeness_score: number;
  completeness_label: "full_chain" | "partial_chain" | "limited";
  chain_visualization: KillChainPhase[];
  operational_risk: "critical" | "high" | "medium" | "low";
}

export interface SeverityBreakdown {
  ta_sophistication: number;
  ioc_confidence: number;
  cve_criticality: number;
  campaign_velocity: number;
  source_quality: number;
  raw: {
    ta_sophistication: number;
    ioc_confidence: number;
    cve_criticality: number;
    campaign_velocity: number;
    source_quality: number;
  };
}

export interface DiamondModel {
  adversary: { threat_actors: string[]; actor_types: string[]; sponsoring_nations: string[]; sophistication: string | null };
  infrastructure: { domains: string[]; ips: string[]; urls: string[]; c2_indicators: string[] };
  capability: { attack_techniques: Record<string, string[]>; malware: string[]; tools: string[]; cve_exploited: string[] };
  victim: { industries: string[]; countries: string[]; organization_types: string[] };
  meta: { timestamps: { first_seen: string; last_seen: string }; confidence: "high" | "medium" | "low"; direction: "lateral" | "outbound" | "inbound" };
}

export interface RelatedCampaign {
  cluster_id: string;
  cluster_name: string;
  link_score: number;
  link_type: "same_actor" | "shared_infra" | "similar_ttp" | "related";
  shared_elements: { tas: string[]; ttps: string[]; iocs: string[] };
}

export interface CampaignIoc {
  id?: number;
  type: string;
  value: string;
}

export interface CampaignEntry {
  cluster_id: string;
  cluster_name: string;
  size: number;
  first_seen: string;
  last_seen: string;
  member_article_ids: number[];
  titles: string[];
  summary_title: string;
  dominant_tas: string[];
  dominant_industries: string[];
  dominant_countries: string[];
  attack_techniques: string[];
  kill_chain: KillChain;
  iocs: CampaignIoc[];
  cve_ids: string[];
  prioritized_cves: PrioritizedCve[];
  velocity_articles_per_day: number;
  velocity_label: "surging" | "active" | "moderate" | "slow";
  acceleration: number;
  velocity_alert: boolean;
  new_iocs_24h: number;
  days_active: number;
  severity_score: number;
  severity_label: "critical" | "high" | "medium" | "low";
  severity_breakdown: SeverityBreakdown;
  matched_pirs: MatchedPir[];
  diamond_model: DiamondModel;
  related_campaigns: RelatedCampaign[];
}

export interface CampaignLink {
  source_id: string;
  target_id: string;
  score: number;
  link_type: string;
  shared_elements: { tas: string[]; ttps: string[]; iocs: string[] };
}

export interface CampaignsResponse {
  campaigns: CampaignEntry[];
  campaign_links: CampaignLink[];
  total: number;
}

export interface CampaignTrendPoint {
  date: string;
  count: number;
}

export interface CampaignTrend {
  cluster_id: string;
  trend_direction: "growing" | "stable" | "declining" | "dormant";
  growth_rate: number | null;
  timeline: CampaignTrendPoint[];
  predicted_peak: string | null;
}

export interface GeopoliticalNationEntry {
  campaign_count: number;
  campaigns: string[];
  primary_motivations: string[];
  targeted_sectors: string[];
  targeted_countries: string[];
  actor_type: string;
}

export interface GeopoliticalSectorTrend {
  campaign_count: number;
  prior_count: number;
  threat_actors: string[];
  trend: "increasing" | "decreasing" | "stable";
}

export interface GeopoliticalSummary {
  nation_state_activity: Record<string, GeopoliticalNationEntry>;
  motivation_breakdown: Record<string, number>;
  sector_threat_trends: Record<string, GeopoliticalSectorTrend>;
  geopolitical_alerts: string[];
  days: number;
  campaign_count: number;
}

/** Shape `NewsletterListItem.sections` (generic `{[key:string]:unknown}`
 * di `schema.d.ts` -- backend nulis lewat `_strip_article()`,
 * `services/newsletter.py`). */
export interface NewsletterArticleStrip {
  id: number;
  title: string;
  url: string;
  source: string;
  posted_on: string;
  news_type: string;
  key_points: string[];
  summary: string;
  body_source: "fetched" | "metadata" | "";
  iocs: Record<string, string[]>;
  cve_mentions: string[];
  possibly_exploited_wild: boolean;
}

export interface NewsletterSections {
  highlight: NewsletterArticleStrip;
  apac: NewsletterArticleStrip[];
  global_news: NewsletterArticleStrip[];
  indonesia: NewsletterArticleStrip[];
  /** Baris "Also Noted" (sejak PR 5); baris riwayat lama tidak punya kuncinya. */
  apac_compact?: unknown[];
  global_news_compact?: unknown[];
  indonesia_compact?: unknown[];
}

/** `POST /api/newsletter/preview` dan `/draft-email` balikin `dict[str,
 * object]` polos (bukan Pydantic model) di `routers/newsletter.py`. */
export interface NewsletterPreviewResult {
  html: string;
  /** Ukuran versi yang DIKIRIM (logo `cid:`), bukan `html` di atas (logo data URI). */
  html_bytes: number;
  /** Teks peringatan siap tampil di atas ~90 KB (Gmail memotong sekitar 102 KB); selain itu null. */
  size_warning: string | null;
  week: number;
  year: number;
  /** Bulan yang diliput, mis. "October 2026"; ganti "Week N, YYYY" untuk judul dan toast. */
  period_label: string;
  /** Rentang tanggal, mis. "1 – 31 October 2026". */
  period_range: string;
  /** `{id artikel: "fetched" | "metadata"}` per kartu penuh; `metadata` = halaman tidak terbaca,
   * ringkasannya ditulis dari metadata saja. */
  body_sources: Record<string, "fetched" | "metadata" | "">;
  /** Preview tidak membuat baris `newsletters`, jadi selalu null. */
  newsletter_id: null;
}

export interface NewsletterDraftResult {
  email_id: string;
  method: string;
  subject: string;
  week: number;
  year: number;
  period_label: string;
  period_range: string;
  newsletter_id: number;
}

/** `NewsletterSuggestionResponse.summary_meta` (`dict[str, object]` di `schema.d.ts`), bentuk dari
 * `services/newsletter_summary.py`. Semua field opsional di sini: baris yang dibangun sebelum PR 8
 * bisa punya `{}`. */
export interface NewsletterSummaryMeta {
  weeks?: { week_start: string; week_end: string }[];
  covered_start?: string | null;
  covered_end?: string | null;
  /** Hari jendela yang tidak diliput pekan mana pun (ekor bulan yang pekannya belum selesai). */
  uncovered?: { start: string; end: string }[];
  model?: string | null;
  /** `{skipped: true, reason: "no_recaps" | "llm_error"}` kalau tidak ada panggilan model. */
  token_usage?: { skipped?: boolean; reason?: string; [key: string]: unknown };
  dropped?: { field: string; value: string; reason: string }[];
  parse_failed?: boolean;
  /** Nama exception (+ kode HTTP), tanpa pesan: sengaja, pesan bisa memuat potongan kunci. */
  error?: string | null;
}

export interface NewsletterResendResult {
  email_id: string;
  method: string;
  subject: string;
}

export interface NewsletterSourceHint {
  paywall_likely: boolean;
  last_seen: string;
}
