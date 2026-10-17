import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api/schema";

type Tweet = components["schemas"]["TweetOut"];

/** Port `_buildBadges()` di `legacy/static/js/newsroom/xintel.js`. */
export function TweetBadges({ tweet: t, limit = 99 }: { tweet: Tweet; limit?: number }) {
  const badges: ReactNode[] = [];

  if (t.apac_indicator) {
    badges.push(
      <Badge key="apac" variant="outline" className="border-primary/30 bg-primary/10 text-xs text-primary-text">
        APAC
      </Badge>,
    );
  }
  if (t.ot_status) {
    badges.push(
      <Badge key="ot" variant="outline" className="border-warning/30 bg-warning/10 text-xs text-warning-text">
        OT
      </Badge>,
    );
  }
  if (t.confirmed_incident) {
    badges.push(
      <Badge
        key="confirmed"
        variant="outline"
        className="border-destructive/30 bg-destructive/10 text-xs text-destructive-text"
      >
        CONFIRMED
      </Badge>,
    );
  }
  if (t.report_status) {
    badges.push(
      <Badge key="report" variant="outline" className="border-ring/20 bg-ring/10 text-xs text-primary-text">
        REPORT
      </Badge>,
    );
  }
  if ((t.zero_day_list ?? []).length) {
    badges.push(
      <Badge
        key="0day"
        variant="outline"
        className="border-destructive/40 bg-destructive/15 text-xs font-bold text-destructive-text"
      >
        0-DAY
      </Badge>,
    );
  }
  (t.cve_list ?? []).slice(0, limit).forEach((cve) =>
    badges.push(
      <Badge
        key={`cve-${cve}`}
        variant="outline"
        className="border-destructive/20 bg-destructive/10 font-mono text-xs text-destructive-text"
      >
        {cve.toUpperCase()}
      </Badge>,
    ),
  );
  (t.mentioned_group ?? []).slice(0, limit).forEach((g) =>
    badges.push(
      <Badge key={`grp-${g}`} variant="outline" className="text-xs text-muted-foreground">
        {g}
      </Badge>,
    ),
  );

  return <>{badges}</>;
}
