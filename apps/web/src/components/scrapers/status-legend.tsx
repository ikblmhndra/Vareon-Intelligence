import { Disclosure } from "@/components/ui/disclosure";

/** Legenda status, pola "How these metrics are calculated" di CVE Dashboard. Aturannya dari
 * `cti_scraper.health` (fungsi murni yang sama dengan digest Telegram). Terbuka lewat tautan toolbar. */
export function StatusLegend({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Disclosure
      id="status-legend"
      title="What the statuses mean"
      printOpen
      open={open}
      onOpenChange={onOpenChange}
      className="mt-4 rounded-2xl surface-raised p-4 text-sm"
    >
      <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
        <li>
          <strong className="text-foreground">OK</strong>: the latest run finished without errors or failed items.
        </li>
        <li>
          <strong className="text-foreground">Disabled</strong>: not scheduled. The line under the badge says who turned it off: an
          admin (with the reason they gave), the default in code, or the CVE mirror that replaces it.
        </li>
        <li>
          <strong className="text-foreground">Stale</strong>: the scraper has never run.
        </li>
        <li>
          <strong className="text-foreground">Dead</strong>: the latest run started more than three schedule intervals ago.
        </li>
        <li>
          <strong className="text-foreground">Degraded</strong>: the latest run failed (fetch, parse, rate limit, timeout or
          backpressure) or finished with items that failed to save.
        </li>
        <li>
          <strong className="text-foreground">Zero yield</strong>: the last three runs all finished with zero items.
        </li>
        <li>
          <strong className="text-foreground">Partial</strong> (a run status in LAST RUN and Run history): the run finished but
          some of its items failed; the scraper then shows as Degraded.
        </li>
        <li>
          <strong className="text-foreground">Unknown</strong>: the health check could not be loaded, so the status is not known.
        </li>
      </ul>
    </Disclosure>
  );
}
