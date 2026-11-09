// Penjabaran vektor CVSS (v2/v3/v4) ke nama metrik dan nilai yang terbaca; dipakai bagian "More" panel
// detail CVE. Port `expandCvssVector()` (`cve.js:693-744`).

const METRIC_NAMES: Record<string, string> = {
  AV: "Attack Vector",
  AC: "Attack Complexity",
  PR: "Privileges Required",
  UI: "User Interaction",
  S: "Scope",
  C: "Confidentiality Impact",
  I: "Integrity Impact",
  A: "Availability Impact",
  AT: "Attack Requirements",
  VC: "Vuln. Confidentiality",
  VI: "Vuln. Integrity",
  VA: "Vuln. Availability",
  SC: "Sub. Confidentiality",
  SI: "Sub. Integrity",
  SA: "Sub. Availability",
  Au: "Authentication",
};

const METRIC_VALUES: Record<string, Record<string, string>> = {
  AV: { N: "Network", A: "Adjacent Network", L: "Local", P: "Physical" },
  AC: { L: "Low", M: "Medium", H: "High" },
  PR: { N: "None", L: "Low", H: "High" },
  UI: { N: "None", R: "Required" },
  S: { U: "Unchanged", C: "Changed" },
  C: { N: "None", L: "Low", H: "High", P: "Partial", C: "Complete" },
  I: { N: "None", L: "Low", H: "High", P: "Partial", C: "Complete" },
  A: { N: "None", L: "Low", H: "High", P: "Partial", C: "Complete" },
  Au: { N: "None", S: "Single", M: "Multiple" },
  AT: { N: "None", P: "Present" },
  VC: { N: "None", L: "Low", H: "High" },
  VI: { N: "None", L: "Low", H: "High" },
  VA: { N: "None", L: "Low", H: "High" },
  SC: { N: "None", L: "Low", H: "High" },
  SI: { N: "None", L: "Low", H: "High", S: "Safety" },
  SA: { N: "None", L: "Low", H: "High", S: "Safety" },
};

export interface CvssRow {
  key: string;
  val: string;
  name: string;
  label: string;
}

/** "CVSS:3.1/AV:N/AC:L/..." -> baris {AV, N, "Attack Vector", "Network"}; pasangan tak berbentuk dilewati. */
export function cvssRows(vector: string): CvssRow[] {
  const clean = vector.replace(/^CVSS:[0-9.]+\//, "");
  return clean.split("/").flatMap((pair) => {
    const ci = pair.indexOf(":");
    if (ci === -1) return [];
    const key = pair.slice(0, ci);
    const val = pair.slice(ci + 1);
    return [{ key, val, name: METRIC_NAMES[key] || key, label: METRIC_VALUES[key]?.[val] || val }];
  });
}
