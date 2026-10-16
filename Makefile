# Einrichtung von ki-dev. Voraussetzungen: python3 (>= 3.12), git, go, C-Compiler.
#
# Verfügbare Ziele:
#   make setup          venv, ki-dev und bd anlegen
#   make setup-runtime  eigenes Betriebs-venv und ~/.local/bin/ki-dev
#   make demo           Mock-Lauf ohne Anbieterzugang
#   make test           Tests und Lint
#   make spec-test      Anforderungstests mit Ergebnismatrix (dürfen rot sein)
#   make readme-check   README-Einrichtung im Wegwerf-Container (braucht Docker)
#   make clean          Temporäre Dateien und venv entfernen

.DEFAULT_GOAL := help

version     = $(shell sed -n 's/.*"$(1)": "\(.*\)".*/\1/p' src/ki_dev/tool-versions.json)
BD_VERSION := $(call version,BD_VERSION)
BIN        := $(CURDIR)/.venv/bin
CHECK      := docker compose -f compose.readme-check.yaml

.PHONY: help
help:
	@echo "ki-dev Makefile - Verfügbare Ziele:"
	@echo ""
	@echo "  make setup          Erstelle venv, ki-dev und bd"
	@echo "  make setup-runtime  Betriebs-venv und ~/.local/bin/ki-dev einrichten"
	@echo "  make demo           Starten Sie einen Mock-Lauf ohne Anbieterzugang"
	@echo "  make test           Führen Sie Tests und Lint aus"
	@echo "  make spec-test      Anforderungstests mit Ergebnismatrix (dürfen rot sein)"
	@echo "  make readme-check   README-Einrichtung im Wegwerf-Container (braucht Docker)"
	@echo "  make clean          Entfernen Sie venv und temporäre Dateien"
	@echo ""
	@echo "Beispiele:"
	@echo "  make setup          # Initialisierung durchführen"
	@echo "  make test           # Tests ausführen"

.PHONY: setup setup-runtime demo test spec-test readme-check clean

setup: .venv/bin/ki-dev .venv/bin/bd

# Explizites Update nur ohne aktive oder pausierte ki-dev-Läufe.
setup-runtime:
	bash scripts/setup-runtime.sh

.venv/bin/ki-dev:
	python3 -m venv .venv
	$(BIN)/pip install -e '.[test]'

# bd landet im venv, damit nichts im Home oder im PATH verändert wird.
.venv/bin/bd: .venv/bin/ki-dev
	GOBIN=$(BIN) CGO_ENABLED=1 go install -tags gms_pure_go \
		github.com/steveyegge/beads/cmd/bd@v$(BD_VERSION)

demo: setup
	PATH=$(BIN):$$PATH scripts/demo-mock-lauf.sh

test: setup
	PATH=$(BIN):$$PATH $(BIN)/pytest -q
	$(BIN)/ruff check .

# Soll-/Istprüfung über die öffentliche CLI; rote Anforderungen sind ein
# zulässiges Ergebnis und deshalb weder Teil von test noch readme-check.
# Bericht: .local/var/spec-test/report.md und report.json.
spec-test: setup
	PATH=$(BIN):$$PATH $(BIN)/pytest -q --spec

# Baut das Prüfimage und startet einen neuen Wegwerf-Container (--rm).
# Arbeitsdateien pro Lauf auf Platte; Download-/Build-Caches bleiben erhalten.
readme-check: export READMECHECK_USER := $(shell id -u):$(shell id -g)
readme-check: export READMECHECK_CACHE_DIR := $(CURDIR)/.local/cache/readme-check
# Schlanke Variante des Python-Images aus tool-versions.json (eine Quelle).
readme-check: export PYTHON_IMAGE := $(subst -bookworm,-slim-bookworm,$(call version,PYTHON_IMAGE))
readme-check: export GO_VERSION      := $(call version,GO_VERSION)
readme-check: export GO_SHA256_AMD64 := $(call version,GO_SHA256_AMD64)
readme-check: export GO_SHA256_ARM64 := $(call version,GO_SHA256_ARM64)
readme-check:
	@set -eu; \
	mkdir -p .local/var/readme-check "$$READMECHECK_CACHE_DIR"; \
	READMECHECK_TMP_DIR=$$(mktemp -d "$(CURDIR)/.local/var/readme-check/run-XXXXXX"); \
	export READMECHECK_TMP_DIR; \
	trap 'rm -rf -- "$$READMECHECK_TMP_DIR"' EXIT; \
	$(CHECK) build check; \
	$(CHECK) run --rm check

clean:
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
