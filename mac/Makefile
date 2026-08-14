.PHONY: install run run-tags check

export PATH := /opt/homebrew/bin:$(PATH)

install:
	ansible-galaxy collection install -r requirements.yml

run:
	ansible-playbook main.yml --ask-become-pass

run-tags:
	ansible-playbook main.yml --ask-become-pass --tags "$(TAGS)"

check:
	ansible-playbook main.yml --ask-become-pass --check

# Examples:
#   make run-tags TAGS=homebrew
#   make run-tags TAGS=defaults,dock
