"use client";

import { ChevronDownIcon } from "lucide-react";
import { useId, useMemo, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChipInput } from "@/components/ui/chip-input";
import { DateField } from "@/components/ui/date-field";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { COUNTRIES } from "@/lib/countries";
import { displayId, PIR_PRIORITY_OPTIONS } from "@/lib/intelligence/format";
import { PIR_STATUS_TABS, usePirPreview, type PIRCriteria, type PIROut } from "@/lib/intelligence/pir";
import { cn } from "@/lib/utils";

interface PirFormDialogProps {
  pir?: PIROut | null;
  open: boolean;
  onClose: () => void;
  /** PIR hasil simpan (respons POST/PUT), supaya halaman bisa memilihnya. */
  onSaved: (saved: PIROut) => void;
}

const SEP = " · ";
const TTP_ID = /^T\d{4}(\.\d{3})?$/i;
const TITLE_ERROR = 'Give the PIR a title, for example "Ransomware against ASEAN banks".';

/** Pesan galat API yang bisa dibaca (FastAPI `detail` string atau daftar galat validasi). */
function apiMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d as { msg?: string }).msg)
      .filter(Boolean)
      .join("; ");
  }
  return "Could not save the PIR. Try again.";
}

/** Bagian awal saran "ID · Indonesia" / "T1566 · Phishing" = nilai yang disimpan. */
function head(v: string): string {
  return v.split(SEP)[0].trim();
}

/** Saran ChipInput: daftar statis dari `/api/pir/options` + `/api/entities` (403 tanpa `view_ta` -> diam saja).
 * ChipInput memanggil sumbernya tiap ketikan; jeda 200 ms + cek ketikan terbaru menahan request ke API, dan
 * `fetchQuery` menyimpan hasilnya di cache react-query. */
function makeSuggest(
  queryClient: QueryClient,
  staticList: () => string[],
  entity?: { type: string; identityClass?: "class"; format: (e: { name: string; external_id?: string | null }) => string },
) {
  let latest = "";
  return async (q: string): Promise<string[]> => {
    latest = q;
    const needle = q.toLowerCase();
    const fromStatic = staticList().filter((s) => s.toLowerCase().includes(needle));
    let fromEntities: string[] = [];
    if (entity) {
      await new Promise((r) => setTimeout(r, 200));
      if (latest !== q) return [];
      try {
        fromEntities = await queryClient.fetchQuery({
          queryKey: ["pir", "suggest", entity.type, entity.identityClass ?? "", q],
          staleTime: 60_000,
          queryFn: async () => {
            const { data } = await api.GET("/api/entities", {
              params: { query: { type: entity.type, identity_class: entity.identityClass, q, limit: 8 } },
            });
            return (data?.items ?? []).map(entity.format);
          },
        });
      } catch {
        fromEntities = [];
      }
    }
    const seen = new Set<string>();
    return [...fromStatic, ...fromEntities]
      .filter((s) => {
        const k = s.toLowerCase();
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      })
      .slice(0, 10);
  };
}

/** Terima nilai lama apa adanya; nilai BARU harus terpetakan oleh `resolve` (negara -> kode ISO, teknik -> id,
 * tipe berita -> opsi). Kriteria di-AND di server: satu token yang tak pernah cocok membuat PIR tak cocok apa
 * pun, jadi teks yang tak terpetakan ditolak dengan galat inline (perilaku `EntityAutocomplete` lama). */
function guarded(
  prev: string[],
  next: string[],
  resolve: (v: string) => string | null,
): { values: string[]; rejected: boolean } {
  const out: string[] = [];
  let rejected = false;
  for (const v of next) {
    const r = prev.includes(v) ? v : resolve(v);
    if (r === null) rejected = true;
    else if (!out.some((x) => x.toLowerCase() === r.toLowerCase())) out.push(r);
  }
  return { values: out, rejected };
}

/** Dialog buat/ubah PIR (spec 2b 6.4, D18): judul wajib dengan galat inline, prioritas 3 tingkat (C10), kriteria
 * sebagai chip, bagian "Advanced" untuk deskripsi/malware/tipe berita/status supaya data lama tidak hilang, dan
 * pratinjau jumlah artikel 90 hari (debounce 500 ms). Galat API tampil di dalam dialog; isian tidak dibuang. */
export function PirFormDialog({ pir, open, onClose, onSaved }: PirFormDialogProps) {
  const isEdit = Boolean(pir);
  const queryClient = useQueryClient();
  const uid = useId();
  const titleRef = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState(pir?.title ?? "");
  const [titleError, setTitleError] = useState<string | undefined>();
  const [description, setDescription] = useState(pir?.description ?? "");
  const [priority, setPriority] = useState(pir?.priority ?? "P2");
  const [owner, setOwner] = useState(pir?.owner ?? "");
  const [status, setStatus] = useState(pir?.status ?? "active");
  const [startDate, setStartDate] = useState<string | null>(pir?.start_date ?? null);
  const [endDate, setEndDate] = useState<string | null>(pir?.end_date ?? null);
  const c = pir?.criteria;
  const [threatActors, setThreatActors] = useState<string[]>(c?.threat_actors ?? []);
  const [malware, setMalware] = useState<string[]>(c?.malware ?? []);
  const [industries, setIndustries] = useState<string[]>(c?.industries ?? []);
  const [countries, setCountries] = useState<string[]>(c?.countries ?? []);
  const [newsTypes, setNewsTypes] = useState<string[]>(c?.news_types ?? []);
  const [ttps, setTtps] = useState<string[]>(c?.ttps ?? []);
  const [keywords, setKeywords] = useState<string[]>(c?.keywords ?? []);
  const [chipErrors, setChipErrors] = useState<Record<string, string | undefined>>({});
  // Advanced terbuka otomatis bila ada isinya, supaya kriteria/deskripsi lama tetap terlihat saat edit.
  const [advancedOpen, setAdvancedOpen] = useState(
    Boolean(
      (pir?.description ?? "") !== "" ||
        (c?.malware.length ?? 0) > 0 ||
        (c?.news_types.length ?? 0) > 0 ||
        (pir && pir.status !== "active"),
    ),
  );
  const [saving, setSaving] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const options = useQuery({
    queryKey: ["pir", "options"],
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/pir/options");
      if (error) throw error;
      return data;
    },
  });
  const opts = options.data;

  const suggest = useMemo(
    () => ({
      actors: makeSuggest(queryClient, () => opts?.threat_actors ?? [], {
        type: "intrusion-set",
        format: (e) => e.name,
      }),
      malware: makeSuggest(queryClient, () => opts?.malware ?? [], {
        type: "malware,tool",
        format: (e) => e.name,
      }),
      industries: makeSuggest(queryClient, () => opts?.industries ?? [], {
        type: "identity",
        identityClass: "class",
        format: (e) => e.name,
      }),
      countries: makeSuggest(queryClient, () => COUNTRIES.map((x) => `${x.code}${SEP}${x.name}`)),
      ttps: makeSuggest(queryClient, () => (opts?.ttps ?? []).map((t) => `${t.id}${SEP}${t.name}`), {
        type: "attack-pattern",
        format: (e) => (e.external_id ? `${e.external_id}${SEP}${e.name}` : e.name),
      }),
      newsTypes: makeSuggest(queryClient, () => opts?.news_types ?? []),
    }),
    [queryClient, opts],
  );

  function resolveCountry(v: string): string | null {
    const t = head(v).toLowerCase();
    return COUNTRIES.find((x) => x.code.toLowerCase() === t || x.name.toLowerCase() === t)?.code ?? null;
  }
  function resolveTtp(v: string): string | null {
    const t = head(v);
    if (TTP_ID.test(t)) return t.toUpperCase();
    return opts?.ttps.find((x) => x.name.toLowerCase() === t.toLowerCase())?.id ?? null;
  }
  function resolveNewsType(v: string): string | null {
    const list = opts?.news_types;
    // Opsi belum termuat: jangan tolak ketikan (server tetap menerimanya), cukup pakai apa adanya.
    if (!list) return v.trim();
    return list.find((x) => x.toLowerCase() === v.trim().toLowerCase()) ?? null;
  }

  function guardedSetter(
    key: string,
    prev: string[],
    set: (v: string[]) => void,
    resolve: (v: string) => string | null,
    message: string,
  ) {
    return (next: string[]) => {
      const r = guarded(prev, next, resolve);
      set(r.values);
      setChipErrors((e) => ({ ...e, [key]: r.rejected ? message : undefined }));
    };
  }

  // Urutan kunci tetap: kunci query pratinjau = JSON objek ini.
  const criteria: PIRCriteria = useMemo(
    () => ({
      threat_actors: threatActors,
      malware,
      industries,
      countries,
      news_types: newsTypes,
      ttps,
      keywords,
    }),
    [threatActors, malware, industries, countries, newsTypes, ttps, keywords],
  );
  const preview = usePirPreview(criteria, open);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setTitleError(TITLE_ERROR);
      titleRef.current?.focus();
      return;
    }
    setSaving(true);
    setApiError(null);
    // Field ber-default di backend tetap dikirim: tipe hasil openapi-typescript mewajibkannya.
    const base = {
      title: title.trim(),
      description,
      priority,
      owner: owner.trim(),
      criteria,
      start_date: startDate,
      end_date: endDate,
    };
    try {
      const res =
        isEdit && pir
          ? await api.PUT("/api/pir/{pir_id}", {
              params: { path: { pir_id: pir.id } },
              body: { ...base, status },
            })
          : await api.POST("/api/pir", { body: base });
      if (res.error || !res.data) {
        setApiError(apiMessage(res.error));
        return;
      }
      toast.success(isEdit ? "PIR updated." : "PIR created.");
      onSaved(res.data);
      onClose();
    } catch {
      setApiError("Could not reach the server. Try again.");
    } finally {
      setSaving(false);
    }
  }

  const id = (name: string) => `${uid}-${name}`;
  const titleId = id("title");
  const advancedPanel = id("advanced");

  let previewText: string | null = null;
  const previewBusy = preview.settling || preview.isFetching;
  if (!previewBusy && preview.data) {
    previewText = preview.data.has_criteria
      ? `Preview: ${preview.data.count.toLocaleString()} articles in the last ${preview.data.days} days would match`
      : `No criteria: every article matches (${preview.data.count.toLocaleString()})`;
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !saving && onClose()}>
      <DialogContent className="max-h-[90vh] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="font-heading">
            {isEdit && pir ? `Edit ${displayId("PIR", pir.id)}` : "New priority intelligence requirement"}
          </DialogTitle>
          <DialogDescription>
            What leadership needs to know. Articles that match the criteria are tracked as coverage.
          </DialogDescription>
        </DialogHeader>

        <form id={id("form")} noValidate onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
          <Field label="Title" htmlFor={titleId} error={titleError}>
            <Input
              ref={titleRef}
              id={titleId}
              value={title}
              aria-invalid={!!titleError}
              aria-describedby={fieldDescribedBy(titleId, { error: titleError })}
              onChange={(e) => {
                setTitle(e.target.value);
                if (titleError && e.target.value.trim()) setTitleError(undefined);
              }}
            />
          </Field>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold text-foreground">
                Priority
              </span>
              <SegmentedControl
                aria-label="Priority"
                options={PIR_PRIORITY_OPTIONS}
                value={priority}
                onChange={setPriority}
                className="self-start"
              />
            </div>
            <Field label="Owner" htmlFor={id("owner")}>
              <Input id={id("owner")} value={owner} onChange={(e) => setOwner(e.target.value)} />
            </Field>
            <Field label="Start date" htmlFor={id("start")}>
              <DateField id={id("start")} value={startDate} onChange={setStartDate} optional />
            </Field>
            <Field label="End date (optional)" htmlFor={id("end")}>
              <DateField id={id("end")} value={endDate} onChange={setEndDate} optional />
            </Field>
          </div>

          <p className="border-t border-border pt-4 text-2xs font-semibold tracking-wide text-muted-foreground">
            CRITERIA · AN ARTICLE MATCHES WHEN IT HITS ANY CHIP IN EVERY FILLED ROW
          </p>
          <Field label="Threat actors" htmlFor={id("actors")}>
            <ChipInput
              id={id("actors")}
              aria-label="Threat actors"
              placeholder="Add actor…"
              values={threatActors}
              onChange={setThreatActors}
              suggest={suggest.actors}
            />
          </Field>
          <div className="grid gap-4 lg:grid-cols-2">
            <Field label="Industries" htmlFor={id("industries")}>
              <ChipInput
                id={id("industries")}
                aria-label="Industries"
                placeholder="Add…"
                values={industries}
                onChange={setIndustries}
                suggest={suggest.industries}
              />
            </Field>
            <Field label="Countries" htmlFor={id("countries")} error={chipErrors.countries}>
              <ChipInput
                id={id("countries")}
                aria-label="Countries"
                placeholder="Add…"
                values={countries}
                onChange={guardedSetter(
                  "countries",
                  countries,
                  setCountries,
                  resolveCountry,
                  "Pick a country from the list",
                )}
                suggest={suggest.countries}
              />
            </Field>
            <Field label="ATT&CK techniques" htmlFor={id("ttps")} error={chipErrors.ttps}>
              <ChipInput
                id={id("ttps")}
                aria-label="ATT&CK techniques"
                placeholder="Add…"
                values={ttps}
                onChange={guardedSetter("ttps", ttps, setTtps, resolveTtp, "Pick a technique from the list")}
                suggest={suggest.ttps}
              />
            </Field>
            <Field label="Keywords" htmlFor={id("keywords")}>
              <ChipInput
                id={id("keywords")}
                aria-label="Keywords"
                placeholder="Add…"
                values={keywords}
                onChange={setKeywords}
              />
            </Field>
          </div>

          <div className="border-t border-border">
            <button
              type="button"
              aria-expanded={advancedOpen}
              aria-controls={advancedPanel}
              onClick={() => setAdvancedOpen((o) => !o)}
              className="flex w-full items-center justify-between gap-2 py-2.5 text-left text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              Advanced
              <ChevronDownIcon
                aria-hidden
                className={cn("size-4 text-muted-foreground transition-transform", advancedOpen && "rotate-180")}
              />
            </button>
            <div id={advancedPanel} hidden={!advancedOpen} className="flex flex-col gap-4 pb-2">
              <Field label="Description" htmlFor={id("description")}>
                <Textarea
                  id={id("description")}
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Field>
              <div className="grid gap-4 lg:grid-cols-2">
                <Field label="Malware and tools" htmlFor={id("malware")}>
                  <ChipInput
                    id={id("malware")}
                    aria-label="Malware and tools"
                    placeholder="Add…"
                    values={malware}
                    onChange={setMalware}
                    suggest={suggest.malware}
                  />
                </Field>
                <Field label="News types" htmlFor={id("news-types")} error={chipErrors.newsTypes}>
                  <ChipInput
                    id={id("news-types")}
                    aria-label="News types"
                    placeholder="Add…"
                    values={newsTypes}
                    onChange={guardedSetter(
                      "newsTypes",
                      newsTypes,
                      setNewsTypes,
                      resolveNewsType,
                      "Pick a news type from the list",
                    )}
                    suggest={suggest.newsTypes}
                  />
                </Field>
              </div>
              {isEdit && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-foreground">Status</span>
                  <SegmentedControl
                    aria-label="Status"
                    options={PIR_STATUS_TABS}
                    value={status}
                    onChange={setStatus}
                    className="self-start"
                  />
                </div>
              )}
            </div>
          </div>

          {apiError && (
            <p role="alert" className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive-text">
              {apiError}
            </p>
          )}

          <DialogFooter className="sm:items-center">
            <p aria-live="polite" className="flex min-h-5 items-center gap-2 text-xs text-muted-foreground sm:mr-auto">
              {previewBusy && (
                <>
                  <span
                    aria-hidden="true"
                    className="size-3.5 animate-spin rounded-full border-2 border-border border-t-foreground"
                  />
                  Counting matching articles…
                </>
              )}
              {/* Galat pratinjau: footer kosong (spec), simpan tetap bisa. */}
              {previewText}
            </p>
            <Button type="button" variant="ghost" disabled={saving} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {isEdit ? "Save" : "Create PIR"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
