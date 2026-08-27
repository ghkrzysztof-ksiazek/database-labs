.PHONY: bootstrap deploy load-data verify teardown test-alert configure-slack

VENV := .venv
ANSIBLE := $(VENV)/bin/ansible-playbook
GALAXY := $(VENV)/bin/ansible-galaxy

bootstrap:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -r requirements.txt
	$(GALAXY) collection install -r ansible/requirements.yml -p ansible/collections

deploy:
	cd ansible && ../$(ANSIBLE) playbooks/site.yml

load-data:
	cd ansible && ../$(ANSIBLE) playbooks/load-data.yml

verify:
	cd ansible && ../$(ANSIBLE) playbooks/verify.yml

teardown:
	cd ansible && ../$(ANSIBLE) playbooks/teardown.yml

test-alert:
	cd ansible && ../$(ANSIBLE) playbooks/test-alert.yml

configure-slack:
	cd ansible && ../$(ANSIBLE) playbooks/configure-slack.yml
