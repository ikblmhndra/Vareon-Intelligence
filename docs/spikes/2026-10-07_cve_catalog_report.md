# Spike katalog tech dari CVE List V5

> **Catatan pembaca (ditambahkan setelah laporan dibaca, isi di bawah tidak diubah).** Ini keluaran
> `tools/ops/spike_cve_catalog.py` **versi pertama** di data penuh (clone CVE List V5, 153.413 berkas).
> Tiga angka di dalamnya menyesatkan karena kelemahan skrip, yang sudah diperbaiki di commit berikutnya:
> (1) nama produk non-Latin (plugin CJK) dihapus normalisasi dan dihitung "placeholder";
> (2) bentuk `multi-produk` (3.940), `url-atau-repo` (3.938), dan `terlalu-panjang` (1.198) mayoritas produk
> ASLI (judul plugin WordPress, repo `owner/repo`), bukan sampah, sehingga "10,7% CVE tanpa produk" adalah
> BATAS ATAS; (3) bagian 4 mencantumkan ejaan mentah, bukan sisa setelah normalisasi (sisa sebenarnya 218,
> lihat bagian 3). Bagian 7 mencampur "kelewat pipeline" dengan "riwayat sebelum tracker ada". Tafsir dan
> keputusan: `docs/CVE_TECH_MATCHING.md` 7.1.3. Angka yang kokoh: volume dan pertumbuhan, vonis per tech,
> recall tracker. Ekor panjang kokoh sebagai ARAH (angka naik sedikit setelah perbaikan, karena identitas
> yang tadinya dibuang masuk dan hampir semuanya berekor 1 CVE).


Dibuat 2026-10-07. Jendela: terbit >= 2025-01-01.

## 1. Korpus

- Berkas CVE dibaca: **153413** (gagal parse: 0; bukan PUBLISHED: 3531; tanpa tanggal terbit: 0; terbit sebelum jendela: 32662).
- **CVE dianalisis: 117220**

| Bulan terbit | CVE |
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

## 2. Cakupan data produk (CNA)

| | CVE | % |
|---|---|---|
| punya >= 1 produk yang layak jadi identitas | 104644 | 89.3% |
| hanya produk sampah (placeholder/generik/...) | 12576 | 10.7% |
| tanpa `affected` sama sekali | 0 | 0.0% |
| diselamatkan data ADP (CNA tak berguna) | 105 | 0.1% |
| memuat CPE di data CNA | 8829 | 7.5% |

CVE tanpa produk layak (CNA maupun ADP) = yang di gate `new_cve` sekarang jatuh ke ringkasan teks; di desain baru mereka TIDAK punya identitas dan perlu jalur sendiri.

## 3. Ukuran dan kebersihan katalog

- Pasangan (vendor, produk) **mentah**: 42710
- Identitas **ternormalisasi** (huruf kecil, tanda baca jadi spasi, sampah dibuang): **37988** (14633 vendor)
- Setelah **menggabung ejaan** (tanpa spasi, `Palo Alto` = `PaloAlto`): **37770** -> normalisasi saja menyisakan 218 duplikat yang bisa digabung otomatis
- Perkiraan **keluarga produk** (token versi di ujung dibuang; kasar): **36543** -- selisihnya dengan angka di atas adalah varian versi yang menggelembungkan katalog (mis. tiap versi Windows = satu produk)
- Entri produk sampah: **16352**

| Jenis sampah | Entri | Contoh |
|---|---|---|
| placeholder | 7029 | n/a; 워드프레스 결제 심플페이; 简数采集器; 评论小秘书; 微力同步 |
| multi-produk | 3940 | RAPIDS cuDF and cuML; User Activity Tracking and Log; Giveaways and Contests by RafflePress; MB Custom Post Types & Custom Taxonomies; Social Media Share Buttons & Social Sharing Icons |
| url-atau-repo | 3938 | hamza417/inure; chatwoot/chatwoot; parisneo/lollms-webui; shaunwei/realchar; mintplex-labs/anything-llm |
| terlalu-panjang | 1198 | Jetson AGX Orin series (including Jetson Orin NX series, Jetson Orin N; MWB HubSpot for WooCommerce – CRM, Abandoned Cart, Email Marketing, Ma; Content Control – The Ultimate Content Restriction Plugin! Restrict Co; ClickWhale – Link Manager, Link Shortener and Click Tracker for Affili; s2Member – Excellent for All Kinds of Memberships, Content Restriction |
| generik | 217 | Web Application; firmware; Server; platform; Mobile Application |
| angka-saja | 27 | 4769; 0752-8303-8000-0002; 777; 0852-1322; 0852-1328 |
| mirip-versi | 3 | 130.8005 |

**Ekor panjang** (identitas menurut jumlah CVE di jendela):

| Jumlah CVE | Identitas |
|---|---|
| 1 CVE | 23808 |
| 2-4 CVE | 8994 |
| 5-19 CVE | 4314 |
| >=20 CVE | 872 |

Kalau picker hanya menampilkan identitas dengan >= 5 CVE, ukuran katalog = 5186; sisanya ekor yang sebagian besar noise atau produk sekali-lewat.

**Keluarga dengan varian terbanyak** (kandidat digabung atau disembunyikan di picker):

| Vendor | Keluarga | Varian | CVE |
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

## 4. Duplikasi ejaan (kandidat merge), 25 teratas

Ejaan berbeda yang setelah dikompaksi jadi identitas yang sama (sisa SESUDAH normalisasi huruf/tanda baca):

| Kunci | CVE | Ejaan (jumlah) |
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

## 5. 40 identitas dengan CVE terbanyak

| Vendor | Produk | CVE | Pertama | Terakhir | Ejaan mentah |
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

## 6. 34 tech produksi terhadap katalog

`hit` = CVE yang vendor/produk/paket/CPE CNA-nya menyebut tech itu (kata utuh), sama dengan gate `new_cve`. **Vonis**: `bersih` = satu vendor DAN satu produk menguasai >= 80% hit; `satu vendor, banyak produk` = vendor jelas tapi produknya tersebar (kasus hierarki: satu tech harus dipetakan ke beberapa produk); `ambigu` = vendor pun tersebar (perlu keputusan manusia saat memetakan); `tidak ada` = tak ada hit (nama tech bukan nama yang dipakai CNA, atau memang tak ada CVE di jendela).

| Tech | Hit | Vonis | Vendor teratas | Produk teratas | Identitas teratas (CVE) |
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

Ringkas: bersih 10, satu vendor banyak produk 9, ambigu 10, tidak ada 5 dari 34.

## 7. Recall terhadap tracker

Per tech, hanya CVE yang terbit di jendela (`di luar` = baris tracker yang terbit sebelum jendela, tidak bisa dinilai). `hanya-tracker` = ditemukan keyword search tapi TIDAK oleh pencocokan identitas (salah-cocok lama, atau nama CNA beda); `hanya-katalog` = ditemukan identitas tapi TIDAK ada di tracker (kelewat keyword search 8 hari, atau terbit sebelum tech ditambahkan).

| Tech | Tracker | Di luar | Di jendela | Keduanya | Hanya tracker | Hanya katalog |
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

**Tracker yang juga ditemukan katalog: 65/66 (98.5%).**

Contoh untuk ditinjau manual (maks 8 per tech):

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

## 8. Batas pengukuran

- Pencocokan tech memakai data CNA saja (ADP hanya menyelamatkan CVE tanpa produk layak). NVD/CPE yang diperkaya belakangan TIDAK ikut dihitung.
- `hit` mengukur kecocokan NAMA, bukan kebenaran; vonis `bersih` berarti identitasnya konsisten, bukan bahwa itu produk yang dimaksud client. Tinjau manusia tetap wajib.
- Gate `new_cve` juga jatuh ke ringkasan teks bila produk kosong; spike ini tidak meniru fallback itu.
- CVE terbit sebelum jendela tidak dihitung; tahun ID di luar `--id-years` tidak dipindai.
- Duplikat hanya yang lolos normalisasi sederhana; kemiripan yang butuh pengetahuan (`PAN-OS` vs `Palo Alto`) tidak terdeteksi. 'Keluarga produk' adalah perkiraan kasar.
