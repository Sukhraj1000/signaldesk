PYTHON ?= python3

.PHONY: install lint typecheck test docs smoke check format fix tox agent-preflight merge-readiness heartbeat sandbox-worktree services-up services-down

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m tox -e lint

typecheck:
	$(PYTHON) -m tox -e typecheck

test:
	$(PYTHON) -m tox -e py

smoke:
	$(PYTHON) -m tox -e smoke

docs:
	$(PYTHON) -m tox -e docs

check:
	$(PYTHON) -m tox

format:
	$(PYTHON) -m tox -e format

fix:
	$(PYTHON) -m tox -e fix

tox:
	$(PYTHON) -m tox

agent-preflight:
	$(PYTHON) scripts/agent_preflight.py

merge-readiness:
	$(PYTHON) scripts/merge_readiness.py

heartbeat:
	$(PYTHON) scripts/agent_heartbeat.py

sandbox-worktree:
	@test -n "$(TASK)" || (echo "Usage: make sandbox-worktree TASK=<task-name>" && exit 1)
	@printf '%s' "$(TASK)" | grep -Eq '^[A-Za-z0-9._-]+$$' || (echo "TASK must match [A-Za-z0-9._-]+" && exit 1)
	mkdir -p ../signaldesk-worktrees
	git fetch origin
	git worktree add "../signaldesk-worktrees/$(TASK)" -b "feature/$(TASK)" origin/main
	@echo "Created ../signaldesk-worktrees/$(TASK)"

services-up:
	docker compose up -d

services-down:
	docker compose down
