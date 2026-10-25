"""Peta frasa perilaku -> teknik ATT&CK untuk tier 1 (deterministik, tanpa LLM).

Format frasa: REGEX FRAGMENT (bukan teks polos). Pencocok membungkus tiap frasa
dengan `\\b(?:...)\\b` dan memakai IGNORECASE, jadi spasi di frasa ditulis `\\s+`
bila perlu dan tanda hubung opsional ditulis `[- ]?`. Satu konvensi di seluruh
berkas supaya tidak ada frasa yang ditafsirkan beda.

Prinsip: frasa harus menyatakan PERILAKU ("dumped credentials"), bukan kata
taktik telanjang ("execution"). Presisi diukur terhadap LLM nanti, jadi frasa
yang berisik lebih buruk daripada frasa yang hilang. `requires` dipakai saat
frasa utama ambigu (mis. "encrypted files" hanya berarti T1486 bila ada
"ransomware" di teks yang sama).

`KEYWORD_MAP_VERSION` = sha256[:8] dari repr aturan; ikut dicatat supaya hasil
lama bisa dihitung ulang bila peta berubah.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_MAX_SENTENCE = 300
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|\n\s*\n")


@dataclass(frozen=True)
class KeywordRule:
    ttp_id: str
    ttp_name: str
    phrases: tuple[str, ...]
    requires: tuple[str, ...] = ()


# Konteks pelaku/aksi untuk aturan yang frasanya ambigu (bisa muncul di deskripsi
# kerentanan, nasihat, atau berita pasar). Dipakai lewat `requires`.
_ACTOR = (
    r"attackers?",
    r"threat\s+actors?",
    r"hackers?",
    r"operators",
    r"campaigns?",
    r"gained\s+access",
    r"leveraged",
    r"\bused\b",
)


def _r(ttp_id: str, name: str, *phrases: str, requires: tuple[str, ...] = ()) -> KeywordRule:
    return KeywordRule(ttp_id, name, phrases, requires)


KEYWORD_MAP: tuple[KeywordRule, ...] = (
    _r(
        "T1190",
        "Exploit Public-Facing Application",
        r"exploit(?:ed|s|ing)?\s+(?:a|the)\s+(?:\w+\s+)?vulnerabilit(?:y|ies)\s+in",
        r"exploit(?:ed|s|ing)?\b[^.!?\n]{0,40}(?:public|internet)[- ]facing",
    ),
    _r(
        "T1566",
        "Phishing",
        r"phishing\s+(?:campaign|emails?|messages?|lures?)",
        r"phishing\s+attacks?",
    ),
    _r(
        "T1566.001",
        "Spearphishing Attachment",
        r"spear[- ]?phishing\s+attachments?",
        r"malicious\s+(?:email\s+)?attachments?",
    ),
    _r(
        "T1566.001",
        "Spearphishing Attachment",
        r"weaponi[sz]ed\s+(?:office\s+)?documents?",
        requires=_ACTOR,
    ),
    _r(
        "T1566.002",
        "Spearphishing Link",
        r"phishing\s+links?",
        r"(?<!clicking )(?<!click )(?<!opening )(?<!open )malicious\s+links?",
        r"spear[- ]?phishing\s+links?",
    ),
    _r(
        "T1598.003",
        "Spearphishing Link (Reconnaissance)",
        r"credential[- ]harvesting\s+(?:page|site|link)s?",
        r"fake\s+login\s+pages?",
    ),
    _r(
        "T1068",
        "Exploitation for Privilege Escalation",
        r"escalat(?:e|ed|es|ing)\s+privileges?\s+(?:via|using|through|by\s+exploiting)",
    ),
    _r(
        "T1041",
        "Exfiltration Over C2 Channel",
        r"exfiltrat(?:e|ed|es|ing)\s+(?:\w+\s+){0,3}(?:over|via|through)\s+(?:the\s+)?"
        r"(?:c2|c&c|command[- ]and[- ]control)",
    ),
    _r(
        "T1195",
        "Supply Chain Compromise",
        r"supply[- ]chain\s+(?:attack|compromise)s?",
    ),
    _r(
        "T1195.001",
        "Compromise Software Dependencies and Development Tools",
        r"malicious\s+(?:npm|pypi|python|rubygems?|nuget|maven)\s+packages?",
        r"(?:npm|pypi)\s+(?:package\s+)?(?:typosquatting|supply[- ]chain)",
        r"poisoned\s+(?:open[- ]source\s+)?(?:libraries|dependencies)",
    ),
    _r(
        "T1195.002",
        "Compromise Software Supply Chain",
        r"trojani[sz]ed\s+(?:software\s+)?(?:update|installer)s?",
        r"compromised\s+software\s+update",
        r"backdoored\s+(?:software\s+)?(?:update|installer|build)s?",
    ),
    _r(
        "T1548",
        "Abuse Elevation Control Mechanism",
        r"bypass(?:ed|es|ing)?\s+user\s+account\s+control",
        r"\buac\s+bypass",
    ),
    _r(
        "T1548.004",
        "Elevated Execution with Prompt",
        r"abus(?:e|ed|es|ing)\s+(?:the\s+)?authorization\s+services",
    ),
    _r(
        "T1005",
        "Data from Local System",
        r"(?:stole|steal(?:s|ing)?|harvest(?:ed|s|ing)?|collect(?:ed|s|ing)?)\s+(?:\w+\s+){0,2}"
        r"(?:files|documents|data)\s+from\s+(?:the\s+)?(?:infected|compromised|victim)"
        r"\s+(?:machine|host|system|device)s?",
    ),
    _r(
        "T1203",
        "Exploitation for Client Execution",
        r"exploit(?:ed|s|ing)?\s+(?:a\s+)?(?:vulnerabilit(?:y|ies)\s+in\s+)?(?:the\s+)?"
        r"(?:web\s+)?(?:browser|office|word|excel|pdf\s+reader|acrobat)",
        r"malicious\s+(?:office|word|excel|pdf)\s+documents?\s+(?:exploit|trigger)",
    ),
    _r(
        "T1036",
        "Masquerading",
        r"masquerad(?:e|ed|es|ing)\s+as",
        r"disguis(?:e|ed|es|ing)\s+(?:itself\s+)?as\s+(?:a\s+)?legitimate",
    ),
    _r(
        "T1036.005",
        "Match Legitimate Name or Location",
        r"mimic(?:s|ked|king)?\s+(?:the\s+)?(?:name|names)\s+of\s+(?:a\s+)?legitimate",
        r"legitimate[- ]looking\s+(?:file\s+)?names?",
    ),
    _r(
        "T1486",
        "Data Encrypted for Impact",
        r"encrypt(?:ed|s|ing)?\s+(?:\w+\s+)?(?:files|data|systems|servers|hosts)",
        r"files?\s+(?:were|was|are|is)\s+encrypted",
        requires=(r"ransomware", r"ransom\s+note"),
    ),
    _r(
        "T1027",
        "Obfuscated Files or Information",
        r"obfuscat(?:ed|es|ing|ion)\s+(?:\w+\s+)?(?:payload|script|code|malware|strings|loader)s?",
        r"(?:packed|encrypted)\s+payloads?",
        r"heavily\s+obfuscated",
    ),
    _r(
        "T1059",
        "Command and Scripting Interpreter",
        r"command[- ]line\s+interpreter",
        r"malicious\s+(?:shell\s+)?scripts?",
        requires=_ACTOR,
    ),
    _r(
        "T1059.003",
        "Windows Command Shell",
        r"cmd\.exe",
        r"windows\s+command\s+shell",
    ),
    _r(
        "T1059.004",
        "Unix Shell",
        r"(?:bash|unix\s+shell)\s+(?:script|command)s?",
        r"reverse\s+shell",
    ),
    _r(
        "T1059.005",
        "Visual Basic",
        r"(?:vba|visual\s+basic)\s+macros?",
        r"\bvbscript\b",
    ),
    _r(
        "T1555",
        "Credentials from Password Stores",
        r"password\s+(?:manager|vault)s?\s+(?:data|databases?|credentials)",
        r"steal(?:s|ing)?\s+(?:stored\s+)?passwords?\s+from",
    ),
    _r(
        "T1555.003",
        "Credentials from Web Browsers",
        r"(?:steal(?:s|ing)?|harvest(?:s|ed|ing)?|extract(?:s|ed|ing)?)\s+(?:\w+\s+)?"
        r"(?:credentials|passwords)\s+(?:stored\s+)?(?:from|in)\s+(?:web\s+)?browsers?",
        r"browser[- ]stored\s+(?:credentials|passwords)",
        r"saved\s+(?:browser\s+)?passwords?\s+in\s+(?:chrome|firefox|edge)",
    ),
    _r(
        "T1003",
        "OS Credential Dumping",
        r"credential\s+dumping",
        r"dump(?:ed|s|ing)?\s+credentials",
        r"\blsass\b",
        r"\bmimikatz\b",
    ),
    _r(
        "T1105",
        "Ingress Tool Transfer",
        r"download(?:ed|s|ing)?\s+(?:additional|second[- ]stage|further)\s+"
        r"(?:payloads?|malware|tools?|components?)",
        r"ingress\s+tool\s+transfer",
    ),
    _r(
        "T1570",
        "Lateral Tool Transfer",
        r"lateral\s+tool\s+transfer",
        r"cop(?:y|ied|ies|ying)\s+(?:\w+\s+)?(?:tools?|payloads?|malware)\s+to\s+(?:other|remote)"
        r"\s+(?:hosts|systems|machines)",
    ),
    _r(
        "T1210",
        "Exploitation of Remote Services",
        r"exploit(?:ed|s|ing)?\s+(?:\w+\s+)?(?:smb|rdp|remote\s+services?)\s+vulnerabilit(?:y|ies)",
        r"exploit(?:ed|s|ing)?\s+(?:a\s+)?remote\s+services?\s+to\s+move\s+laterally",
        r"\beternalblue\b",
    ),
    _r(
        "T1563",
        "Remote Service Session Hijacking",
        r"(?:rdp|ssh|remote\s+desktop)\s+session\s+hijack(?:ing)?",
        r"hijack(?:ed|s|ing)?\s+(?:an?\s+)?(?:rdp|ssh|remote\s+desktop)\s+sessions?",
    ),
    _r(
        "T1213",
        "Data from Information Repositories",
        r"(?:sharepoint|confluence|wiki)\s+(?:data|pages|documents)\s+(?:was|were)?\s*"
        r"(?:accessed|stolen|exfiltrated)",
        r"(?:stole|steal(?:s|ing)?|exfiltrat(?:e|ed|es|ing))\s+(?:\w+\s+)?"
        r"(?:from|data\s+from)\s+(?:the\s+)?(?:sharepoint|confluence|source\s+code\s+repositor(?:y|ies))",
    ),
    _r(
        "T1552",
        "Unsecured Credentials",
        r"hard[- ]?coded\s+(?:credentials|passwords|secrets)",
        r"credentials\s+stored\s+in\s+(?:plain\s*text|cleartext)",
    ),
    _r(
        "T1552.001",
        "Credentials In Files",
        r"credentials\s+(?:found\s+)?in\s+(?:configuration|config|\.env)\s+files?",
        r"searched?\s+(?:for\s+)?(?:files|file\s+systems?)\s+for\s+(?:passwords|credentials)",
    ),
    _r(
        "T1552.007",
        "Container API",
        r"exposed\s+(?:docker|kubernetes|kubelet)\s+api",
        r"(?:docker|kubernetes)\s+api\s+(?:was\s+)?exposed",
    ),
    _r(
        "T1505.003",
        "Web Shell",
        r"web[- ]?shells?",
    ),
    _r(
        "T1589",
        "Gather Victim Identity Information",
        r"gather(?:ed|s|ing)?\s+(?:\w+\s+)?(?:victim|employee)\s+(?:identity|email|credential)"
        r"\s+(?:information|addresses|data)",
        r"harvest(?:ed|s|ing)?\s+(?:employee\s+)?email\s+addresses",
    ),
    _r(
        "T1556",
        "Modify Authentication Process",
        r"modif(?:y|ied|ies|ying)\s+(?:the\s+)?authentication\s+(?:process|mechanism|module)",
        r"malicious\s+(?:pam|authentication)\s+(?:module|library)",
        r"(?:authentication|password)\s+filter\s+dll",
    ),
    _r(
        "T1204.002",
        "Malicious File",
        r"(?:tricked|trick(?:s|ing)?|lur(?:e|ed|es|ing))\s+(?:\w+\s+){0,3}(?:into|to)\s+"
        r"(?:open(?:ing)?|run(?:ning)?|execut(?:e|ing))\s+(?:a\s+|the\s+)?"
        r"(?:malicious\s+)?(?:file|attachment|document|executable)",
        r"user\s+(?:must|needs\s+to)\s+(?:open|run)\s+(?:the\s+)?malicious\s+file",
    ),
    _r(
        "T1082",
        "System Information Discovery",
        r"system\s+information\s+discovery",
        r"collect(?:s|ed|ing)?\s+(?:the\s+)?(?:system|host)\s+information\s+(?:such\s+as|including)",
        r"gather(?:s|ed|ing)?\s+(?:the\s+)?(?:os|operating\s+system)\s+version",
    ),
    _r(
        "T1583.006",
        "Web Services (Acquire Infrastructure)",
        r"(?:abus(?:e|ed|es|ing)|us(?:e|ed|es|ing))\s+(?:legitimate\s+)?(?:cloud|web)\s+services\s+"
        r"(?:to\s+host|for\s+hosting)",
        r"(?:github|pastebin|google\s+drive|dropbox)\s+(?:to\s+host|for\s+hosting)\s+"
        r"(?:payloads?|malware)",
    ),
    _r(
        "T1189",
        "Drive-by Compromise",
        r"drive[- ]by\s+(?:download|compromise|attack)s?",
        r"watering[- ]hole\s+(?:attack|campaign|site)s?",
        r"compromised\s+websites?\s+(?:to\s+)?(?:serve|deliver|host)",
    ),
    _r(
        "T1071.001",
        "Web Protocols",
        r"c2\s+(?:traffic\s+)?over\s+https?",
        r"command[- ]and[- ]control\s+(?:traffic\s+)?over\s+https?",
        r"beacon(?:s|ed|ing)?\s+(?:to\s+\S+\s+)?over\s+https?",
    ),
    _r(
        "T1530",
        "Data from Cloud Storage",
        r"(?:misconfigured|publicly\s+accessible|exposed|open)\s+(?:s3|azure\s+blob|cloud\s+storage)"
        r"\s*(?:buckets?|containers?|storage)?",
        r"s3\s+buckets?\s+(?:was|were)?\s*(?:exposed|accessed|misconfigured)",
    ),
    _r(
        "T1539",
        "Steal Web Session Cookie",
        r"(?:steal(?:s|ing)?|stole|harvest(?:s|ed|ing)?)\s+(?:\w+\s+)?"
        r"(?:session|authentication)\s+cookies?",
        r"session\s+cookie\s+theft",
        r"cookie\s+(?:stealing|hijacking)",
    ),
    _r(
        "T1133",
        "External Remote Services",
        r"(?:exposed|internet[- ]facing)\s+(?:vpn|rdp|remote\s+desktop)",
        r"(?:vpn|rdp|citrix)\s+access\s+(?:to|into)\s+(?:the\s+)?(?:victim|network|environment)",
        r"remote\s+desktop\s+protocol\s+exposed",
        requires=_ACTOR,
    ),
    _r(
        "T1020",
        "Automated Exfiltration",
        r"automated\s+exfiltration",
        r"automatically\s+exfiltrat(?:e|ed|es|ing)",
    ),
    _r(
        "T1090",
        "Proxy",
        r"(?:use(?:d|s)?|using)\s+(?:a\s+)?(?:proxy|socks5?)\s+(?:server\s+)?to\s+"
        r"(?:hide|relay|route|tunnel)",
        r"residential\s+proxy\s+(?:network|botnet)",
    ),
    _r(
        "T1528",
        "Steal Application Access Token",
        r"(?:steal(?:s|ing)?|stole|abus(?:e|ed|es|ing))\s+(?:\w+\s+)?(?:oauth|access|api)\s+tokens?",
        r"oauth\s+token\s+theft",
        r"malicious\s+oauth\s+app(?:lication)?s?",
    ),
    _r(
        "T1083",
        "File and Directory Discovery",
        r"(?:enumerat(?:e|ed|es|ing)|list(?:s|ed|ing)?|search(?:es|ed|ing)?)\s+(?:for\s+)?"
        r"(?:files\s+and\s+directories|directories\s+and\s+files|file\s+system)",
        r"file\s+and\s+directory\s+discovery",
    ),
    _r(
        "T1055",
        "Process Injection",
        r"process\s+(?:injection|hollowing)",
        r"inject(?:s|ed|ing)?\s+(?:\w+\s+){0,2}(?:code|payload|shellcode|dll)\s+into\s+"
        r"(?:a\s+|the\s+)?(?:legitimate\s+)?process",
    ),
    _r(
        "T1199",
        "Trusted Relationship",
        r"trusted\s+(?:third[- ]party|relationship|vendor)\s+(?:access|compromise|relationship)",
        r"compromis(?:e|ed|es|ing)\s+(?:a\s+)?(?:managed\s+service\s+provider|msp)",
        r"abus(?:e|ed|es|ing)\s+(?:a\s+)?trusted\s+relationship",
    ),
    _r(
        "T1565.001",
        "Stored Data Manipulation",
        r"(?:manipulat(?:e|ed|es|ing)|tamper(?:ed|s|ing)?\s+with|alter(?:ed|s|ing)?)\s+"
        r"(?:\w+\s+)?(?:stored|database)\s+(?:data|records)",
    ),
    _r(
        "T1588",
        "Obtain Capabilities",
        r"(?:purchas(?:e|ed|es|ing)|bought|acquir(?:e|ed|es|ing))\s+(?:\w+\s+)?"
        r"(?:malware|exploits?|tools)\s+(?:from|on)\s+(?:an?\s+)?(?:underground|dark\s*web|criminal)",
        r"malware[- ]as[- ]a[- ]service",
        requires=_ACTOR,
    ),
    _r(
        "T1557",
        "Adversary-in-the-Middle",
        r"adversary[- ]in[- ]the[- ]middle",
        r"man[- ]in[- ]the[- ]middle\s+(?:attack|proxy|phishing)s?",
        r"\baitm\b",
    ),
    _r(
        "T1491.001",
        "Internal Defacement",
        r"deface(?:d|s|ment)?\s+(?:\w+\s+)?(?:internal|corporate|company)\s+(?:web\s*sites?|pages?)",
        r"ransom\s+note\s+(?:was\s+)?(?:set|used)\s+as\s+(?:the\s+)?(?:desktop\s+)?wallpaper",
    ),
    _r(
        "T1098",
        "Account Manipulation",
        r"(?:added|add(?:s|ing)?|creat(?:e|ed|es|ing))\s+(?:a\s+)?(?:new\s+)?"
        r"(?:rogue\s+|backdoor\s+)?(?:administrator|admin)\s+accounts?",
        r"added\s+(?:\w+\s+)?to\s+(?:the\s+)?(?:domain\s+admins|administrators)\s+group",
        r"(?:added|registered)\s+(?:a\s+)?(?:new\s+)?(?:mfa|authenticator)\s+device",
    ),
    _r(
        "T1657",
        "Financial Theft",
        r"business\s+email\s+compromise",
        r"\bbec\s+(?:attack|scam|fraud)s?",
        r"fraudulent\s+(?:wire\s+)?transfers?",
        r"(?:stole|steal(?:s|ing)?)\s+(?:\w+\s+)?(?:cryptocurrency|crypto\s+assets)",
    ),
    _r(
        "T1496",
        "Resource Hijacking",
        r"crypto[- ]?(?:miner|mining|jacking)s?",
        r"coin[- ]?miners?",
        r"\bxmrig\b",
    ),
    _r(
        "T1684",
        "Social Engineering",
        r"social\s+engineering\s+(?:attacks?|campaigns?|tactics?)\s+(?:to|that)",
        requires=_ACTOR,
    ),
    _r(
        "T1684.001",
        "Impersonation",
        r"impersonat(?:e|ed|es|ing)\s+(?:\w+\s+){0,3}"
        r"(?:it|help\s?desk|support|executives?|ceo|cfo|employees?)\b",
        requires=_ACTOR,
    ),
    _r(
        "T1685",
        "Disable or Modify Tools",
        r"disabl(?:e|ed|es|ing)\s+(?:the\s+)?(?:edr|antivirus|anti-virus|security\s+tools?|defender)",
        r"kill(?:ed|s|ing)?\s+(?:the\s+)?(?:edr|av)\b",
        requires=_ACTOR,
    ),
    _r(
        "T1663",
        "Remote Access Software (Mobile)",
        r"malicious\s+(?:android|ios)\s+(?:app|application)s?\s+(?:with|using)\s+remote\s+access",
    ),
)

KEYWORD_MAP_VERSION: str = hashlib.sha256(repr(KEYWORD_MAP).encode()).hexdigest()[:8]


def sentence_at(text: str, offset: int) -> str:
    """Kalimat di sekitar `offset`, maks 300 karakter, spasi diringkas.

    Batas kalimat = tanda akhir (`.!?` + spasi) atau baris kosong; sengaja
    sederhana, cukup buat bukti yang bisa dibaca manusia. Kalimat yang lebih
    panjang dari batas dipotong di sekitar offset supaya frasa pemicu tetap ada.
    """
    offset = max(0, min(offset, len(text)))
    start = 0
    for m in _SENTENCE_END.finditer(text, 0, offset):
        start = m.end()
    end_match = _SENTENCE_END.search(text, offset)
    end = end_match.end() if end_match else len(text)
    sentence = " ".join(text[start:end].split())
    if len(sentence) <= _MAX_SENTENCE:
        return sentence
    # Potong di sekitar offset, dalam koordinat teks asli lalu ringkas spasi.
    lo = max(start, offset - _MAX_SENTENCE // 2)
    hi = min(end, lo + _MAX_SENTENCE)
    return " ".join(text[lo:hi].split())[:_MAX_SENTENCE]
