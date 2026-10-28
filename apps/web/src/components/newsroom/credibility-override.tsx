"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorMessage } from "@/lib/newsletter/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

type Article = components["schemas"]["ArticleOut"];

const COMPUTED = "computed";
const LEVELS = ["1", "2", "3", "4", "5", "6"];
// `items` supaya trigger menampilkan label "Computed", bukan nilai mentah, sebelum popup pernah dibuka.
const ITEMS: Record<string, string> = { [COMPUTED]: "Computed", ...Object.fromEntries(LEVELS.map((l) => [l, l])) };

/** Override kredibilitas artikel oleh analis (P6 5.1, `PUT /api/articles/{id}/credibility`).
 * "Computed" mengirim `null` = hapus override. Pemanggil yang menyembunyikan kontrol ini dari user
 * tanpa `manage_intel`; API tetap menegakkan izinnya. Sesudah berhasil, query artikel newsroom,
 * dashboard dan dialog artikel-by-id di-invalidate, dan artikel baru diteruskan ke `onSaved` karena
 * modal memegang objek artikel di state induk (tidak ikut refetch). */
export function CredibilityOverride({ article, onSaved }: { article: Article; onSaved: (a: Article) => void }) {
  const queryClient = useQueryClient();
  const isOverride = article.score_reasons.credibility.includes("analyst");
  const current = isOverride && article.credibility != null ? String(article.credibility) : COMPUTED;
  const [value, setValue] = useState(current);
  const [note, setNote] = useState("");
  // pilihan sama dengan keadaan sekarang tanpa catatan = PUT no-op + baris audit palsu
  const unchanged = value === current && note.trim() === "";

  const mutation = useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.PUT("/api/articles/{article_id}/credibility", {
        params: { path: { article_id: article.id } },
        body: { credibility: value === COMPUTED ? null : Number(value), note },
      });
      if (!response.ok || !data) throw new Error(errorMessage(error));
      return data;
    },
    onSuccess: (updated) => {
      toast.success(value === COMPUTED ? "Credibility override cleared" : `Credibility set to ${value}`);
      setNote("");
      onSaved(updated);
      void queryClient.invalidateQueries({ queryKey: ["newsroom", "articles"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["campaign-clusters", "article-by-id"] });
    },
    onError: (e: Error) => toast.error(`Override failed: ${e.message}`),
  });

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Select items={ITEMS} value={value} onValueChange={(v) => setValue(v ?? COMPUTED)}>
        <SelectTrigger size="sm" className="w-32 text-xs" aria-label="Credibility override">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={COMPUTED} className="text-xs">
            Computed
          </SelectItem>
          {LEVELS.map((l) => (
            <SelectItem key={l} value={l} className="text-xs">
              {l}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        aria-label="Override note"
        placeholder="Note (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        className="h-9 w-56 text-xs"
      />
      <Button size="sm" variant="outline" disabled={mutation.isPending || unchanged} onClick={() => mutation.mutate()}>
        {mutation.isPending ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
