"use client";

import Markdown from "react-markdown";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ExecBriefResponse } from "@/lib/api/loose-types";

interface ExecBriefModalProps {
  brief: ExecBriefResponse | null;
  days: number;
  onOpenChange: (open: boolean) => void;
}

/** Port modal AI Brief (`exec.js:731-755`). Legacy dump `d.brief` mentah
 * lewat `.textContent` padahal LLM-nya diinstruksiin markdown 5 section
 * `##` (`exec_brief.py` SYSTEM_PROMPT) -- di sini beneran di-render
 * `react-markdown` (pola sama kayak `ChangelogDialog`), bukan port
 * bug-nya. */
export function ExecBriefModal({ brief, days, onOpenChange }: ExecBriefModalProps) {
  return (
    <Dialog open={brief !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] w-full max-w-2xl overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Executive Brief</DialogTitle>
          {brief && (
            <p className="font-mono text-xs text-muted-foreground">
              Generated: {new Date(brief.generated_at).toLocaleString()} · Period: {days} days
            </p>
          )}
        </DialogHeader>
        <div className="prose prose-sm max-w-none text-xs leading-relaxed">
          <Markdown>{brief?.brief ?? ""}</Markdown>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => {
              if (!brief) return;
              void navigator.clipboard.writeText(brief.brief).then(() => toast.success("Copied to clipboard"));
            }}
          >
            Copy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
