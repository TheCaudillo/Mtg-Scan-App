SHELL := /bin/bash
SYSTEM_PY ?= python3
VENV := $(CURDIR)/.venv
PY := $(VENV)/bin/python
SCANNER := services/scanner
WEB := apps/web
API_HOST ?= 127.0.0.1
API_PORT ?= 8000

.PHONY: help setup setup-ml env sync sync-quick sync-es prices index index-quick api web dev dev-lan test test-web build scan fixtures clean

help:
	@echo "make setup        install Python + web deps"
	@echo "make setup-ml     install OpenCLIP + FAISS (local art index, Mode A)"
	@echo "make sync         full Scryfall default_cards mirror (~110k printings, ~20s)"
	@echo "make sync-es      also ingest Spanish printings (all_cards, ~400MB download)"
	@echo "make prices       fast daily price refresh"
	@echo "make index        build the full OpenCLIP/FAISS art index (resumable, ~30-60 min CPU)"
	@echo "make index-quick  art index for printings since 2023 (~10 min)"
	@echo "make dev          run API (:8000) + web (:3000)"
	@echo "make dev-lan      same, reachable from your phone on the LAN"
	@echo "make scan IMG=photo.jpg   CLI smoke test on one photo"
	@echo "make test         backend tests;  make build  web production build"

env:
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

$(PY):
	@$(SYSTEM_PY) -m venv $(VENV) || (echo; echo "Could not create a virtualenv. On Ubuntu/Debian run:  sudo apt install python3-venv python3-pip"; exit 1)
	$(PY) -m pip install --upgrade pip

setup: env $(PY)
	@command -v npm >/dev/null || (echo; echo "npm not found: install Node.js 20+ (see README)"; exit 1)
	$(PY) -m pip install -r $(SCANNER)/requirements.txt
	cd $(WEB) && npm install
	@command -v tesseract >/dev/null || echo "TIP: install tesseract for free local collector-number OCR (brew install tesseract / apt install tesseract-ocr)"

setup-ml: $(PY)
	$(PY) -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu || $(PY) -m pip install torch torchvision
	$(PY) -m pip install -r $(SCANNER)/requirements-ml.txt

sync: env
	$(PY) scripts/sync_scryfall.py sync

sync-quick: env
	$(PY) scripts/sync_scryfall.py sync --recent-sets 24

sync-es: env
	$(PY) scripts/sync_scryfall.py sync --source all_cards --langs en,es

prices:
	$(PY) scripts/sync_scryfall.py prices

index:
	$(PY) scripts/build_art_index.py

index-quick:
	$(PY) scripts/build_art_index.py --since 2023-01-01

api:
	cd $(SCANNER) && $(PY) -m uvicorn scanner.api.main:app --host $(API_HOST) --port $(API_PORT) --reload --reload-dir scanner

web:
	cd $(WEB) && npm run dev

dev:
	@trap 'kill 0' EXIT; \
	(cd $(SCANNER) && $(PY) -m uvicorn scanner.api.main:app --host $(API_HOST) --port $(API_PORT)) & \
	(cd $(WEB) && npm run dev) & \
	wait

dev-lan:
	@trap 'kill 0' EXIT; \
	(cd $(SCANNER) && $(PY) -m uvicorn scanner.api.main:app --host 0.0.0.0 --port $(API_PORT)) & \
	(cd $(WEB) && npm run dev -- -H 0.0.0.0) & \
	wait

scan:
	@test -n "$(IMG)" || (echo "usage: make scan IMG=path/to/photo.jpg" && exit 1)
	$(PY) scripts/test_scan.py "$(IMG)" --debug "$(basename $(IMG))_annotated.jpg"

fixtures:
	$(PY) scripts/make_synthetic_binder.py

test:
	cd $(SCANNER) && $(PY) -m pytest -q

build:
	cd $(WEB) && npm run lint && npm run build

clean:
	rm -rf $(WEB)/.next $(SCANNER)/.pytest_cache
