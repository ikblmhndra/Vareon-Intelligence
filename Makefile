# Jalan pintas operasional. Detail: README.md dan docs/CUTOVER_RUNBOOK.md.
.PHONY: help fresh-deploy fresh-status deploy backfill-published-at

help:
	@echo "make fresh-deploy [ARGS='--skip-build --skip-nginx']  deploy dari nol di host ini (idempoten)"
	@echo "make fresh-deploy ARGS='--restore-from /path/cti-<UTC>.dump'  isi DB dari backup (hanya DB kosong)"
	@echo "make deploy [ARGS='--dry-run --skip-backup']      update stack yang SUDAH jalan (backup, build, migrasi, cek sehat, rollback otomatis)"
	@echo "make fresh-status                                     status container stack"
	@echo "make backfill-published-at [ARGS='--apply --client acme']  isi jam publish MITRE CVE lama (laporan saja tanpa --apply)"

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
