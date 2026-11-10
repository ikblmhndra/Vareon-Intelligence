"use client";

import { ExternalLinkIcon, XIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { EntityChip } from "@/components/entities/entity-chip";
import { ArticleByIdDialog } from "@/components/intelligence/campaign-clusters/article-by-id-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { RowMenu } from "@/components/ui/row-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatePanel } from "@/components/ui/state-panel";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/client";
import type {
  IocDetail,
  IocEnrichmentProvider,
  IocSummary,
  IocTaLink,
  IocTaLinksResponse,
} from "@/lib/api/loose-types";
import { useCan } from "@/lib/auth/permissions";
import { fmtAgo, fmtShortDate } from "@/lib/format";
import { defang } from "@/lib/intelligence/defang";
import { actionLabel } from "@/lib/intelligence/format";
import { cn } from "@/lib/utils";

export interface IocTarget {
  type: string;
  value: string;
}

const TLP_OPTIONS: IocSummary["tlp"][] = ["clear", "green", "amber", "amber+strict", "red"];
const PAP_OPTIONS: IocSummary["pap"][] = ["clear", "green", "amber", "red"];

/** Tint chip aksi (D20) per nada `actionLabel`; ditulis utuh supaya Tailwind menemukannya. */
export const ACTION_CHIP = {
  destructive: "bg-destructive/15 text-destructive-text",
  warning: "bg-warning/15 text-warning-text",
  info: "bg-info/15 text-info-text",
  neutral: "bg-panel text-foreground",
} as const;

/** Chip ACTION (BLOCK/INVESTIGATE/MONITOR/ARCHIVE). Label kosong/tak dikenal -> tidak dirender. */
export function IocActionChip({ label }: { label: string | null }) {
  const a = actionLabel(label);
  if (!a) return null;
  return <Chip kind="flag" value={a.word} className={ACTION_CHIP[a.tone]} />;
}

const STATE_CHIP: Record<IocSummary["state"], string> = {
  active: "bg-success/15 text-success-text",
  expired: "bg-panel text-foreground",
  revoked: "bg-destructive/15 text-destructive-text",
  allowlisted: "bg-warning/15 text-warning-text",
};

export function IocStateChip({ state }: { state: IocSummary["state"] }) {
  return <Chip kind="flag" value={state} className={STATE_CHIP[state] ?? STATE_CHIP.expired} />;
}

/** Semua tampilan IOC (tabel, panel, allowlist, analitik FP, dialog entity) ikut diperbarui setelah aksi
 * apa pun di panel: hitungan pil, tile tipe, dan baris tabel membaca kunci-kunci ini. */
export function invalidateIocViews(qc: QueryClient) {
  for (const k of ["ioc-list", "ioc-stats", "ioc-allowlist", "ioc-fp-analytics"]) {
    void qc.invalidateQueries({ queryKey: ["intelligence", k] });
  }
}

/** Tipe allowlist dari tipe IOC (spec 6.9) + nilai yang benar-benar dicocokkan matcher
 * (`cti_core/ioc/allowlist.py`): entri `url_domain` dicocokkan ke host URL, `email_domain` ke domain
 * email, jadi URL/email penuh tidak akan pernah cocok. Hash tidak punya padanan allowlist -> null. */
export function allowlistEntryFor(type: string, value: string): { type: "ip" | "url_domain" | "email_domain"; value: string } | null {
  const v = value.trim().toLowerCase();
  if (type === "ip") return { type: "ip", value: v };
  if (type === "domain") return { type: "url_domain", value: v };
  if (type === "url") {
    const m = /^(?:[a-z][a-z0-9+.-]*:\/\/)?([^/:?#\s]+)/.exec(v);
    return m ? { type: "url_domain", value: m[1] } : null;
  }
  if (type === "email") {
    const at = v.lastIndexOf("@");
    return at > 0 ? { type: "email_domain", value: v.slice(at + 1) } : null;
  }
  return null;
}

/** Angka ringkas per provider dari kunci `raw` yang dikenal (`services/ioc_providers.py`): AbuseIPDB
 * `abuse_confidence` -> "100 / 100", VirusTotal `detections` "14/94" -> "14 / 94 engines", OTX `pulses`
 * -> "6 pulses". Kunci lain jatuh ke `score` ("{score} / 100"). Kunci yang dipakai di sini tidak diulang
 * di daftar rincian. */
function providerMetric(p: IocEnrichmentProvider): { text: string | null; used: string | null } {
  const raw = p.raw ?? {};
  const abuse = raw.abuse_confidence;
  if (abuse != null && abuse !== "") return { text: `${abuse} / 100`, used: "abuse_confidence" };
  const det = raw.detections;
  if (typeof det === "string" && /^\d+\/\d+$/.test(det)) {
    const [hit, total] = det.split("/");
    return { text: `${hit} / ${total} engines`, used: "detections" };
  }
  const pulses = raw.pulses;
  if (pulses != null && pulses !== "") return { text: `${pulses} pulse${Number(pulses) === 1 ? "" : "s"}`, used: "pulses" };
  if (p.score != null) return { text: `${p.score} / 100`, used: null };
  return { text: null, used: null };
}

const VERDICT_CHIP: Record<string, string> = {
  malicious: "bg-destructive/15 text-destructive-text",
  suspicious: "bg-warning/15 text-warning-text",
  clean: "bg-success/15 text-success-text",
  listed: "bg-warning/15 text-warning-text",
};

const FOCUS_RING =
  "outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background";

function SectionLabel({ children }: { children: ReactNode }) {
  return <h3 className="text-2xs font-semibold tracking-wide text-muted-foreground uppercase">{children}</h3>;
}

interface IocDetailBodyProps {
  target: IocTarget;
  /** Dipanggil setelah setiap perubahan (feedback, marking, TA, allowlist) untuk cache milik pemanggil. */
  onChanged: () => void;
  /** Setelah IOC dihapus permanen: pemanggil menutup panel/dialog. */
  onDeleted?: () => void;
  /** `panel` = kartu kanan halaman IOC (judul `h2`); `dialog` = isi `IocDetailDialog` (judul ada di dialog). */
  layout: "panel" | "dialog";
  /** Fokus setelah dialog konfirmasi tertutup (baris terpilih di tabel); tanpa ini kembali ke pemicunya. */
  returnFocus?: () => HTMLElement | null;
}

/** Isi detail IOC (spec 2b 6.9, D21-D23), dipakai panel kanan halaman IOC dan dialog di tab Indicators
 * entity supaya keduanya identik. Semua isi dialog lama tetap ada: marking TLP/PAP, editor tautan threat
 * actor, peringatan FP sumber, hapus permanen, rincian enrichment, sumber + konteks, dan masa berlaku. */
export function IocDetailBody({ target, onChanged, onDeleted, layout, returnFocus }: IocDetailBodyProps) {
  const can = useCan();
  const manage = can("manage_ioc");
  const qc = useQueryClient();
  const uid = useId();
  const [taInput, setTaInput] = useState("");
  const [busy, setBusy] = useState<null | "tp" | "fp" | "allowlist" | "delete" | "ta">(null);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [fpWarning, setFpWarning] = useState<IocDetail["source_fp_warning"] | null>(null);
  const [articleId, setArticleId] = useState<number | null>(null);

  const detailKey = ["intelligence", "ioc-detail", target.type, target.value] as const;
  const taKey = ["intelligence", "ioc-ta-links", target.type, target.value] as const;

  const detailQuery = useQuery({
    queryKey: detailKey,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/{ioc_type}/{value}", {
        params: { path: { ioc_type: target.type, value: target.value } },
      });
      if (error) throw error;
      return data as unknown as IocDetail;
    },
  });

  const taQuery = useQuery({
    queryKey: taKey,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/ta-links/{ioc_type}/{value}", {
        params: { path: { ioc_type: target.type, value: target.value } },
      });
      if (error) throw error;
      return data as unknown as IocTaLinksResponse;
    },
  });

  const ioc = detailQuery.data;

  function changed() {
    void qc.invalidateQueries({ queryKey: detailKey });
    void qc.invalidateQueries({ queryKey: taKey });
    invalidateIocViews(qc);
    onChanged();
  }

  async function feedback(verdict: "tp" | "fp", note?: string) {
    if (!ioc) return;
    setBusy(verdict);
    try {
      const { data, error } = await api.POST("/api/iocs/{ioc_id}/feedback", {
        params: { path: { ioc_id: ioc.id } },
        body: { verdict, note: note || null },
      });
      if (error) throw new Error(JSON.stringify(error));
      const res = data as unknown as IocDetail;
      setFpWarning(verdict === "fp" ? (res.source_fp_warning ?? null) : null);
      toast.success(verdict === "tp" ? "Marked as true positive." : "Removed from feeds.");
      changed();
    } catch (e) {
      toast.error(`Feedback failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      setRemoveOpen(false);
    }
  }

  async function allowlist() {
    if (!ioc) return;
    const entry = allowlistEntryFor(ioc.type, ioc.value);
    if (!entry) return;
    setBusy("allowlist");
    try {
      const { error } = await api.POST("/api/iocs/allowlist", {
        body: { ...entry, note: `from IOC ${ioc.value}`.slice(0, 300) },
      });
      if (error) throw new Error(JSON.stringify(error));
      toast.success(`Added ${entry.value} to the allowlist.`);
      changed();
    } catch (e) {
      toast.error(`Allowlist failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function doDelete() {
    if (!ioc) return;
    setBusy("delete");
    try {
      const { error } = await api.DELETE("/api/iocs/{ioc_id}", { params: { path: { ioc_id: ioc.id } } });
      if (error) throw new Error(JSON.stringify(error));
      toast.success("IOC deleted.");
      invalidateIocViews(qc);
      onChanged();
      onDeleted?.();
    } catch (e) {
      toast.error(`Delete failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
      setDeleteOpen(false);
    }
  }

  async function addTa() {
    const actor = taInput.trim();
    if (!actor) return;
    setBusy("ta");
    try {
      const { error } = await api.POST("/api/iocs/{ioc_type}/{value}/threat-actors", {
        params: { path: { ioc_type: target.type, value: target.value } },
        body: { threat_actors: [actor] },
      });
      if (error) throw new Error(JSON.stringify(error));
      setTaInput("");
      changed();
    } catch (e) {
      toast.error(`Failed to link TA: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function removeTa(actor: string) {
    try {
      const { error } = await api.DELETE("/api/iocs/{ioc_type}/{value}/threat-actors/{actor}", {
        params: { path: { ioc_type: target.type, value: target.value, actor } },
      });
      if (error) throw new Error(JSON.stringify(error));
      changed();
    } catch (e) {
      toast.error(`Failed to remove TA: ${(e as Error).message}`);
    }
  }

  async function setMarking(body: { tlp?: IocSummary["tlp"]; pap?: IocSummary["pap"] }) {
    if (!ioc) return;
    try {
      const { error } = await api.PATCH("/api/iocs/{ioc_id}/marking", { params: { path: { ioc_id: ioc.id } }, body });
      if (error) throw new Error(JSON.stringify(error));
      changed();
    } catch (e) {
      toast.error(`Failed to update marking: ${(e as Error).message}`);
    }
  }

  const wrap = (content: ReactNode) =>
    layout === "panel" ? (
      <Card>
        <div className="flex flex-col gap-5 px-5">{content}</div>
      </Card>
    ) : (
      <div className="flex flex-col gap-5">{content}</div>
    );

  if (detailQuery.isPending) return wrap(<StatePanel variant="loading" title="Loading indicator" />);
  if (detailQuery.isError || !ioc)
    return wrap(
      <StatePanel
        variant="error"
        title="Could not load this indicator"
        action={
          <Button variant="outline" size="sm" onClick={() => void detailQuery.refetch()}>
            Retry
          </Button>
        }
      />,
    );

  const shown = defang(ioc.type, ioc.value);
  const Heading = layout === "panel" ? "h2" : "p";
  const providers = (ioc.enrichment?.providers ?? []).filter((p) => p && p.key);
  const links: IocTaLink[] = taQuery.data?.threat_actors ?? [];
  const allowEntry = allowlistEntryFor(ioc.type, ioc.value);

  let stateLine: string;
  if (ioc.state === "revoked")
    stateLine = `Removed from feeds by ${ioc.revoked_by ?? "—"} on ${fmtShortDate(ioc.revoked_at)}`;
  else if (ioc.state === "allowlisted") stateLine = "Allowlisted";
  else if (ioc.state === "expired") stateLine = `Expired ${fmtShortDate(ioc.valid_until)}`;
  else stateLine = ioc.valid_until ? `Active · valid until ${fmtShortDate(ioc.valid_until)}` : "Active · never expires";
  if (ioc.auto_suppressed) stateLine += ` · auto-suppressed${ioc.suppression_reason ? `: ${ioc.suppression_reason}` : ""}`;

  return wrap(
    <>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-start gap-2">
          <Heading className="min-w-0 flex-1 font-code text-sm font-semibold break-all text-foreground">{shown}</Heading>
          <IocActionChip label={ioc.actionability_label} />
          <RowMenu
            label={`More actions for ${shown}`}
            items={[{ label: "Delete IOC", destructive: true, onSelect: () => setDeleteOpen(true), hidden: !manage }]}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          {ioc.type} · first seen {fmtShortDate(ioc.first_seen)} · last seen {fmtAgo(ioc.last_seen)}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <IocStateChip state={ioc.state} />
          <Chip kind="flag" value={`TLP:${ioc.tlp}`} />
          <span className="text-xs text-muted-foreground">
            conf. {ioc.confidence_score ?? "—"} · actionability {ioc.actionability_score ?? "—"} · seen {ioc.seen_count || 1}× ·{" "}
            {ioc.tp_count} TP · {ioc.fp_count} FP
          </span>
        </div>
        <p className={cn("text-xs", ioc.state === "revoked" ? "text-destructive-text" : "text-muted-foreground")}>{stateLine}</p>
        {ioc.recommended_action && <p className="text-sm text-foreground">{ioc.recommended_action}</p>}
      </div>

      {fpWarning && (
        <Notice tone="warning" title={`High FP rate for ${fpWarning.source_name}`}>
          {fpWarning.fp_count} of {fpWarning.total_iocs} indicators from this source are marked FP (
          {Math.round(fpWarning.fp_rate * 100)}%). Consider lowering its reliability grade.
        </Notice>
      )}

      <section className="flex flex-col gap-2">
        <SectionLabel>Enrichment</SectionLabel>
        {providers.length === 0 ? (
          <p className="text-xs text-muted-foreground">No enrichment yet.</p>
        ) : (
          <ul className="flex flex-col divide-y divide-border">
            {providers.map((p) => {
              const metric = providerMetric(p);
              const raw = p.raw ?? {};
              const rest = Object.keys(raw).filter((k) => k !== metric.used && raw[k] !== null && raw[k] !== "");
              const families = (p.malware_families ?? []).filter(Boolean).slice(0, 6);
              const tags = (p.tags ?? []).slice(0, 8);
              const verdict = (p.verdict || "unknown").toLowerCase();
              return (
                <li key={p.key} className="flex flex-col gap-1.5 py-2 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-foreground">{p.name || p.key}</span>
                    <Chip kind="flag" value={verdict} className={VERDICT_CHIP[verdict]} />
                    {metric.text && <span className="ml-auto font-code text-xs text-foreground">{metric.text}</span>}
                  </div>
                  {rest.length > 0 && (
                    <dl className="flex flex-wrap gap-x-3 gap-y-0.5 text-2xs text-muted-foreground">
                      {rest.map((k) => (
                        <div key={k} className="flex gap-1">
                          <dt>{k.replace(/_/g, " ")}</dt>
                          <dd className="text-foreground">{String(raw[k])}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {families.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {families.map((f) => (
                        <EntityChip key={f} type="malware,tool" name={f} />
                      ))}
                    </div>
                  )}
                  {tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {tags.map((t) => (
                        <Chip key={t} kind="flag" value={t} className="normal-case" />
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {ioc.enrichment?.updated_at && (
          <p className="text-2xs text-muted-foreground">updated {fmtShortDate(ioc.enrichment.updated_at)}</p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <SectionLabel>Threat actors</SectionLabel>
        {links.length === 0 ? (
          <p className="text-xs text-muted-foreground">No threat actors linked.</p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {links.map((ta) => {
              const isManual = ta.source === "manual" || ta.source === "both";
              return (
                <li key={ta.name} className="flex flex-col gap-0.5">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <EntityChip type="intrusion-set" name={ta.name} />
                    {ta.is_watched && <Chip kind="flag" value="watched" className="bg-warning/15 text-warning-text" />}
                    {ta.attack_group_id && <Chip kind="flag" value={ta.attack_group_id} className="font-code" />}
                    {ta.source === "manual" && <Chip kind="flag" value="manual" />}
                    {ta.source === "both" && <Chip kind="flag" value="manual + articles" />}
                    {isManual && manage && (
                      <button
                        type="button"
                        aria-label={`Remove ${ta.name}`}
                        onClick={() => void removeTa(ta.name)}
                        className={cn("inline-flex size-6 items-center justify-center rounded-sm text-muted-foreground hover:text-destructive-text", FOCUS_RING)}
                      >
                        <XIcon aria-hidden className="size-3.5" />
                      </button>
                    )}
                    <span className="ml-auto text-2xs text-muted-foreground">
                      {ta.article_count > 0 ? `${ta.article_count} article${ta.article_count === 1 ? "" : "s"}` : "manual only"}
                    </span>
                  </div>
                  {(ta.attack_group_aliases ?? []).length > 0 && (
                    <p className="text-2xs text-muted-foreground">aka {(ta.attack_group_aliases ?? []).slice(0, 4).join(", ")}</p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {manage && (
          <div className="flex gap-1.5">
            <Input
              aria-label="Threat actor name"
              placeholder="Add threat actor name…"
              value={taInput}
              onChange={(e) => setTaInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void addTa()}
              className="h-8 flex-1 text-xs"
            />
            <Button size="sm" variant="outline" loading={busy === "ta"} onClick={() => void addTa()}>
              Link actor
            </Button>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <SectionLabel>Sources · {ioc.sources.length}</SectionLabel>
        {ioc.sources.length === 0 ? (
          <p className="text-xs text-muted-foreground">No source articles recorded.</p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {ioc.sources.map((s, i) => (
              <li key={`${s.url}-${i}`} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-foreground">{s.source_name || "—"}</span>
                  <span className="ml-auto text-2xs text-muted-foreground">{fmtShortDate(s.first_seen)}</span>
                </div>
                {s.context && <p className="text-xs text-muted-foreground italic">{s.context}</p>}
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  {s.article_id != null && (
                    <button
                      type="button"
                      onClick={() => setArticleId(s.article_id)}
                      className={cn("rounded-sm text-primary-text hover:underline", FOCUS_RING)}
                    >
                      Open article
                    </button>
                  )}
                  {s.url && (
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={s.url}
                      className={cn("inline-flex min-w-0 items-center gap-1 rounded-sm text-muted-foreground hover:underline", FOCUS_RING)}
                    >
                      <span className="truncate">{s.url}</span>
                      <ExternalLinkIcon aria-hidden className="size-3 shrink-0" />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <SectionLabel>Marking</SectionLabel>
        <div className="flex gap-3">
          <MarkingSelect id={`${uid}-tlp`} label="TLP" value={ioc.tlp} options={TLP_OPTIONS} disabled={!manage} onChange={(v) => void setMarking({ tlp: v })} />
          <MarkingSelect id={`${uid}-pap`} label="PAP" value={ioc.pap} options={PAP_OPTIONS} disabled={!manage} onChange={(v) => void setMarking({ pap: v })} />
        </div>
      </section>

      {ioc.tags.length > 0 && (
        <section className="flex flex-col gap-2">
          <SectionLabel>Tags</SectionLabel>
          <div className="flex flex-wrap gap-1">
            {ioc.tags.map((t) => (
              <Chip key={t} kind="flag" value={t} className="bg-primary/10 text-primary-text normal-case" />
            ))}
          </div>
        </section>
      )}

      {manage && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <Button size="sm" variant="outline" loading={busy === "tp"} disabled={busy !== null} onClick={() => void feedback("tp")}>
            TP / restore
          </Button>
          <Button size="sm" variant="destructive" disabled={busy !== null || ioc.state === "revoked"} onClick={() => setRemoveOpen(true)}>
            FP: remove
          </Button>
          {allowEntry ? (
            <Button size="sm" variant="outline" loading={busy === "allowlist"} disabled={busy !== null} onClick={() => void allowlist()}>
              Allowlist
            </Button>
          ) : (
            <Tooltip>
              {/* Tombol disabled tidak menerima hover/fokus, jadi tooltip dipasang di pembungkus yang bisa difokus. */}
              <TooltipTrigger render={<span tabIndex={0} className={cn("rounded-[10px]", FOCUS_RING)} />}>
                <Button size="sm" variant="outline" disabled aria-label="Allowlist (not available for hashes)">
                  Allowlist
                </Button>
              </TooltipTrigger>
              <TooltipContent>Hashes cannot be allowlisted; only IPs, domains, URLs and email domains.</TooltipContent>
            </Tooltip>
          )}
        </div>
      )}

      <ConfirmDialog
        open={removeOpen}
        onOpenChange={setRemoveOpen}
        title={`Remove ${shown} from feeds?`}
        description="It stops appearing in STIX and CSV exports for every client. Analysts can restore it with TP."
        note={{ label: "Note", placeholder: "Optional: why this is a false positive", maxLength: 2000 }}
        confirmLabel="Remove from feeds"
        cancelVariant="ghost"
        tone="danger"
        confirmLoading={busy === "fp"}
        finalFocus={returnFocus}
        onConfirm={(note) => void feedback("fp", note)}
      />
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Delete ${shown}?`}
        description="This deletes the indicator and its history. It cannot be undone."
        confirmLabel="Delete IOC"
        cancelVariant="ghost"
        tone="danger"
        confirmLoading={busy === "delete"}
        finalFocus={returnFocus}
        onConfirm={() => void doDelete()}
      />
      <ArticleByIdDialog articleId={articleId} onClose={() => setArticleId(null)} />
    </>,
  );
}

function MarkingSelect<T extends string>({
  id,
  label,
  value,
  options,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: T;
  options: T[];
  disabled: boolean;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex flex-1 flex-col gap-1">
      <label htmlFor={id} className="text-2xs font-semibold text-muted-foreground">
        {label}
      </label>
      <Select items={Object.fromEntries(options.map((o) => [o, o]))} value={value} disabled={disabled} onValueChange={(v) => v && onChange(v as T)}>
        <SelectTrigger id={id} size="sm" className="w-full text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
