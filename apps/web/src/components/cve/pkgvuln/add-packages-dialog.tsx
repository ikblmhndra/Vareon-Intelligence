"use client";

import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Dropzone } from "@/components/ui/dropzone";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { PkgAddResult } from "@/lib/api/loose-types";
import type { components } from "@/lib/api/schema";
import { getActiveClientId } from "@/lib/auth/client-id";
import { useDebounced } from "@/lib/cve/catalog";

type LockfileImportResult = components["schemas"]["LockfileImportResult"];

export const PKG_ECOSYSTEMS = ["npm", "PyPI", "Go", "Maven", "crates.io", "NuGet", "RubyGems", "Packagist", "Hex"];

const AUTO = "auto";
const ECOSYSTEM_ITEMS: Record<string, string> = {
  [AUTO]: "Detect from file",
  ...Object.fromEntries(PKG_ECOSYSTEMS.map((e) => [e, e])),
};
const LOCKFILE_ACCEPT = "package-lock.json,yarn.lock,poetry.lock,requirements.txt,go.sum,pom.xml,Gemfile.lock";
const LOCKFILE_HINT = "package-lock.json, yarn.lock, poetry.lock, requirements.txt, go.sum, pom.xml, Gemfile.lock";

type Mode = "single" | "import";

interface AddPackagesDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Segmen awal saat dialog dibuka ("+ Add package" = single, "Import lockfile" = import). */
  mode: Mode;
}

/** Dialog "Add packages" (spec 2a 6.9): satu paket (form inline lama) atau impor lockfile dengan dry run.
 * Body di dalam content supaya state bersih tiap dibuka. */
export function AddPackagesDialog({ open, onOpenChange, mode }: AddPackagesDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <AddBody initialMode={mode} onClose={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function invalidatePkgvuln(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "packages"] });
  void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "stats"] });
  void queryClient.invalidateQueries({ queryKey: ["pkgvuln", "vulns"] });
}

function AddBody({ initialMode, onClose }: { initialMode: Mode; onClose: () => void }) {
  const [mode, setMode] = useState<Mode>(initialMode);
  return (
    <>
      <DialogHeader>
        <DialogTitle>Add packages</DialogTitle>
        <DialogDescription>Monitor one package, or import everything pinned in a lockfile.</DialogDescription>
      </DialogHeader>
      <SegmentedControl
        aria-label="Add packages mode"
        value={mode}
        onChange={setMode}
        options={[
          { value: "single", label: "Single package" },
          { value: "import", label: "Import lockfile" },
        ]}
      />
      {mode === "single" ? <SingleForm onClose={onClose} /> : <ImportForm onClose={onClose} />}
    </>
  );
}

function SingleForm({ onClose }: { onClose: () => void }) {
  const uid = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [ecosystem, setEcosystem] = useState("npm");
  const [adding, setAdding] = useState(false);

  async function add() {
    if (!name.trim()) return;
    setAdding(true);
    try {
      const { data, error } = await api.POST("/api/pkgvuln/packages", {
        body: { name: name.trim(), ecosystem, version: version.trim() || undefined },
      });
      if (error) throw error;
      const d = data as unknown as PkgAddResult;
      if (!d.success) {
        toast.error("Add failed");
        return;
      }
      toast.success(`${name.trim()} added.`);
      // Scan berjalan di latar (BackgroundTasks): segarkan sekarang dan sekali lagi sesudah jeda.
      invalidatePkgvuln(queryClient);
      setTimeout(() => invalidatePkgvuln(queryClient), 4000);
      onClose();
    } catch {
      toast.error(`${name} already exists, or not found on ${ecosystem} registry`);
    } finally {
      setAdding(false);
    }
  }

  return (
    <>
      <Field label="Name" htmlFor={`${uid}-name`}>
        <Input id={`${uid}-name`} placeholder="e.g. lodash" value={name} onChange={(e) => setName(e.target.value)} className="font-code" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Version" htmlFor={`${uid}-version`} hint="Optional; empty monitors any version.">
          <Input id={`${uid}-version`} placeholder="e.g. 4.17.21" value={version} onChange={(e) => setVersion(e.target.value)} className="font-code" />
        </Field>
        <Field label="Ecosystem" htmlFor={`${uid}-eco`}>
          <Select items={ECOSYSTEM_ITEMS} value={ecosystem} onValueChange={(v) => v && setEcosystem(v)}>
            <SelectTrigger id={`${uid}-eco`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PKG_ECOSYSTEMS.map((e) => (
                <SelectItem key={e} value={e}>
                  {e}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={adding}>
          Cancel
        </Button>
        <Button disabled={!name.trim()} loading={adding} onClick={() => void add()}>
          Add package
        </Button>
      </DialogFooter>
    </>
  );
}

/** Teks galat API (`detail` string atau daftar 422 FastAPI) dari body respons proxy. */
async function responseError(resp: Response): Promise<string> {
  const raw = await resp.text();
  try {
    const detail = (JSON.parse(raw) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const msg = detail.map((d) => (d as { msg?: string }).msg ?? "").filter(Boolean).join("; ");
      if (msg) return msg;
    }
  } catch {
    // bukan JSON: pakai teks mentah di bawah
  }
  return raw || `Request failed (${resp.status})`;
}

/** Lewat proxy langsung (bukan klien openapi-fetch): butuh `FormData` multipart mentah. */
async function postLockfile(file: File, ecosystem: string, project: string, dryRun: boolean): Promise<LockfileImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("dry_run", dryRun ? "true" : "false");
  fd.append("ecosystem", ecosystem);
  fd.append("project", project);
  const clientId = getActiveClientId();
  const resp = await fetch("/api/proxy/api/pkgvuln/import-lockfile", {
    method: "POST",
    headers: clientId ? { "X-Client-ID": clientId } : undefined,
    body: fd,
  });
  if (!resp.ok) throw new Error(await responseError(resp));
  return (await resp.json()) as LockfileImportResult;
}

/** Impor lockfile: satu dry run per pilihan berkas/opsi (dry run backend = satu lookup per paket, mahal untuk
 * go.sum/yarn.lock besar), jadi Project di-debounce dan hasilnya di-cache per kunci; tombol Import memakai
 * opsi yang sama dengan pratinjau. */
function ImportForm({ onClose }: { onClose: () => void }) {
  const uid = useId();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [ecosystem, setEcosystem] = useState(AUTO);
  const [project, setProject] = useState("");
  const [importing, setImporting] = useState(false);
  const debouncedProject = useDebounced(project.trim());

  const fileKey = file ? `${file.name}:${file.size}:${file.lastModified}` : null;
  const preview = useQuery({
    queryKey: ["pkgvuln", "lockfile-preview", fileKey, ecosystem, debouncedProject],
    queryFn: () => postLockfile(file!, ecosystem, debouncedProject, true),
    enabled: file !== null,
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });

  // Selama Project belum selesai di-debounce, pratinjau belum cocok dengan opsi di layar.
  const stale = project.trim() !== debouncedProject;
  const data = preview.data;
  const shown = data && !stale && !preview.isFetching ? data : null;
  const errorText = preview.isError
    ? `${preview.error.message}${ecosystem === AUTO ? " Try choosing the ecosystem above." : ""}`
    : undefined;

  async function doImport() {
    if (!file || !shown) return;
    setImporting(true);
    try {
      const res = await postLockfile(file, ecosystem, debouncedProject, false);
      toast.success(`${res.added} added, ${res.skipped} already monitored`);
      // Scan tiap paket baru berjalan di latar: segarkan sekarang dan sekali lagi sesudah jeda.
      invalidatePkgvuln(queryClient);
      setTimeout(() => invalidatePkgvuln(queryClient), 5000);
      onClose();
    } catch (e) {
      toast.error(`Import failed: ${(e as Error).message}`);
    } finally {
      setImporting(false);
    }
  }

  const issues = shown ? [...shown.errors, ...(shown.unsupported > 0 ? [`${shown.unsupported} entries use an unsupported source and are skipped.`] : [])] : [];

  return (
    <>
      <Field label="Ecosystem" htmlFor={`${uid}-eco`}>
        <Select items={ECOSYSTEM_ITEMS} value={ecosystem} onValueChange={(v) => v && setEcosystem(v)}>
          <SelectTrigger id={`${uid}-eco`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={AUTO}>Detect from file</SelectItem>
            {PKG_ECOSYSTEMS.map((e) => (
              <SelectItem key={e} value={e}>
                {e}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Dropzone
        aria-label="Lockfile to import"
        accept={LOCKFILE_ACCEPT}
        hint={LOCKFILE_HINT}
        file={file}
        onFile={setFile}
        error={errorText}
      />
      <Field label="Project (optional)" htmlFor={`${uid}-project`} hint="Prefix for the source path, e.g. services/billing.">
        <Input id={`${uid}-project`} value={project} onChange={(e) => setProject(e.target.value)} maxLength={200} className="font-code" />
      </Field>
      {file && !preview.isError && (preview.isFetching || stale) && (
        <Notice busy title="Reading the lockfile">
          Counting packages and checking which are already monitored; large files can take a moment.
        </Notice>
      )}
      {file && shown && (
        <Notice tone="info" title={`${file.name} - ${shown.ecosystem || ecosystem} - ${shown.parsed} packages found - ${shown.already_monitored} already monitored`}>
          {shown.new} new{shown.version_changes > 0 ? `, ${shown.version_changes} with a changed version` : ""}.
          {issues.length > 0 && <span className="mt-1 block">{issues.slice(0, 3).join(" ")}</span>}
        </Notice>
      )}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose} disabled={importing}>
          Cancel
        </Button>
        <Button disabled={!shown || shown.new === 0} loading={importing} onClick={() => void doImport()}>
          {importing ? `Importing ${shown?.new ?? ""}...` : `Import ${shown?.new ?? ""}`.trim()}
        </Button>
      </DialogFooter>
    </>
  );
}
