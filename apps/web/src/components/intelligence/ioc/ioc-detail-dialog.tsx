"use client";

import { Trash2Icon, XIcon, ZapIcon } from "lucide-react";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { IocActionabilityChip, IocConfidenceChip, IocTypeBadge } from "@/components/intelligence/ioc/ioc-badges";
import type { IocDetail, IocTaLink, IocTaLinksResponse } from "@/lib/api/loose-types";

export interface IocTarget {
  type: string;
  value: string;
}

interface IocDetailDialogProps {
  target: IocTarget | null;
  onClose: () => void;
  onDeleted: () => void;
}

function verdictColor(verdict: string | undefined) {
  switch ((verdict || "").toLowerCase()) {
    case "malicious":
      return "text-destructive";
    case "suspicious":
      return "text-warning";
    case "clean":
      return "text-primary";
    default:
      return "text-muted-foreground";
  }
}

function scoreColor(score: number) {
  if (score >= 75) return "text-destructive";
  if (score > 0) return "text-warning";
  return "text-muted-foreground";
}

/** Port `iocmgmtOpenDetail()` (`ioc_mgmt.js:158-292`) -- detail IOC +
 * TIP enrichment + TA links + linked articles, satu overlay. */
export function IocDetailDialog({ target, onClose, onDeleted }: IocDetailDialogProps) {
  const queryClient = useQueryClient();
  const [taInput, setTaInput] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const detailQuery = useQuery({
    queryKey: ["intelligence", "ioc-detail", target?.type, target?.value],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/{ioc_type}/{value}", {
        params: { path: { ioc_type: target!.type, value: target!.value } },
      });
      if (error) throw error;
      return data as unknown as IocDetail;
    },
    enabled: target !== null,
  });

  const taQuery = useQuery({
    queryKey: ["intelligence", "ioc-ta-links", target?.type, target?.value],
    queryFn: async () => {
      const { data, error } = await api.GET("/api/iocs/ta-links/{ioc_type}/{value}", {
        params: { path: { ioc_type: target!.type, value: target!.value } },
      });
      if (error) throw error;
      return data as unknown as IocTaLinksResponse;
    },
    enabled: target !== null,
  });

  function invalidateAll() {
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-detail", target?.type, target?.value] });
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-ta-links", target?.type, target?.value] });
    void queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-list"] });
  }

  async function addTa() {
    const actor = taInput.trim();
    if (!actor || !target) return;
    try {
      const { error } = await api.POST("/api/iocs/{ioc_type}/{value}/threat-actors", {
        params: { path: { ioc_type: target.type, value: target.value } },
        body: { threat_actors: [actor] },
      });
      if (error) throw new Error(JSON.stringify(error));
      setTaInput("");
      invalidateAll();
    } catch (e) {
      toast.error(`Failed to link TA: ${(e as Error).message}`);
    }
  }

  async function removeTa(actor: string) {
    if (!target) return;
    try {
      const { error } = await api.DELETE("/api/iocs/{ioc_type}/{value}/threat-actors/{actor}", {
        params: { path: { ioc_type: target.type, value: target.value, actor } },
      });
      if (error) throw new Error(JSON.stringify(error));
      invalidateAll();
    } catch (e) {
      toast.error(`Failed to remove TA: ${(e as Error).message}`);
    }
  }

  async function doDelete() {
    if (!ioc) return;
    try {
      const { error } = await api.DELETE("/api/iocs/{ioc_id}", { params: { path: { ioc_id: ioc.id } } });
      if (error) throw new Error(JSON.stringify(error));
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-list"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligence", "ioc-stats"] });
      onDeleted();
    } catch (e) {
      toast.error(`Delete failed: ${(e as Error).message}`);
    }
  }

  const ioc = detailQuery.data;
  const providers = (ioc?.enrichment?.providers ?? []).filter((p) => p && p.key);

  return (
    <>
      <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
        <DialogContent className="max-h-[85vh] w-full max-w-2xl overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="sr-only">IOC Detail</DialogTitle>
          </DialogHeader>

          {detailQuery.isPending && <p className="py-6 text-center text-xs text-muted-foreground">Loading…</p>}
          {detailQuery.isError && <p className="py-6 text-center text-xs text-destructive">Failed to load IOC.</p>}

          {ioc && (
            <div className="font-mono text-xs">
              <div className="mb-3 flex flex-wrap items-center gap-2.5">
                <IocTypeBadge type={ioc.type} />
                <span className="font-code text-[13px] break-all text-foreground">{ioc.value}</span>
                <IocConfidenceChip score={ioc.confidence_score} />
                <IocActionabilityChip label={ioc.actionability_label} />
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto h-6 border-destructive/40 px-2 text-xs text-destructive"
                  onClick={() => setConfirmDelete(true)}
                >
                  <Trash2Icon aria-hidden /> Delete IOC
                </Button>
              </div>

              {ioc.recommended_action && (
                <div className="mb-3.5 rounded-xl border border-border bg-background px-2.5 py-1.5 text-xs text-foreground">
                  <ZapIcon aria-hidden /> {ioc.recommended_action}
                </div>
              )}

              <div className="mb-5 grid grid-cols-3 gap-3">
                <div className="rounded-xl border border-border bg-background p-2.5">
                  <div className="mb-1 text-sm font-semibold text-muted-foreground">Seen Count</div>
                  <div className="text-lg font-bold text-foreground">{ioc.seen_count || 1}</div>
                </div>
                <div className="rounded-xl border border-border bg-background p-2.5">
                  <div className="mb-1 text-sm font-semibold text-muted-foreground">First Seen</div>
                  <div className="text-[13px] text-foreground">{ioc.first_seen || "—"}</div>
                </div>
                <div className="rounded-xl border border-border bg-background p-2.5">
                  <div className="mb-1 text-sm font-semibold text-muted-foreground">Last Seen</div>
                  <div className="text-[13px] text-foreground">{ioc.last_seen || "—"}</div>
                </div>
              </div>

              {ioc.tags.length > 0 && (
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {ioc.tags.map((t) => (
                    <span key={t} className="rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-xs text-primary-text">
                      {t}
                    </span>
                  ))}
                </div>
              )}

              {providers.length > 0 && (
                <div className="mb-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-muted-foreground">
                    TIP Enrichment
                    {ioc.enrichment?.updated_at && <span className="text-xs normal-case">updated {ioc.enrichment.updated_at}</span>}
                  </div>
                  {providers.map((p) => {
                    const families = (p.malware_families ?? []).filter(Boolean).slice(0, 6);
                    const tags = (p.tags ?? []).slice(0, 8);
                    const raw = p.raw ?? {};
                    const rawKeys = Object.keys(raw).filter((k) => raw[k] !== null && raw[k] !== "");
                    return (
                      <div key={p.key} className="mb-2.5 rounded-xl border border-border bg-background p-3">
                        <div className="mb-2.5 flex items-center justify-between">
                          <span className="text-sm font-semibold text-muted-foreground">{p.name || p.key}</span>
                          <span className={`rounded-full border border-border bg-surface px-1.5 py-0.5 text-xs uppercase ${verdictColor(p.verdict)}`}>
                            {p.verdict || "unknown"}
                          </span>
                        </div>
                        <div className="mb-2.5 flex flex-wrap gap-4">
                          <div>
                            <div className="mb-0.5 text-xs text-muted-foreground">SCORE</div>
                            <div className={`text-base font-bold ${scoreColor(p.score ?? 0)}`}>
                              {p.score ?? "—"}
                              <span className="text-xs text-muted-foreground">/100</span>
                            </div>
                          </div>
                          {rawKeys.map((k) => (
                            <div key={k}>
                              <div className="mb-0.5 text-xs text-muted-foreground">{k.replace(/_/g, " ").toUpperCase()}</div>
                              <div className="text-[13px] text-foreground">{String(raw[k])}</div>
                            </div>
                          ))}
                        </div>
                        {families.length > 0 && (
                          <div className="mb-1.5">
                            <div className="mb-1 text-xs text-muted-foreground">MALWARE FAMILIES</div>
                            <div className="flex flex-wrap gap-1">
                              {families.map((f) => (
                                <span key={f} className="rounded-full border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive-text">
                                  {f}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        {tags.length > 0 && (
                          <div>
                            <div className="mb-1 text-xs text-muted-foreground">TAGS</div>
                            <div className="flex flex-wrap gap-1">
                              {tags.map((t) => (
                                <span key={t} className="rounded-full border border-border bg-surface px-1.5 py-0.5 text-xs text-muted-foreground">
                                  {t}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <IocTaLinksSection links={taQuery.data?.threat_actors ?? []} taInput={taInput} setTaInput={setTaInput} onAdd={() => void addTa()} onRemove={(actor) => void removeTa(actor)} />

              <div className="mb-2 text-sm font-semibold text-muted-foreground">Linked Articles ({ioc.sources.length})</div>
              <div className="overflow-hidden rounded-md border border-border">
                {ioc.sources.length === 0 ? (
                  <div className="p-3 text-[13px] text-muted-foreground">No source articles recorded.</div>
                ) : (
                  ioc.sources.map((s, i) => (
                    <div key={i} className="flex flex-col gap-1 border-b border-border p-2.5 last:border-b-0">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full border border-border bg-surface px-1.5 py-0.5 text-xs text-muted-foreground">{s.source_name || "—"}</span>
                        <span className="ml-auto text-xs text-muted-foreground">{s.first_seen}</span>
                      </div>
                      <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-xs break-all text-primary">
                        {s.url}
                      </a>
                      {s.context && <div className="mt-0.5 text-xs text-muted-foreground italic">{s.context}</div>}
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this IOC?"
        description={ioc ? `${ioc.type}: ${ioc.value}` : undefined}
        warning="This cannot be undone."
        confirmLabel="Delete"
        onConfirm={() => void doDelete()}
      />
    </>
  );
}

function IocTaLinksSection({
  links,
  taInput,
  setTaInput,
  onAdd,
  onRemove,
}: {
  links: IocTaLink[];
  taInput: string;
  setTaInput: (v: string) => void;
  onAdd: () => void;
  onRemove: (actor: string) => void;
}) {
  return (
    <div className="mb-4">
      <div className="mb-2 text-sm font-semibold text-muted-foreground">Linked Threat Actors ({links.length})</div>
      <div className="overflow-hidden rounded-md border border-border">
        {links.length === 0 ? (
          <div className="p-3 text-[13px] text-muted-foreground">No threat actors linked.</div>
        ) : (
          links.map((ta) => {
            const isManual = ta.source === "manual" || ta.source === "both";
            return (
              <div key={ta.name} className="flex flex-col gap-0.5 border-b border-border p-2.5 last:border-b-0">
                <div className="flex flex-wrap items-center">
                  <span className="text-[12px] text-foreground">{ta.name}</span>
                  {ta.is_watched && (
                    <span className="ml-1.5 rounded-full border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-xs text-warning-text">WATCHED</span>
                  )}
                  {ta.attack_group_id && (
                    <span className="ml-1.5 rounded-full border border-tag-violet/35 bg-tag-violet/15 px-1.5 py-0.5 text-xs text-tag-violet-text">{ta.attack_group_id}</span>
                  )}
                  {ta.source === "manual" && (
                    <span className="ml-1.5 rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-xs text-primary-text">MANUAL</span>
                  )}
                  {ta.source === "both" && (
                    <span className="ml-1.5 rounded-full border border-primary/30 bg-primary/10 px-1.5 py-0.5 text-xs text-primary-text">MANUAL+ART</span>
                  )}
                  {isManual && (
                    <button type="button" aria-label={`Remove ${ta.name}`} onClick={() => onRemove(ta.name)} className="ml-2 inline-flex min-h-6 min-w-6 items-center justify-center text-[13px] text-muted-foreground hover:text-destructive">
                      <XIcon aria-hidden />
                    </button>
                  )}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {ta.article_count > 0 ? `${ta.article_count} article${ta.article_count !== 1 ? "s" : ""}` : "manual only"}
                  </span>
                </div>
                {(ta.attack_group_aliases ?? []).length > 0 && (
                  <div className="text-xs text-muted-foreground">aka: {(ta.attack_group_aliases ?? []).slice(0, 4).join(", ")}</div>
                )}
              </div>
            );
          })
        )}
      </div>
      <div className="mt-2 flex gap-1.5">
        <Input
          placeholder="Add threat actor name…"
          value={taInput}
          onChange={(e) => setTaInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAdd()}
          className="flex-1 font-mono text-xs"
        />
        <Button size="sm" variant="outline" onClick={onAdd}>
          + Link TA
        </Button>
      </div>
    </div>
  );
}
