# Jalan pintas operasional. Detail: README.md dan docs/CUTOVER_RUNBOOK.md.
.PHONY: help fresh-deploy fresh-status deploy backfill-published-at backfill-cve-mirror
.PHONY: promote-cve-mirror compare-promotion-shadow catalog-mapping check-orphaned-tickets

help:
	@echo "make fresh-deploy [ARGS='--skip-build --skip-nginx']  deploy dari nol di host ini (idempoten)"
	@echo "make fresh-deploy ARGS='--restore-from /path/cti-<UTC>.dump'  isi DB dari backup (hanya DB kosong)"
	@echo "make deploy [ARGS='--dry-run --skip-backup']      update stack yang SUDAH jalan (backup, build, migrasi, cek sehat, rollback otomatis)"
	@echo "make fresh-status                                     status container stack"
	@echo "make backfill-cve-mirror SOURCE=/data/cvelistV5 [ARGS='--apply']  isi mirror CVE + katalog tech dari clone/zip CVE List V5 (laporan saja tanpa --apply)"
	@echo "make promote-cve-mirror MODE=shadow|live [ARGS='--apply --entry fortigate']  promosi mirror -> techstack ke seluruh mirror (laporan saja tanpa --apply)"
	@echo "make compare-promotion-shadow SINCE=2026-09-01 [ARGS='--client acme']  bandingkan bayangan dengan cve_tracker (hanya baca)"
	@echo "make catalog-mapping CMD=export|import|suggest [ARGS='--file /work/mapping.json --apply']  pemetaan techstack->katalog sebagai berkas (import = laporan saja tanpa --apply)"
	@echo "make backfill-published-at [ARGS='--apply --client acme']  isi jam publish MITRE CVE lama (laporan saja tanpa --apply)"
	@echo "make check-orphaned-tickets [ARGS='--client acme']  daftar tiket CVE tanpa baris tracker (hanya baca)"

fresh-deploy:
	bash tools/ops/fresh_deploy.sh $(ARGS)

fresh-status:
	docker compose --env-file docker/stack.env --profile app ps

deploy:
	bash tools/ops/deploy.sh $(ARGS)

# Tool ops sekali jalan di container `worker` yang SUDAH ada di stack: image, `.env`, dan network ikut
# service itu (tidak perlu menebak `<project>_default` atau `$CTI_TAG`). `tools/` tidak ikut image, jadi
# di-mount read-only. `--no-deps`: tidak menyentuh postgres/redis/migrate; `-T`: jalan tanpa TTY (cron/CI).
# Tanpa ARGS = laporan saja; `ARGS=--apply` baru menulis. Playbook: docs/SCRAPER_MAINTENANCE.md 4.H.
backfill-published-at:
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" --entrypoint python worker \
	  /tools/ops/backfill_cve_published_at.py $(ARGS)

# Tiket CVE yang tidak punya baris tracker (sisa `purge-orphaned` lama). HANYA MEMBACA, tidak ada --apply.
check-orphaned-tickets:
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" --entrypoint python worker \
	  /tools/ops/check_orphaned_tickets.py $(ARGS)

# Isi awal mirror CVE + katalog tech (ROADMAP #19). SOURCE = clone cvelistV5 atau zip rilisnya di host;
# di-mount read-only ke /data. Tanpa ARGS = laporan saja (di-rollback); `ARGS=--apply` baru menulis.
# Aman bersamaan dengan cve.mirror_sync (kunci advisory yang sama). Playbook: docs/CVE_CATALOG_DESIGN.md 8.
backfill-cve-mirror:
	@test -n "$(SOURCE)" || { echo "SOURCE=<clone/zip cvelistV5> wajib diisi"; exit 2; }
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" -v "$(abspath $(SOURCE)):/data/cvelist:ro" --entrypoint python worker \
	  /tools/ops/backfill_cve_mirror.py --source /data/cvelist $(ARGS)

# Promosi mirror -> techstack (ROADMAP #19 irisan 4) terhadap SELURUH mirror: mengisi riwayat bayangan
# sebelum perbandingan, atau riwayat entri yang baru di-Monitor. Tanpa ARGS = laporan (di-rollback);
# `ARGS=--apply` baru menulis. MODE=shadow hanya menulis cve_promotion_shadow; MODE=live menulis
# cve_tracker (tanpa notifikasi). Playbook: docs/CVE_CATALOG_DESIGN.md 8.
promote-cve-mirror:
	@test -n "$(MODE)" || { echo "MODE=shadow|live wajib diisi"; exit 2; }
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" --entrypoint python worker \
	  /tools/ops/promote_cve_mirror.py --mode $(MODE) $(ARGS)

# Hanya baca. Prasyarat: bayangan terisi (promote-cve-mirror MODE=shadow ARGS=--apply).
compare-promotion-shadow:
	@test -n "$(SINCE)" || { echo "SINCE=YYYY-MM-DD wajib diisi"; exit 2; }
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" --entrypoint python worker \
	  /tools/ops/compare_promotion_shadow.py --since $(SINCE) $(ARGS)

# Pemetaan techstack -> katalog sebagai berkas (ROADMAP #19 irisan 7): export dari dev, import ke prod
# (kunci katalog stabil, bukan ID). MAPPING_DIR (default: direktori ini) di-mount ke /work, jadi berkas
# ditulis/dibaca sebagai /work/<nama>. import tanpa --apply = laporan (di-rollback).
# Contoh: make catalog-mapping CMD=export ARGS='--out /work/mapping.json'
#         make catalog-mapping CMD=import ARGS='--file /work/mapping.json --apply'
MAPPING_DIR ?= $(CURDIR)
catalog-mapping:
	@test -n "$(CMD)" || { echo "CMD=export|import|suggest wajib diisi"; exit 2; }
	docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \
	  -v "$(CURDIR)/tools:/tools:ro" -v "$(abspath $(MAPPING_DIR)):/work" --entrypoint python worker \
	  /tools/ops/catalog_mapping.py $(CMD) $(ARGS)

