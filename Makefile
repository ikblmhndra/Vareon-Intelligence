# Jalan pintas operasional. Detail: README.md dan docs/CUTOVER_RUNBOOK.md.
.PHONY: help fresh-deploy fresh-status deploy

help:
	@echo "make fresh-deploy [ARGS='--skip-build --skip-nginx']  deploy dari nol di host ini (idempoten)"
	@echo "make fresh-deploy ARGS='--restore-from /path/cti-<UTC>.dump'  isi DB dari backup (hanya DB kosong)"
	@echo "make deploy [ARGS='--dry-run --skip-backup']      update stack yang SUDAH jalan (backup, build, migrasi, cek sehat, rollback otomatis)"
	@echo "make fresh-status                                     status container stack"

fresh-deploy:
	bash tools/ops/fresh_deploy.sh $(ARGS)

fresh-status:
	docker compose --env-file docker/stack.env --profile app ps

deploy:
	bash tools/ops/deploy.sh $(ARGS)
