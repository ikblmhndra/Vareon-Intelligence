# Tech catalog spike from CVE List V5

> **SUPERSEDED by `2026-10-07_cve_catalog_report_v2.md`.** **Reader's note (added after the report was read; the content below is unchanged).** This is the output of
> the **first version** of `tools/ops/spike_cve_catalog.py` on the full data (a CVE List V5 clone, 153,413 files).
> Three numbers in it are misleading because of weaknesses in the script, fixed in the next commit:
> (1) non-Latin product names (CJK plugins) were erased by normalisation and counted as "placeholder";
> (2) the `multi-produk` (3,940), `url-atau-repo` (3,938), and `terlalu-panjang` (1,198) shapes are mostly REAL
> products (WordPress plugin titles, `owner/repo` repos), not junk, so "10.7% of CVEs without a product" is an
> UPPER BOUND; (3) section 4 lists raw spellings, not what remains after normalisation (the real remainder is 218,
> see section 3). Section 7 mixes "missed by the pipeline" with "history from before the tracker existed". Interpretation and
> decisions: `docs/CVE_TECH_MATCHING.md` 7.1.3. The solid numbers: volume and growth, the per-tech verdicts,
> tracker recall. The long tail is solid as a DIRECTION (the numbers rise slightly after the fix, because identities
> that used to be dropped come in, and almost all of them have a tail of 1 CVE).
>
> **Label legend.** Labels in `code` and in the tables are the values the spike script prints and are kept
> as-is: junk kinds `placeholder`, `generik` (generic), `multi-produk` (multi-product), `url-atau-repo`
> (URL or repo), `url`, `terlalu-panjang` (too long), `angka-saja` (digits only), `mirip-versi` (version-like);
> name shapes `memuat-and-atau-titik-koma` (contains "and" or a semicolon), `judul-panjang` (long title),
> `owner/repo`; verdicts `bersih` (clean), `satu vendor, banyak produk` (one vendor, many products), `ambigu`
> (ambiguous), `tidak ada` (none); recall buckets `hanya-tracker` (tracker only), `hanya-katalog` (catalog only).


Created 2026-10-07. Window: published >= 2025-01-01.

## 1. Corpus

- CVE files read: **153413** (parse failures: 0; not PUBLISHED: 3531; no publish date: 0; published before the window: 32662).
- **CVEs analysed: 117220**

| Publish month | CVE |
|---|---|
| 2025-01 | 4023 |
| 2025-02 | 2852 |
| 2025-03 | 3849 |
| 2025-04 | 3959 |
| 2025-05 | 3659 |
| 2025-06 | 3339 |
| 2025-07 | 3693 |
| 2025-08 | 3453 |
| 2025-09 | 3803 |
| 2025-10 | 3724 |
| 2025-11 | 2975 |
| 2025-12 | 4487 |
| 2026-01 | 3887 |
| 2026-02 | 4214 |
| 2026-03 | 5910 |
| 2026-04 | 5627 |
| 2026-05 | 6673 |
| 2026-06 | 7757 |
| 2026-07 | 9741 |
| 2026-08 | 12239 |
| 2026-09 | 14862 |
| 2026-10 | 2494 |

## 2. Product data coverage (CNA)

| | CVE | % |
|---|---|---|
| has >= 1 product fit to be an identity | 104644 | 89.3% |
| only junk products (placeholder/generic/...) | 12576 | 10.7% |
| no `affected` at all | 0 | 0.0% |
| rescued by ADP data (CNA unusable) | 105 | 0.1% |
| contains CPE in the CNA data | 8829 | 7.5% |

CVEs without a usable product (CNA or ADP) = the ones that the `new_cve` gate currently sends to the text summary; in the new design they have NO identity and need their own path.

## 3. Catalog size and cleanliness

- **Raw** (vendor, product) pairs: 42710
- **Normalised** identities (lower case, punctuation to spaces, junk dropped): **37988** (14633 vendors)
- After **merging spellings** (no spaces, `Palo Alto` = `PaloAlto`): **37770** -> normalisation alone leaves 218 duplicates that can be merged automatically
- Estimated **product families** (trailing version tokens dropped; rough): **36543** -- the difference from the number above is version variants inflating the catalog (e.g. every Windows version = one product)
- Junk product entries: **16352**

| Junk kind | Entries | Examples |
|---|---|---|
| placeholder | 7029 | n/a; 워드프레스 결제 심플페이; 简数采集器; 评论小秘书; 微力同步 |
| multi-produk | 3940 | RAPIDS cuDF and cuML; User Activity Tracking and Log; Giveaways and Contests by RafflePress; MB Custom Post Types & Custom Taxonomies; Social Media Share Buttons & Social Sharing Icons |
| url-atau-repo | 3938 | hamza417/inure; chatwoot/chatwoot; parisneo/lollms-webui; shaunwei/realchar; mintplex-labs/anything-llm |
| terlalu-panjang | 1198 | Jetson AGX Orin series (including Jetson Orin NX series, Jetson Orin N; MWB HubSpot for WooCommerce – CRM, Abandoned Cart, Email Marketing, Ma; Content Control – The Ultimate Content Restriction Plugin! Restrict Co; ClickWhale – Link Manager, Link Shortener and Click Tracker for Affili; s2Member – Excellent for All Kinds of Memberships, Content Restriction |
| generik | 217 | Web Application; firmware; Server; platform; Mobile Application |
| angka-saja | 27 | 4769; 0752-8303-8000-0002; 777; 0852-1322; 0852-1328 |
| mirip-versi | 3 | 130.8005 |

**Long tail** (identities by number of CVEs in the window):

| CVE count | Identities |
|---|---|
| 1 CVE | 23808 |
| 2-4 CVE | 8994 |
| 5-19 CVE | 4314 |
| >=20 CVE | 872 |

If the picker only shows identities with >= 5 CVEs, the catalog size = 5186; the rest is a tail that is mostly noise or one-off products.

**Families with the most variants** (candidates for merging or hiding in the picker):

| Vendor | Family | Variants | CVE |
|---|---|---|---|
| dell | latitude | 47 | 49 |
| siemens | industrial edge device kit | 42 | 52 |
| dlink | dir | 41 | 219 |
| dell | poweredge | 40 | 40 |
| siemens | mendix studio pro | 30 | 31 |
| dell | precision | 27 | 27 |
| phoenixcontact | fl switch | 19 | 418 |
| dell | inspiron | 18 | 29 |
| dlink | dns | 16 | 396 |
| brotherindustriesltd | ads | 14 | 59 |
| dell | vostro | 14 | 14 |
| dell | powerstore | 13 | 218 |
| dell | xps | 13 | 13 |
| dlink | dsl | 13 | 15 |
| microsoft | microsoft visual studio | 13 | 182 |

## 4. Spelling duplicates (merge candidates), top 25

Different spellings that become the same identity once compacted (what remains AFTER case/punctuation normalisation):

| Key | CVE | Spellings (count) |
|---|---|---|
| `microsoft|windows11version23h2` | 2887 | Microsoft | Windows 11 Version 23H2 (1860); Microsoft | Windows 11 version 23H2 (1027) |
| `microsoft|windows11version26h1` | 1582 | Microsoft | Windows 11 version 26H1 (1558); Microsoft | Windows 11 Version 26H1 (24) |
| `openclaw|openclaw` | 639 | OpenClaw | OpenClaw (597); openclaw | openclaw (42) |
| `huawei|harmonyos` | 349 | Huawei | HarmonyOS (346); Huawei | Harmony OS (3) |
| `ibm|i` | 159 | ibm | i (156); IBM | i (3) |
| `misp|misp` | 138 | misp | misp (70); MISP | MISP (68) |
| `getgrav|grav` | 137 | getgrav | grav (136); getgrav | Grav (1) |
| `flowiseai|flowise` | 121 | FlowiseAI | Flowise (116); flowiseai | flowise (5) |
| `capgo|capgo` | 100 | Capgo | Capgo (82); Cap-go | capgo (17); Cap-go | Cap-go (1) |
| `vllmproject|vllm` | 95 | vllm-project | vllm (91); vllm-project | vLLM (4) |
| `mongodb|mongodbserver` | 90 | MongoDB | MongoDB Server (89); MongoDB | MongoDB server (1) |
| `portabilis|ieducar` | 87 | Portabilis | i-Educar (72); portabilis | i-educar (15) |
| `wolfssl|wolfssl` | 87 | wolfSSL | wolfSSL (85); wolfssl | wolfssl (1); wolfSSL | wolfssl (1) |
| `grokability|snipeit` | 85 | grokability | snipe-it (84); Grokability | Snipe-IT (1) |
| `fortinet|fortios` | 80 | fortinet | fortios (79); Fortinet | FortiOS (1) |
| `ibm|websphereapplicationserver` | 72 | ibm | websphere_application_server (71); IBM | WebSphere Application Server (1) |
| `oisf|suricata` | 69 | OISF | suricata (67); OISF | Suricata (2) |
| `thorsten|phpmyfaq` | 62 | thorsten | phpMyFAQ (49); thorsten | phpmyfaq (13) |
| `frappe|frappe` | 61 | frappe | frappe (59); Frappe | Frappe (2) |
| `paloaltonetworks|panos` | 59 | palo_alto_networks | pan-os (37); paloaltonetworks | pan-os (15); Palo Alto Networks | PAN-OS (7) |
| `dokploy|dokploy` | 58 | Dokploy | dokploy (57); dokploy | dokploy (1) |
| `legionofthebouncycastleinc|bcjava` | 58 | Legion of the Bouncy Castle Inc. | BC-JAVA (55); Legion of the Bouncy Castle Inc. | BC Java (3) |
| `vim|vim` | 56 | vim | vim (55); Vim | Vim (1) |
| `wazuh|wazuh` | 56 | wazuh | wazuh (55); Wazuh | Wazuh (1) |
| `paloaltonetworks|globalprotectapp` | 54 | palo_alto_networks | globalprotect_app (27); Palo Alto Networks | GlobalProtect App (18); paloaltonetworks | globalprotect_app (8); Palo Alto Networks | Global Protect App (1) |

## 5. The 40 identities with the most CVEs

| Vendor | Product | CVE | First | Last | Raw spellings |
|---|---|---|---|---|---|
| linux | linux | 10064 | 2025-01-06 | 2026-10-06 | 1 |
| google | chrome | 3388 | 2025-01-08 | 2026-10-06 | 1 |
| microsoft | windows server 2025 | 2502 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2025 server core installation | 2500 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 11 version 24h2 | 2333 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2022 | 2288 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2019 | 2169 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2019 server core installation | 2168 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 10 version 22h2 | 2057 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 10 version 21h2 | 2056 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 10 version 1809 | 2046 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2016 | 1877 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2016 server core installation | 1877 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 11 version 23h2 | 1860 | 2025-01-14 | 2026-09-08 | 2 |
| microsoft | windows 11 version 25h2 | 1816 | 2025-10-14 | 2026-09-08 | 1 |
| microsoft | windows 10 version 1607 | 1755 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 11 version 26h1 | 1558 | 2025-01-14 | 2026-09-14 | 2 |
| microsoft | windows server 2012 r2 | 1469 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2012 r2 server core installation | 1469 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2012 | 1389 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows server 2012 server core installation | 1389 | 2025-01-14 | 2026-09-08 | 1 |
| apple | macos | 1362 | 2025-01-15 | 2026-09-28 | 1 |
| microsoft | windows server 2022 23h2 edition server core installation | 1056 | 2025-01-14 | 2026-05-12 | 1 |
| redhat | enterprise linux | 848 | 2025-01-09 | 2026-10-07 | 1 |
| microsoft | windows 11 version 22h3 | 829 | 2025-01-14 | 2026-04-14 | 1 |
| google | android | 747 | 2025-01-02 | 2026-10-06 | 1 |
| mozilla | firefox | 736 | 2025-01-07 | 2026-10-06 | 1 |
| mozilla | thunderbird | 706 | 2025-01-07 | 2026-09-30 | 1 |
| openclaw | openclaw | 639 | 2026-02-01 | 2026-09-29 | 2 |
| microsoft | windows 11 version 22h2 | 601 | 2025-01-14 | 2026-06-09 | 1 |
| apple | visionos | 571 | 2025-01-15 | 2026-09-14 | 1 |
| microsoft | microsoft 365 apps for enterprise | 509 | 2025-01-14 | 2026-09-25 | 1 |
| microsoft | microsoft office ltsc 2024 | 500 | 2025-01-14 | 2026-09-25 | 1 |
| apple | watchos | 493 | 2025-01-15 | 2026-09-14 | 1 |
| microsoft | microsoft office ltsc 2021 | 487 | 2025-01-14 | 2026-09-25 | 1 |
| apple | tvos | 471 | 2025-01-15 | 2026-09-14 | 1 |
| microsoft | microsoft office 2019 | 463 | 2025-01-14 | 2026-09-08 | 1 |
| microsoft | windows 10 version 1507 | 448 | 2025-01-14 | 2025-12-09 | 1 |
| qualcomm inc | snapdragon | 425 | 2025-01-06 | 2026-10-06 | 1 |
| microsoft | microsoft office ltsc for mac 2024 | 419 | 2025-01-14 | 2026-09-08 | 1 |

## 6. The 34 production techs against the catalog

`hit` = CVEs whose CNA vendor/product/package/CPE names that tech (whole word), the same as the `new_cve` gate. **Verdict**: `bersih` (clean) = one vendor AND one product hold >= 80% of hits; `satu vendor, banyak produk` (one vendor, many products) = clear vendor but the products are spread out (the hierarchy case: one tech must map to several products); `ambigu` (ambiguous) = even the vendor is spread out (needs a human decision when mapping); `tidak ada` (none) = no hits (the tech name is not a name CNAs use, or there really is no CVE in the window).

| Tech | Hit | Verdict | Top vendor | Top product | Top identities (CVE) |
|---|---|---|---|---|---|
| anydesk | 3 | bersih | 100% | 100% | anydesk | anydesk (3) |
| burp suite | 1 | bersih | 100% | 100% | portswigger | burp suite dast (1) |
| crowdstrike | 6 | satu vendor, banyak produk | 92% | 50% | crowdstrike | falcon sensor for windows (6); crowdstrike | falcon sensor for linux (1); crowdstrike | falcon kubernetes admission controller (1) |
| ejbca | 2 | bersih | 100% | 100% | primekey solutions ab | ejbca (2) |
| esxi | 16 | ambigu | 62% | 62% | vmware | esxi (8); n a | intel r data center graphics driver for vmware esxi software (3); n a | vmware esxi (1) |
| extrahop | 0 | tidak ada | - | - | - |
| fortigate | 0 | tidak ada | - | - | - |
| fortinet | 311 | satu vendor, banyak produk | 100% | 15% | fortinet | fortios (80); fortinet | fortiproxy (44); fortinet | fortimanager (40) |
| gitlab | 391 | bersih | 97% | 95% | gitlab | gitlab (372); gitlab | ai gateway (4); jenkins project | jenkins gitlab plugin (3) |
| grafana | 88 | ambigu | 75% | 28% | grafana | grafana oss (33); grafana | grafana (16); grafana | grafana enterprise (16) |
| graylog | 16 | ambigu | 56% | 56% | graylog2 | graylog2 server (9); graylog | graylog web interface (7) |
| harmony sase | 1 | bersih | 100% | 100% | checkpoint | check point harmony sase (1) |
| jira | 21 | ambigu | 77% | 42% | atlassian | jira align (11); atlassian | jira service management data center (3); atlassian | jira software data center (2) |
| juniper | 168 | satu vendor, banyak produk | 100% | 53% | juniper networks | junos os (116); juniper networks | junos os evolved (62); juniper networks | junos space (28) |
| junos | 160 | satu vendor, banyak produk | 100% | 56% | juniper networks | junos os (116); juniper networks | junos os evolved (62); juniper networks | junos space (28) |
| mariadb | 23 | ambigu | 60% | 27% | mariadb corporation | mariadb connector j (4); mariadb corporation | mariadb connector nodejs (3); mariadb | mariadb (2) |
| maxscale | 0 | tidak ada | - | - | - |
| microsoft 365 | 542 | bersih | 99% | 94% | microsoft | microsoft 365 apps for enterprise (509); microsoft | microsoft 365 copilot (14); microsoft | microsoft 365 copilot s business chat (7) |
| mikrotik | 19 | bersih | 100% | 95% | mikrotik | routeros (19); mikrotik | cloud hosted router (1) |
| n8n | 210 | bersih | 83% | 83% | n8n io | n8n (272); n8n | n8n (42); czlonkowski | n8n mcp (9) |
| nagios | 50 | ambigu | 75% | 41% | nagios | xi (23); nagios | log server (12); nagios enterprises llc | nagios core (7) |
| nessus | 8 | satu vendor, banyak produk | 88% | 62% | tenable | nessus (5); tenable | nessus agent (2); tenable inc | tenable nessus tenable nessus agent (1) |
| new relic | 0 | tidak ada | - | - | - |
| nginx | 80 | ambigu | 61% | 23% | f5 | nginx open source (23); f5 | nginx plus (21); 0xjacky | nginx ui (15) |
| okta | 23 | satu vendor, banyak produk | 95% | 50% | okta | okta access gateway (11); okta | okta sdk java (2); okta | okta privileged access client (2) |
| outlook | 24 | ambigu | 68% | 40% | microsoft | microsoft outlook 2016 (10); microsoft | microsoft outlook for android (3); hclsoftware | traveler for microsoft outlook (2) |
| palo alto | 150 | satu vendor, banyak produk | 96% | 17% | palo alto networks | cloud ngfw (58); palo alto networks | prisma access (57); palo alto networks | globalprotect app (45) |
| perimeter81 | 0 | tidak ada | - | - | - |
| proofpoint | 3 | satu vendor, banyak produk | 100% | 67% | proofpoint | enterprise protection (2); proofpoint | insider threat management itm server (1) |
| proxmox | 2 | ambigu | 50% | 50% | bpg | terraform provider proxmox (1); proxmox | pmg api (1) |
| splunk | 182 | satu vendor, banyak produk | 100% | 49% | splunk | splunk enterprise (120); splunk | splunk cloud platform (45); splunk | splunk soar (16) |
| suricata | 74 | bersih | 92% | 92% | oisf | suricata (69); netgate | pfsense ce (4); suse | opensuse tumbleweed (2) |
| thales | 2 | ambigu | 50% | 50% | thales cert | suspicious (1); thales | sconnect (1) |
| wazuh | 67 | bersih | 100% | 82% | wazuh | wazuh (56); wazuh | wazuh manager (8); wazuh | wazuh agent (2) |

Summary: clean 10, one vendor many products 9, ambiguous 10, none 5, out of 34.

## 7. Recall against the tracker

Per tech, only CVEs published in the window (`di luar` (outside) = tracker rows published before the window, which cannot be assessed). `hanya-tracker` = found by keyword search but NOT by identity matching (an old false match, or a different CNA name); `hanya-katalog` = found by identity but NOT in the tracker (missed by the 8-day keyword search, or published before the tech was added).

| Tech | Tracker | Outside | In window | Both | Tracker only | Catalog only |
|---|---|---|---|---|---|---|
| anydesk | 0 | 0 | 0 | 0 | 0 | 3 |
| burp suite | 0 | 0 | 0 | 0 | 0 | 1 |
| crowdstrike | 0 | 0 | 0 | 0 | 0 | 6 |
| ejbca | 0 | 0 | 0 | 0 | 0 | 2 |
| esxi | 0 | 0 | 0 | 0 | 0 | 16 |
| fortinet | 2 | 0 | 2 | 2 | 0 | 309 |
| gitlab | 12 | 0 | 12 | 12 | 0 | 379 |
| grafana | 4 | 1 | 3 | 2 | 1 | 86 |
| graylog | 1 | 0 | 1 | 1 | 0 | 15 |
| harmony sase | 0 | 0 | 0 | 0 | 0 | 1 |
| jira | 1 | 0 | 1 | 1 | 0 | 20 |
| juniper | 0 | 0 | 0 | 0 | 0 | 168 |
| junos | 0 | 0 | 0 | 0 | 0 | 160 |
| mariadb | 0 | 0 | 0 | 0 | 0 | 23 |
| microsoft 365 | 2 | 0 | 2 | 2 | 0 | 540 |
| mikrotik | 1 | 0 | 1 | 1 | 0 | 18 |
| n8n | 16 | 0 | 16 | 16 | 0 | 194 |
| nagios | 0 | 0 | 0 | 0 | 0 | 50 |
| nessus | 6 | 6 | 0 | 0 | 0 | 8 |
| nginx | 6 | 0 | 6 | 6 | 0 | 74 |
| okta | 0 | 0 | 0 | 0 | 0 | 23 |
| outlook | 0 | 0 | 0 | 0 | 0 | 24 |
| palo alto | 0 | 0 | 0 | 0 | 0 | 150 |
| proofpoint | 0 | 0 | 0 | 0 | 0 | 3 |
| proxmox | 1 | 0 | 1 | 1 | 0 | 1 |
| splunk | 0 | 0 | 0 | 0 | 0 | 182 |
| suricata | 19 | 0 | 19 | 19 | 0 | 55 |
| thales | 0 | 0 | 0 | 0 | 0 | 2 |
| wazuh | 2 | 0 | 2 | 2 | 0 | 65 |

**Tracker rows also found by the catalog: 65/66 (98.5%).**

Examples for manual review (max 8 per tech):

- **anydesk** hanya-tracker: - | hanya-katalog: CVE-2025-34499, CVE-2026-15681, CVE-2026-15682
- **burp suite** hanya-tracker: - | hanya-katalog: CVE-2026-90481
- **crowdstrike** hanya-tracker: - | hanya-katalog: CVE-2025-1146, CVE-2025-42701, CVE-2025-42706, CVE-2026-40050, CVE-2026-40058, CVE-2026-76380
- **ejbca** hanya-tracker: - | hanya-katalog: CVE-2025-3026, CVE-2025-3027
- **esxi** hanya-tracker: - | hanya-katalog: CVE-2025-22224, CVE-2025-22225, CVE-2025-22226, CVE-2025-41226, CVE-2025-41227, CVE-2025-41228, CVE-2025-41236, CVE-2025-41237
- **fortinet** hanya-tracker: - | hanya-katalog: CVE-2024-21758, CVE-2024-21760, CVE-2024-23104, CVE-2024-23106, CVE-2024-26006, CVE-2024-26008, CVE-2024-26009, CVE-2024-26012
- **gitlab** hanya-tracker: - | hanya-katalog: CVE-2024-10219, CVE-2024-10307, CVE-2024-10383, CVE-2024-10925, CVE-2024-11129, CVE-2024-11222, CVE-2024-11931, CVE-2024-12093
- **grafana** hanya-tracker: CVE-2026-75786 | hanya-katalog: CVE-2024-11741, CVE-2024-11831, CVE-2025-10630, CVE-2025-1088, CVE-2025-10894, CVE-2025-11065, CVE-2025-11539, CVE-2025-12141
- **graylog** hanya-tracker: - | hanya-katalog: CVE-2025-30373, CVE-2025-46827, CVE-2025-53106, CVE-2026-1435, CVE-2026-1436, CVE-2026-1437, CVE-2026-1438, CVE-2026-1439
- **harmony sase** hanya-tracker: - | hanya-katalog: CVE-2025-3831
- **jira** hanya-tracker: - | hanya-katalog: CVE-2025-22157, CVE-2025-22167, CVE-2025-22168, CVE-2025-22169, CVE-2025-22170, CVE-2025-22171, CVE-2025-22172, CVE-2025-22173
- **juniper** hanya-tracker: - | hanya-katalog: CVE-2024-39564, CVE-2025-11198, CVE-2025-13914, CVE-2025-21589, CVE-2025-21590, CVE-2025-21591, CVE-2025-21592, CVE-2025-21593
- **junos** hanya-tracker: - | hanya-katalog: CVE-2024-39564, CVE-2025-21590, CVE-2025-21591, CVE-2025-21592, CVE-2025-21593, CVE-2025-21594, CVE-2025-21595, CVE-2025-21596
- **mariadb** hanya-tracker: - | hanya-katalog: CVE-2025-13699, CVE-2026-32710, CVE-2026-3494, CVE-2026-35549, CVE-2026-44168, CVE-2026-44169, CVE-2026-44170, CVE-2026-44171
- **microsoft 365** hanya-tracker: - | hanya-katalog: CVE-2025-1488, CVE-2025-21186, CVE-2025-21345, CVE-2025-21346, CVE-2025-21354, CVE-2025-21356, CVE-2025-21357, CVE-2025-21362
- **mikrotik** hanya-tracker: - | hanya-katalog: CVE-2025-10948, CVE-2025-42611, CVE-2025-6443, CVE-2025-6563, CVE-2026-14227, CVE-2026-16347, CVE-2026-56719, CVE-2026-67276
- **n8n** hanya-tracker: - | hanya-katalog: CVE-2025-46343, CVE-2025-49592, CVE-2025-49595, CVE-2025-52478, CVE-2025-52554, CVE-2025-57749, CVE-2025-58177, CVE-2025-61914
- **nagios** hanya-tracker: - | hanya-katalog: CVE-2024-13986, CVE-2024-13992, CVE-2024-13993, CVE-2024-13994, CVE-2024-13995, CVE-2024-13996, CVE-2024-13997, CVE-2024-13998
- **nessus** hanya-tracker: - | hanya-katalog: CVE-2025-24914, CVE-2025-24915, CVE-2025-36625, CVE-2025-36630, CVE-2025-36640, CVE-2026-33694, CVE-2026-57587, CVE-2026-57588
- **nginx** hanya-tracker: - | hanya-katalog: CVE-2024-56236, CVE-2025-1097, CVE-2025-1098, CVE-2025-12014, CVE-2025-14727, CVE-2025-15566, CVE-2025-1695, CVE-2025-1974
- **okta** hanya-tracker: - | hanya-katalog: CVE-2025-66033, CVE-2025-67505, CVE-2025-7371, CVE-2026-25193, CVE-2026-77585, CVE-2026-78074, CVE-2026-78545, CVE-2026-78550
- **outlook** hanya-tracker: - | hanya-katalog: CVE-2024-23581, CVE-2024-42190, CVE-2024-42191, CVE-2024-42192, CVE-2025-0916, CVE-2025-21259, CVE-2025-21357, CVE-2025-21361
- **palo alto** hanya-tracker: - | hanya-katalog: CVE-2025-0103, CVE-2025-0104, CVE-2025-0105, CVE-2025-0106, CVE-2025-0107, CVE-2025-0108, CVE-2025-0109, CVE-2025-0110
- **proofpoint** hanya-tracker: - | hanya-katalog: CVE-2024-10635, CVE-2025-0431, CVE-2025-8558
- **proxmox** hanya-tracker: - | hanya-katalog: CVE-2026-25499
- **splunk** hanya-tracker: - | hanya-katalog: CVE-2025-0367, CVE-2025-20226, CVE-2025-20227, CVE-2025-20228, CVE-2025-20229, CVE-2025-20230, CVE-2025-20231, CVE-2025-20232
- **suricata** hanya-tracker: - | hanya-katalog: CVE-2024-55605, CVE-2024-55626, CVE-2024-55627, CVE-2024-55628, CVE-2024-55629, CVE-2025-29915, CVE-2025-29916, CVE-2025-29917
- **thales** hanya-tracker: - | hanya-katalog: CVE-2026-13014, CVE-2026-18397
- **wazuh** hanya-tracker: - | hanya-katalog: CVE-2024-1243, CVE-2024-35177, CVE-2024-47770, CVE-2025-15612, CVE-2025-15615, CVE-2025-15616, CVE-2025-15617, CVE-2025-24016

## 8. Measurement limits

- Tech matching uses CNA data only (ADP only rescues CVEs without a usable product). NVD/CPE enrichment added later is NOT counted.
- `hit` measures a NAME match, not correctness; a `bersih` verdict means the identity is consistent, not that it is the product the client means. Human review is still mandatory.
- The `new_cve` gate also falls back to the text summary when the product is empty; this spike does not imitate that fallback.
- CVEs published before the window are not counted; ID years outside `--id-years` are not scanned.
- Duplicates are only those caught by simple normalisation; similarities that need knowledge (`PAN-OS` vs `Palo Alto`) are not detected. 'Product families' is a rough estimate.
