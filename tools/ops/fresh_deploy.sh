#!/usr/bin/env bash
# Deploy CTI platform dari NOL di host baru (tanpa Mongo/stack lama). Idempoten: aman dijalankan ulang,
# tidak pernah menghapus volume atau data.
#
#   cp .env.prod.template .env              # isi semua nilai (jangan tempel secret ke chat/tiket)
#   cp docker/stack.env.example docker/stack.env   # ganti POSTGRES_PASSWORD, NGINX_TLS_HOSTS, port
#   make fresh-deploy                       # atau: bash tools/ops/fresh_deploy.sh
#
# Urutan (sama dengan docs/CUTOVER_RUNBOOK.md bagian 3, minus langkah yang butuh stack lama):
#   0 cek prasyarat  1 build image  2 cek secret (probe live, baca-doang)  3 postgres+redis+migrasi+api
#   4 seed data referensi bawaan  5 admin pertama (auth/init)  6 sinkron katalog ATT&CK
#   7 worker  8 beat TERAKHIR  9 web + nginx  -> ringkasan
# Dengan --restore-from, restore dijalankan di langkah 3, SESUDAH postgres+redis naik dan SEBELUM api
# (api menarik migrasi, jadi dump dari revisi lebih lama otomatis dinaikkan ke head).
#
# Opsi:  --skip-build  --skip-secret-check  --skip-nginx  -h|--help
#        --restore-from <dump>  isi database dari backup `pg_backup.py` (mis. dari staging) alih-alih DB kosong;
#                               hanya jalan di DB KOSONG, menolak (dan tidak menyentuh apa pun) kalau sudah berisi
#        --replace-db           (dengan --restore-from) TIMPA database yang sudah berisi -- DESTRUKTIF, minta konfirmasi
# Env:   ADMIN_USER (default "admin")  CTI_ENV_FILE (default .env)  CTI_STACK_ENV (default docker/stack.env)
#        COMPOSE_PROJECT_NAME (mis. untuk latihan di mesin yang sudah punya stack lain)
#
# Password admin dibuat acak dan ditulis ke secrets/admin_password (mode 600) -- TIDAK pernah dicetak.
# Ganti lewat UI setelah login pertama lalu hapus file itu.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

ENV_FILE="${CTI_ENV_FILE:-.env}"
STACK_ENV="${CTI_STACK_ENV:-docker/stack.env}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PW_FILE="secrets/admin_password"
SKIP_BUILD=0 SKIP_SECRET_CHECK=0 SKIP_NGINX=0 RESTORE_FROM="" REPLACE_DB=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-build) SKIP_BUILD=1 ;;
    --skip-secret-check) SKIP_SECRET_CHECK=1 ;;
    --skip-nginx) SKIP_NGINX=1 ;;
    --replace-db) REPLACE_DB=1 ;;
    --restore-from)
      [ $# -ge 2 ] || { echo "--restore-from butuh path berkas dump" >&2; exit 2; }
      RESTORE_FROM="$2"; shift ;;
    --restore-from=*) RESTORE_FROM="${1#*=}" ;;
    -h|--help) awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "opsi tidak dikenal: $1 (lihat --help)" >&2; exit 2 ;;
  esac
  shift
done
[ "$REPLACE_DB" -eq 0 ] || [ -n "$RESTORE_FROM" ] || { echo "--replace-db hanya bermakna bersama --restore-from" >&2; exit 2; }

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '  [PERINGATAN] %s\n' "$*" >&2; }
die() { printf '\n[GAGAL] %s\n' "$*" >&2; exit 1; }

export CTI_ENV_FILE="$ENV_FILE"
dc() { docker compose --env-file "$STACK_ENV" --profile app "$@"; }
stack_var() { # nilai variabel dari stack.env tanpa komentar inline; kosong kalau tidak ada
  { grep -E "^$1=" "$STACK_ENV" || true; } | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//'
}

# ------------------------------------------------------------------------------------------------
say "0/9 cek prasyarat"
command -v docker >/dev/null || die "docker tidak ditemukan"
docker compose version >/dev/null 2>&1 || die "plugin 'docker compose' tidak ditemukan"
docker info >/dev/null 2>&1 || die "daemon docker tidak jalan / user ini tidak boleh memakainya"
command -v python3 >/dev/null || die "python3 dibutuhkan (generator password, pengecekan env, pg_backup.py)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "python3 >= 3.9 dibutuhkan (ditemukan: $(python3 --version 2>&1))"

if [ ! -f "$ENV_FILE" ]; then
  cp .env.prod.template "$ENV_FILE"; chmod 600 "$ENV_FILE"
  die "$ENV_FILE belum ada -- saya salinkan dari .env.prod.template. Isi semua nilainya (terutama baris
       bertanda [ ] ROTASI), lalu jalankan ulang."
fi
if [ ! -f "$STACK_ENV" ]; then
  cp docker/stack.env.example "$STACK_ENV"
  die "$STACK_ENV belum ada -- saya salinkan dari docker/stack.env.example. Ganti POSTGRES_PASSWORD
       (harus sama dengan password di DATABASE__URL), NGINX_TLS_HOSTS, dan port bila perlu, lalu jalankan ulang."
fi
if grep -q 'GANTI_INI' "$ENV_FILE"; then
  grep -n 'GANTI_INI' "$ENV_FILE" | cut -d: -f1 | sed 's/^/  baris /' >&2
  die "$ENV_FILE masih berisi placeholder GANTI_INI (baris di atas)."
fi
[ "$(stack_var POSTGRES_PASSWORD)" != "cti" ] || die "POSTGRES_PASSWORD di $STACK_ENV masih default 'cti' -- ganti."

# Rahasia internal (bukan key provider) yang kosong di template: bangkitkan acak, jangan paksa user mengarang.
python3 - "$ENV_FILE" <<'PY'
import re, secrets, sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
made = []
for key in ("AUTH__JWT_SECRET", "AUTH__SESSION_SECRET_KEY"):
    pat = re.compile(rf"^{key}=[ \t]*(#.*)?$", re.M)
    if pat.search(text):
        text = pat.sub(f"{key}={secrets.token_urlsafe(48)}", text, count=1)
        made.append(key)
if made:
    open(path, "w", encoding="utf-8").write(text)
    print("  dibangkitkan acak (tadinya kosong): " + ", ".join(made))
PY

python3 - "$ENV_FILE" "$STACK_ENV" <<'PY' || die "password Postgres di $STACK_ENV tidak cocok dengan DATABASE__URL / DATABASE__SYNC_URL di $ENV_FILE."
import re, sys
from urllib.parse import unquote, urlsplit

def read(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line.rstrip("\n"))
        if m:
            out[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip()
    return out

app, stack = read(sys.argv[1]), read(sys.argv[2])
want = stack.get("POSTGRES_PASSWORD", "")
bad = [k for k in ("DATABASE__URL", "DATABASE__SYNC_URL")
       if unquote(urlsplit(app.get(k, "")).password or "") != want]
sys.exit(1 if bad or not want else 0)
PY
echo "  ok: docker, env aplikasi terisi, password Postgres konsisten"

if [ -n "$RESTORE_FROM" ]; then
  [ -f "$RESTORE_FROM" ] && [ -r "$RESTORE_FROM" ] || die "berkas dump tidak ditemukan/terbaca: $RESTORE_FROM"
  RESTORE_FROM="$(cd "$(dirname "$RESTORE_FROM")" && pwd)/$(basename "$RESTORE_FROM")"
  if [ -f "$RESTORE_FROM.sha256" ]; then
    echo "  ok: dump $(basename "$RESTORE_FROM") ($(du -h "$RESTORE_FROM" | cut -f1)); checksum akan dicek saat restore"
  else
    warn "tidak ada $(basename "$RESTORE_FROM").sha256 di sebelahnya -- integritas berkas tidak bisa dicek"
  fi
  if [ "$REPLACE_DB" -eq 1 ]; then
    warn "--replace-db: database yang ada SEKARANG akan DIHAPUS lalu diisi dari dump."
    if [ -t 0 ]; then
      read -r -p "  Ketik 'timpa' untuk melanjutkan: " ans
      [ "$ans" = "timpa" ] || die "dibatalkan."
    fi
  fi
fi

TAG="$(stack_var CTI_TAG)"; TAG="${TAG:-latest}"
API_PORT="$(stack_var API_PORT)"; API_PORT="${API_PORT:-8000}"

wait_ready() { # wait_ready <service> [detik]  -- healthy, atau running kalau service tanpa healthcheck
  local svc="$1" limit="${2:-240}" i=0 cid st
  while [ "$i" -lt "$limit" ]; do
    cid="$(dc ps -q "$svc" 2>/dev/null | head -1)"
    if [ -n "$cid" ]; then
      st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")"
      case "$st" in
        healthy|running) return 0 ;;
        exited|dead) break ;;
      esac
    fi
    sleep 3; i=$((i + 3))
  done
  warn "$svc tidak siap (status: ${st:-tidak ada}). 30 baris log terakhir:"
  dc logs --no-color --tail 30 "$svc" >&2 || true
  die "$svc gagal naik."
}

# ------------------------------------------------------------------------------------------------
if [ "$SKIP_BUILD" -eq 1 ]; then
  say "1/9 build dilewati (--skip-build)"
else
  say "1/9 build image (pertama kali bisa 10-20 menit)"
  dc build
fi

if [ "$SKIP_SECRET_CHECK" -eq 1 ]; then
  say "2/9 cek secret dilewati (--skip-secret-check)"
else
  say "2/9 cek secret: probe live baca-doang ke LLM/Telegram/NVD/GitHub/twitterapi.io/X"
  # `compose run` (bukan `docker run --env-file`): compose membuang komentar inline di .env, docker run tidak.
  dc run --rm --no-deps -T -v "$PWD/tools:/tools:ro" --entrypoint python worker \
    /tools/ops/check_secrets.py || die "check_secrets gagal -- betulkan key yang ditolak di $ENV_FILE
       (key opsional yang kosong tidak masalah; LLM dan Telegram wajib). Lanjutkan paksa: --skip-secret-check."
fi

say "3/9 postgres + redis$([ -z "$RESTORE_FROM" ] || echo ', restore database'), migrasi skema, api"
if [ "$REPLACE_DB" -eq 1 ]; then  # DROP DATABASE memutus koneksi: hentikan semua penulis dulu
  dc stop beat worker worker-browser worker-nlp worker-cve web nginx api >/dev/null 2>&1 || true
fi
dc up -d postgres redis
wait_ready postgres; wait_ready redis
PG_USER="$(stack_var POSTGRES_USER)"; PG_USER="${PG_USER:-cti}"
PG_DB="$(stack_var POSTGRES_DB)"; PG_DB="${PG_DB:-cti}"
if [ -n "$RESTORE_FROM" ]; then
  echo "  restore $(basename "$RESTORE_FROM") -> database '$PG_DB'"
  restore_args=(--file "$RESTORE_FROM" --to-db "$PG_DB" --force-live)
  [ "$REPLACE_DB" -eq 0 ] || restore_args+=(--replace)
  python3 tools/ops/pg_backup.py \
    --pg-exec "docker compose --env-file $STACK_ENV --profile app exec -T postgres" \
    --user "$PG_USER" --db "$PG_DB" restore "${restore_args[@]}" \
    || die "restore gagal -- database TIDAK diubah kalau pesannya 'sudah berisi' atau 'checksum'. Untuk host yang
       sudah berisi data: jalankan ulang TANPA --restore-from, atau (menghapus semua data) tambahkan --replace-db."
fi
dc up -d api || {      # menarik service `migrate` (one-shot, alembic upgrade head) lebih dulu
  warn "migrasi/api gagal naik. 20 baris log migrate:"
  dc logs --no-color --tail 20 migrate >&2 || true
  die "migrasi gagal. Kalau pesannya \"Can't locate revision\": database (mis. hasil --restore-from) berasal dari kode
       yang LEBIH BARU dari checkout ini -- pakai kode yang sama atau lebih baru dari yang membuat dump."
}
wait_ready api

say "4/9 seed data referensi bawaan (threat actor, demonym, allowlist IOC)"
dc run --rm --no-deps -T -v "$PWD/tools:/tools:ro" -v "$PWD/tools/seed/reference:/dump:ro" \
  --entrypoint sh worker -c '
    pip install --target /tmp/pm -q pymongo &&
    PYTHONPATH=/tmp/pm python /tools/seed/fase5_reference_data.py --dump-dir /dump' \
  || die "seed data referensi gagal (lihat pesan di atas)."

say "5/9 admin pertama ($ADMIN_USER) lewat POST /api/auth/init"
mkdir -p secrets && chmod 700 secrets
NEWPW="$ADMIN_PW_FILE.new"
( umask 077; python3 - > "$NEWPW" <<'PY'
import secrets, string
rng = secrets.SystemRandom()
pools = [string.ascii_uppercase, string.ascii_lowercase, string.digits, "-_.!@#%^*+="]
chars = [rng.choice(p) for p in pools] + [rng.choice("".join(pools)) for _ in range(24)]
rng.shuffle(chars)
print("".join(chars))
PY
)
set +e
python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "password": open(sys.argv[2]).read().strip()}))' \
  "$ADMIN_USER" "$NEWPW" \
| dc exec -T api python -c '
import json, sys, urllib.error, urllib.request
body = sys.stdin.buffer.read()
req = urllib.request.Request("http://127.0.0.1:8000/api/auth/init", data=body,
                             headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=30); sys.exit(0)
except urllib.error.HTTPError as e:
    raw = e.read().decode("utf-8", "replace")
    if e.code == 409: sys.exit(3)
    try:
        d = json.loads(raw).get("detail")
    except ValueError:
        d = None
    if isinstance(d, list):   # 422 pydantic: JANGAN cetak "input" (berisi password)
        d = "; ".join(str(x.get("loc")) + " " + str(x.get("msg")) for x in d if isinstance(x, dict))
    print("HTTP %s: %s" % (e.code, d if isinstance(d, str) else "(lihat log api)"), file=sys.stderr)
    sys.exit(1)
'
rc=$?
set -e
case "$rc" in
  0) mv "$NEWPW" "$ADMIN_PW_FILE"; echo "  admin '$ADMIN_USER' dibuat; password ada di $ADMIN_PW_FILE (mode 600)" ;;
  3) rm -f "$NEWPW"; echo "  sudah ada user di database$([ -z "$RESTORE_FROM" ] || echo ' (dari backup)') -- admin tidak dibuat ulang (file password lama, kalau ada, tidak disentuh)" ;;
  *) rm -f "$NEWPW"; die "pembuatan admin gagal (kode $rc)." ;;
esac

say "6/9 sinkron katalog ATT&CK (butuh akses keluar ke GitHub; tanpa ini TTP belum dinormalisasi)"
if ! dc exec -T api python - <<'PY'
import asyncio, json, sys
from cti_core.db.engine import async_session
from cti_core.db.repositories.attack import AsyncAttackSyncRepo

async def main() -> int:
    async with async_session() as s:
        repo = AsyncAttackSyncRepo(s)
        await repo.sync_all_domains()
        status = await repo.get_sync_status()
    for row in status:
        print("  ", json.dumps(row, default=str)[:160])
    return 1 if any(r.get("status") == "never" for r in status) else 0

sys.exit(asyncio.run(main()))
PY
then
  warn "sinkron ATT&CK belum lengkap (jaringan keluar ke GitHub diblokir?). Platform tetap naik; task
       periodik akan mencoba lagi, atau tekan tombol Sync di UI. Artikel yang masuk sebelum katalog terisi
       bisa punya TTP yang belum dinormalisasi."
fi

say "7/9 worker (ringan, browser, nlp, cve)"
dc up -d worker worker-browser worker-nlp worker-cve
wait_ready worker; wait_ready worker-browser; wait_ready worker-nlp 360; wait_ready worker-cve

say "8/9 beat -- penembak jadwal, SENGAJA terakhir"
dc up -d beat
wait_ready beat 60
sleep 5
beat_cid="$(dc ps -q beat | head -1)"  # hanya sejak start TERAKHIR: log lama (restart/rerun) tetap tersimpan
leaders="$(docker logs --since "$(docker inspect -f '{{.State.StartedAt}}' "$beat_cid")" "$beat_cid" 2>&1 | grep -c 'beat_leader' || true)"
[ "$leaders" -eq 1 ] || warn "baris beat_leader di log sejak start = $leaders (harus tepat 1). Periksa: docker compose logs beat"

say "9/9 web$([ "$SKIP_NGINX" -eq 1 ] || echo ' + nginx')"
dc up -d web
wait_ready web
if [ "$SKIP_NGINX" -eq 0 ]; then
  dc up -d nginx
  wait_ready nginx
fi

HTTPS_PORT="$(stack_var NGINX_HTTPS_PORT)"; HTTPS_PORT="${HTTPS_PORT:-443}"
HOSTS="$(stack_var NGINX_TLS_HOSTS)"
say "SELESAI"
dc ps --format 'table {{.Service}}\t{{.Status}}'
cat <<EOF

Buka   : https://${HOSTS%%,*}$([ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT")   (sertifikat self-signed: browser akan memperingatkan)
$(if [ -n "$RESTORE_FROM" ]; then
  echo "Login  : pakai user dari backup (password lama; TIDAK dibuat admin baru):"
  dc exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -tA -c "select '           ' || username || ' (' || role_name || ')' from users order by 1" || true
else
  echo "Login  : user '$ADMIN_USER', password di $ADMIN_PW_FILE  -> ganti lewat UI, lalu hapus file itu"
fi)
Health : curl -fs http://127.0.0.1:${API_PORT}/healthz

$([ -z "$RESTORE_FROM" ] || cat <<'WARN'
Backup membawa APA ADANYA: user + password lama, data uji (mis. TA whitelist), dan override scraper
(`scraper_config`: jadwal/max_items). Ganti password dan bersihkan data uji sebelum dipakai produksi.
Redis tidak ikut backup (isinya sementara); dedup scraper ada di Postgres, jadi tidak ada banjir "cold start".

WARN
)
Yang MASIH harus diisi manual lewat UI (tanpa ini beberapa scraper sengaja idle):
  - client + negara, user lain, techstack (tanpa ini new_cve kosong), akun X yang dipantau (tanpa ini monitor_x idle)
Dianjurkan sebelum dipakai: pasang timer backup Postgres (docs/PROD_PREP.md, docker/ops/cti-pg-backup.*).
Pada DB kosong, scraper pertama kali jalan dengan mode "cold start": maks 5 item per scraper. Detail: README.md dan docs/CUTOVER_RUNBOOK.md.
EOF
