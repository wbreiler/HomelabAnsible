.PHONY: install run run-main run-dev run-both run-tags check validate

export PATH := /opt/homebrew/bin:$(PATH)
PROFILE ?= main
REMOTE_ACCESS ?= false
MAC_ACCESS = -e '{"mac_dev_remote_access":$(REMOTE_ACCESS)}'
MAC_PROFILES = ["$(PROFILE)"]
ifeq ($(PROFILE),both)
MAC_PROFILES = ["main","dev"]
endif

install:
	ansible-galaxy collection install -r requirements.yml

run: run-$(PROFILE)

run-main:
	ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["main"]}'

run-dev:
	ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["dev"]}' $(MAC_ACCESS)

run-both:
	ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":["main","dev"]}' $(MAC_ACCESS)

run-tags:
	ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":$(MAC_PROFILES)}' $(MAC_ACCESS) --tags "$(TAGS)"

check:
	ansible-playbook main.yml --ask-become-pass -e '{"mac_profiles":$(MAC_PROFILES)}' $(MAC_ACCESS) --check --diff

validate:
	ansible-playbook main.yml --syntax-check
	ansible-playbook -i 'dev_host,' dev-vm.yml --syntax-check
	ansible-lint main.yml dev-vm.yml
	ansible-playbook tests/roles.yml
