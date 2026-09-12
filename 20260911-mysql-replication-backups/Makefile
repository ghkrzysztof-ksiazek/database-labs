.PHONY: bootstrap deploy load-data verify backup restore teardown test

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
