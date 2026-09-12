.PHONY: bootstrap deploy load-data verify backup restore teardown test test-backups report \
	test-t01 test-t02 test-t03 test-t04 test-t05 test-t06 test-t07 test-t08 test-t09 test-t10 test-t11 test-t12

RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%SZ)

VENV := .venv
ANSIBLE := $(VENV)/bin/ansible-playbook
GALAXY := $(VENV)/bin/ansible-galaxy
PYTHON := $(VENV)/bin/python

bootstrap:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -r requirements.txt
	$(GALAXY) collection install -r ansible/requirements.yml -p ansible/collections

test:
	$(PYTHON) -m unittest discover -s tests -v

deploy:
	cd ansible && ../$(ANSIBLE) playbooks/site.yml

load-data:
	cd ansible && ../$(ANSIBLE) playbooks/load-data.yml

verify:
	cd ansible && ../$(ANSIBLE) playbooks/verify.yml

backup:
	cd ansible && ../$(ANSIBLE) playbooks/backup.yml

restore:
	cd ansible && ../$(ANSIBLE) playbooks/restore.yml

teardown:
	cd ansible && ../$(ANSIBLE) playbooks/teardown.yml

test-backups:
	cd ansible && ../$(ANSIBLE) playbooks/tests/all.yml -e run_id=$(RUN_ID)

report:
	cd ansible && ../$(ANSIBLE) playbooks/tests/report.yml -e run_id=$(RUN_ID)

test-t01:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t01-backup-full.yml -e run_id=$(RUN_ID)

test-t02:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t02-backup-from-replica.yml -e run_id=$(RUN_ID)

test-t03:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t03-backup-incremental.yml -e run_id=$(RUN_ID)

test-t04:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t04-storage-contents.yml -e run_id=$(RUN_ID)

test-t05:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t05-backup-scheduled.yml -e run_id=$(RUN_ID)

test-t06:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t06-backup-retention.yml -e run_id=$(RUN_ID)

test-t07:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t07-restore-in-place.yml -e run_id=$(RUN_ID)

test-t08:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t08-restore-dropped-table.yml -e run_id=$(RUN_ID)

test-t09:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t09-pitr-timestamp.yml -e run_id=$(RUN_ID)

test-t10:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t10-pitr-gtid.yml -e run_id=$(RUN_ID)

test-t11:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t11-pitr-invalid-target.yml -e run_id=$(RUN_ID)

test-t12:
	cd ansible && ../$(ANSIBLE) playbooks/tests/t12-restore-as-replica.yml -e run_id=$(RUN_ID)
