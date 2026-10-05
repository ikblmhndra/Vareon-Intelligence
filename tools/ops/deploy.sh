#!/usr/bin/env bash
# Update stack CTI yang SUDAH berjalan ke kode di checkout ini. Dipanggil CD (.github/workflows/deploy.yml)
# atau manual: `make deploy`. Beda dengan fresh_deploy.sh (host baru): ini TIDAK menyentuh seed, admin,
# maupun sinkron ATT&CK, dan tidak pernah menghapus volume/data.
#
# Urutan:
#   1 prasyarat  2 backup Postgres  3 tandai image yang SEDANG berjalan sebagai :prev (jangkar rollback)
#   4 build image  5 up -d (service `migrate` menaikkan skema lebih dulu)  6 tunggu API + semua container sehat
#   7 kalau 5/6 gagal -> rollback.py ke :prev (TANPA --yes: tidak pernah downgrade DB sendiri) + alarm Telegram
#
# Opsi:  --skip-backup (tidak dianjurkan)  --dry-run (cetak rencana, tidak mengubah apa pun)  -h|--help
# Env:   CTI_ENV_FILE (default .env)  CTI_STACK_ENV (default docker/stack.env)
#        CTI_BACKUP_DIR (default /var/backups/cti)  CTI_HEALTH_WAIT detik (default 300)
#
# Exit 0 = sukses. Exit 1 = gagal (stack sudah dikembalikan ke :prev kalau rollback otomatis bisa;
# kalau tidak bisa -- mis. butuh downgrade DB -- pesan alarm menyebut langkah manualnya).

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

ENV_FILE="${CTI_ENV_FILE:-.env}"
STACK_ENV="${CTI_STACK_ENV:-docker/stack.env}"
BACKUP_DIR="${CTI_BACKUP_DIR:-/var/backups/cti}"
HEALTH_WAIT="${CTI_HEALTH_WAIT:-300}"
SKIP_BACKUP=0 DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-backup) SKIP_BACKUP=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) awk 'NR > 1 && /^#/ { print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "opsi tidak dikenal: $1 (lihat --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n==> %s\n' "$*"; }
warn() { printf '  [PERINGATAN] %s\n' "$*" >&2; }
die() { printf '\n[GAGAL] %s\n' "$*" >&2; exit 1; }

export CTI_ENV_FILE="$ENV_FILE"
dc() { docker compose --env-file "$STACK_ENV" --profile app "$@"; }
stack_var() { # nilai variabel dari stack.env tanpa komentar inline; kosong kalau tidak ada
  { grep -E "^$1=" "$STACK_ENV" || true; } | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//'
}
notify() {
  python3 tools/ops/notify_telegram.py --env-file "$ENV_FILE" --topic debug --text "$1" >/dev/null 2>&1 \
    || warn "alarm Telegram gagal terkirim"
}

say "1/7 prasyarat"
command -v docker >/dev/null || die "docker tidak ditemukan"
command -v python3 >/dev/null || die "python3 dibutuhkan (pg_backup.py, rollback.py, notify_telegram.py)"
[ -f "$ENV_FILE" ] || die "$ENV_FILE tidak ada -- ini bukan host yang sudah di-deploy? (host baru: make fresh-deploy)"
[ -f "$STACK_ENV" ] || die "$STACK_ENV tidak ada"
dc config -q || die "docker-compose.yml / env tidak valid"

# Satu deploy dalam satu waktu (CD + manual tidak boleh bertabrakan).
if command -v flock >/dev/null; then
  exec 9>/tmp/cti-deploy.lock
  flock -n 9 || die "deploy lain sedang berjalan (/tmp/cti-deploy.lock)"
fi

TAG="$(stack_var CTI_TAG)"; TAG="${TAG:-latest}"
API_PORT="$(stack_var API_PORT)"; API_PORT="${API_PORT:-8000}"
API_URL="http://127.0.0.1:${API_PORT}/healthz"
SHA="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
PROJECT="$(dc config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
# service compose -> image (rollback butuh tag :prev di keempatnya)
SERVICE_IMAGES="api:cti-api worker:cti-worker worker-nlp:cti-worker-nlp web:cti-web"

if [ "$DRY_RUN" -eq 1 ]; then
  say "DRY RUN -- rencana (tidak ada yang diubah)"
  echo "  commit $SHA, tag $TAG, project $PROJECT, health $API_URL"
  echo "  backup -> $BACKUP_DIR$([ "$SKIP_BACKUP" -eq 0 ] || echo ' (DILEWATI)')"
  echo "  tandai :prev dari container yang berjalan: $SERVICE_IMAGES"
  echo "  dc build && dc up -d, tunggu sehat <= ${HEALTH_WAIT}s, gagal -> rollback.py ke :prev"
  exit 0
fi

rollback_or_alarm() {
  local why="$1"
  warn "$why -- mencoba rollback ke :prev"
  if python3 tools/ops/rollback.py --current-tag "$TAG" --tag prev \
       --compose "docker compose --env-file $STACK_ENV --profile app" \
       --env-file "$ENV_FILE" --network "${PROJECT}_default" --api-url "$API_URL" \
       --services "api worker worker-browser worker-nlp beat web"; then
    notify "DEPLOY GAGAL (commit $SHA): $why. Stack DIKEMBALIKAN ke versi sebelumnya (:prev). Cek log CD."
    die "$why -- stack dikembalikan ke :prev"
  fi
  notify "DEPLOY GAGAL (commit $SHA): $why. Rollback otomatis TIDAK bisa (mis. butuh downgrade DB). Stack mungkin setengah jalan -- tangani manual: docs/CUTOVER_RUNBOOK.md bagian 7."
  die "$why -- rollback otomatis gagal, TANGANI MANUAL (docs/CUTOVER_RUNBOOK.md bagian 7)"
}

healthy() {
  curl -fsS -m 3 "$API_URL" >/dev/null 2>&1 || return 1
  # migrate = one-shot (State exited), dikecualikan; sisanya harus running dan tidak unhealthy/starting
  local bad
  bad="$(dc ps -a --format '{{.Service}} {{.State}} {{.Health}}' \
        | awk '$1 != "migrate" && ($2 != "running" || $3 == "unhealthy" || $3 == "starting")')"
  [ -z "$bad" ]
}

if [ "$SKIP_BACKUP" -eq 1 ]; then
  say "2/7 backup dilewati (--skip-backup)"
else
  say "2/7 backup Postgres -> $BACKUP_DIR"
  python3 tools/ops/pg_backup.py \
    --pg-exec "docker compose --env-file $STACK_ENV --profile app exec -T postgres" \
    backup --dir "$BACKUP_DIR" --keep-days 14 --keep-min 3 \
    || die "backup gagal -- deploy DIBATALKAN, belum ada yang diubah"
fi

say "3/7 tandai image yang sedang berjalan sebagai :prev"
for pair in $SERVICE_IMAGES; do
  svc="${pair%%:*}"; img="${pair#*:}"
  cid="$(dc ps -q "$svc" 2>/dev/null | head -1 || true)"
  if [ -n "$cid" ]; then
    docker tag "$(docker inspect -f '{{.Image}}' "$cid")" "$img:prev"
    echo "  $img:prev <- container $svc"
  else
    # Tidak ada container berjalan (mis. deploy sebelumnya gagal): JANGAN menimpa :prev dengan
    # image yang belum tentu baik.
    warn "$svc tidak berjalan -- $img:prev dibiarkan apa adanya"
  fi
done

say "4/7 build image ($SHA)"
dc build || die "build gagal -- stack lama TIDAK disentuh"

say "5/7 up -d (migrate lebih dulu)"
dc up -d || rollback_or_alarm "up -d gagal (migrate/api tidak naik)"

say "6/7 tunggu API dan semua container sehat (maks ${HEALTH_WAIT}s)"
deadline=$((SECONDS + HEALTH_WAIT))
until healthy; do
  [ "$SECONDS" -lt "$deadline" ] || { dc ps -a >&2 || true; rollback_or_alarm "tidak sehat dalam ${HEALTH_WAIT}s"; }
  sleep 5
done

say "7/7 selesai"
docker image prune -f >/dev/null 2>&1 || true   # hanya image dangling; :prev tetap ada
dc ps --format 'table {{.Service}}\t{{.Status}}'
notify "DEPLOY OK: commit $SHA berjalan sehat."
