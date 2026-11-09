"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { StatePanel } from "@/components/ui/state-panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type Team = components["schemas"]["CveTeamOut"];

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const EMAIL_ERROR = "Enter a full email address, for example name@example.com.";
const DUP_ERROR = "A team with this name already exists.";

interface Draft {
  name: string;
  lead_name: string;
  lead_email: string;
}
const EMPTY: Draft = { name: "", lead_name: "", lead_email: "" };

/** Galat per kolom dari respons gagal: 409 = nama kembar; 422 = daftar `{loc, msg}`. */
function fieldErrors(status: number, error: unknown): { name?: string; email?: string; other?: string } {
  if (status === 409) return { name: DUP_ERROR };
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (status === 422 && Array.isArray(detail)) {
    const locs = detail.map((d) => ((d as { loc?: unknown[] }).loc ?? []).map(String));
    if (locs.some((l) => l.includes("lead_email"))) return { email: EMAIL_ERROR };
    if (locs.some((l) => l.includes("name"))) return { name: "Enter a team name (1-200 characters)." };
  }
  return { other: typeof detail === "string" ? detail : "Request failed" };
}

interface RowFormProps {
  draft: Draft;
  onChange: (d: Draft) => void;
  errors: { name?: string; email?: string };
  label: string;
}

/** Tiga kolom isian (Name, Lead, Lead email) dipakai baris tambah dan baris edit. */
function RowFields({ draft, onChange, errors, label }: RowFormProps) {
  return (
    <>
      <TableCell className="align-top">
        <Input
          aria-label={`${label} name`}
          aria-invalid={!!errors.name}
          value={draft.name}
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
        />
        {errors.name && (
          <p role="alert" className="mt-1 whitespace-normal text-xs text-destructive-text">
            {errors.name}
          </p>
        )}
      </TableCell>
      <TableCell className="align-top">
        <Input
          aria-label={`${label} lead`}
          value={draft.lead_name}
          onChange={(e) => onChange({ ...draft, lead_name: e.target.value })}
        />
      </TableCell>
      <TableCell className="align-top">
        <Input
          aria-label={`${label} lead email`}
          type="email"
          aria-invalid={!!errors.email}
          value={draft.lead_email}
          onChange={(e) => onChange({ ...draft, lead_email: e.target.value })}
        />
        {errors.email && (
          <p role="alert" className="mt-1 whitespace-normal text-xs text-destructive-text">
            {errors.email}
          </p>
        )}
      </TableCell>
    </>
  );
}

/** Dialog "Owner teams" (spec 2a 6.9): tabel tim dengan baris tambah, edit inline, dan Deactivate (soft delete).
 * Tanpa Telegram (D25). Rename merambat ke `owner_team` ticket di backend; cocok-nama persis (btrim, case-sensitive). */
export function TeamsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const teamsQuery = useQuery({
    queryKey: ["cve", "teams"],
    enabled: open,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/cve/teams");
      if (error) throw error;
      return data.items;
    },
  });
  const teams = teamsQuery.data ?? [];

  const [adding, setAdding] = useState<Draft>(EMPTY);
  const [addErrors, setAddErrors] = useState<{ name?: string; email?: string }>({});
  const [editId, setEditId] = useState<number | null>(null);
  const [edit, setEdit] = useState<Draft>(EMPTY);
  const [editErrors, setEditErrors] = useState<{ name?: string; email?: string }>({});
  const [busy, setBusy] = useState<string | null>(null);

  function refresh(renamed = false) {
    void queryClient.invalidateQueries({ queryKey: ["cve", "teams"] });
    if (renamed) {
      for (const key of [["cve", "tickets"], ["cve", "dashboard"]]) void queryClient.invalidateQueries({ queryKey: key });
    }
  }

  function startEdit(t: Team) {
    setEditId(t.id);
    setEdit({ name: t.name, lead_name: t.lead_name, lead_email: t.lead_email });
    setEditErrors({});
  }

  async function add() {
    const name = adding.name.trim();
    if (!name) return setAddErrors({ name: "Enter a team name." });
    if (adding.lead_email.trim() && !EMAIL_RE.test(adding.lead_email.trim())) return setAddErrors({ email: EMAIL_ERROR });
    setBusy("add");
    try {
      const { error, response } = await api.POST("/api/cve/teams", {
        body: { name, lead_name: adding.lead_name.trim(), lead_email: adding.lead_email.trim() },
      });
      if (error) {
        const f = fieldErrors(response.status, error);
        if (f.other) throw new Error(f.other);
        return setAddErrors(f);
      }
      toast.success(`Team "${name}" added.`);
      setAdding(EMPTY);
      setAddErrors({});
      refresh();
    } catch (e) {
      toast.error(`Add failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function save(t: Team) {
    const name = edit.name.trim();
    if (!name) return setEditErrors({ name: "Enter a team name." });
    if (edit.lead_email.trim() && !EMAIL_RE.test(edit.lead_email.trim())) return setEditErrors({ email: EMAIL_ERROR });
    setBusy(`save-${t.id}`);
    try {
      const { error, response } = await api.PATCH("/api/cve/teams/{team_id}", {
        params: { path: { team_id: t.id } },
        body: { name, lead_name: edit.lead_name.trim(), lead_email: edit.lead_email.trim() },
      });
      if (error) {
        const f = fieldErrors(response.status, error);
        if (f.other) throw new Error(f.other);
        return setEditErrors(f);
      }
      const renamed = name !== t.name;
      toast.success(renamed ? "Team renamed. Tickets with the old name are updated." : "Team saved.");
      setEditId(null);
      refresh(renamed);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function deactivate(t: Team) {
    setBusy(`off-${t.id}`);
    try {
      const { error } = await api.DELETE("/api/cve/teams/{team_id}", { params: { path: { team_id: t.id } } });
      if (error) throw new Error("Request failed");
      toast.success(`Team "${t.name}" deactivated. Tickets keep the name.`);
      setEditId(null);
      refresh();
    } catch (e) {
      toast.error(`Deactivate failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Owner teams</DialogTitle>
          <DialogDescription>
            Teams offered in the ticket form. The lead receives the escalation email draft.
          </DialogDescription>
        </DialogHeader>
        {teamsQuery.isPending ? (
          <StatePanel variant="loading" title="Loading teams" />
        ) : teamsQuery.isError ? (
          <StatePanel
            variant="error"
            title="Could not load teams"
            action={
              <Button variant="outline" size="sm" onClick={() => void teamsQuery.refetch()}>
                Retry
              </Button>
            }
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Lead</TableHead>
                <TableHead>Lead email</TableHead>
                <TableHead className="text-right">Tickets</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {teams.map((t) =>
                editId === t.id ? (
                  <TableRow key={t.id}>
                    <RowFields draft={edit} onChange={setEdit} errors={editErrors} label={`Edit ${t.name}`} />
                    <TableCell className="text-right align-top font-code text-xs">{t.ticket_count}</TableCell>
                    <TableCell className="align-top">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button size="sm" loading={busy === `save-${t.id}`} onClick={() => void save(t)}>
                          Save
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditId(null)}>
                          Cancel
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          loading={busy === `off-${t.id}`}
                          onClick={() => void deactivate(t)}
                        >
                          Deactivate team
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : (
                  <TableRow key={t.id}>
                    <TableCell className="text-xs font-semibold">{t.name}</TableCell>
                    <TableCell className="text-xs">{t.lead_name || "—"}</TableCell>
                    <TableCell className="text-xs">{t.lead_email || "—"}</TableCell>
                    <TableCell className="text-right font-code text-xs">{t.ticket_count}</TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" aria-label={`Edit ${t.name}`} onClick={() => startEdit(t)}>
                        Edit
                      </Button>
                    </TableCell>
                  </TableRow>
                ),
              )}
              {teams.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-xs text-muted-foreground">
                    No teams yet. Add the first one below.
                  </TableCell>
                </TableRow>
              )}
              <TableRow className="hover:bg-transparent">
                <RowFields
                  draft={adding}
                  onChange={(d) => {
                    setAdding(d);
                    setAddErrors({});
                  }}
                  errors={addErrors}
                  label="New team"
                />
                <TableCell />
                <TableCell className="text-right align-top">
                  <Button size="sm" loading={busy === "add"} onClick={() => void add()}>
                    Add team
                  </Button>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        )}
        {editId !== null && (
          <p className="text-xs text-muted-foreground">Renaming a team updates the tickets that use the old name.</p>
        )}
      </DialogContent>
    </Dialog>
  );
}
