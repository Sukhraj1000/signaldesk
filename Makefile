.PHONY: install lint typecheck test check format fix tox services-up services-down

install:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

lint:
	tox -e lint

typecheck:
	tox -e typecheck

test:
	tox -e py

check:
	tox

format:
	tox -e format

fix:
	tox -e fix

tox:
	tox

services-up:
	docker compose up -d

services-down:
	docker compose down
