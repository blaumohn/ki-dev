# Einrichtung von ki-dev. Voraussetzungen: python3 (>= 3.12), git, go, C-Compiler.
#
# Verfügbare Ziele:
#   make setup          venv, ki-dev und bd anlegen
#   make setup-agents   geprüfte Codex- und Claude-CLI nach .venv/bin (braucht npm)
#   make setup-runtime  eigenes Betriebs-venv und ~/.local/bin/ki-dev
#   make demo           Mock-Lauf ohne Anbieterzugang
#   make test           Tests und Lint
#   make spec-test      Anforderungstests mit Ergebnismatrix (dürfen rot sein)
#   make readme-check   README-Befehle im Wegwerf-Container, setzt Statuszeilen (braucht Docker)
#   make readme-live    README-Beispiel mit echten Agenten (verbraucht Tokens; codex und claude angemeldet)
#   make clean          Temporäre Dateien und venv entfernen

.DEFAULT_GOAL := help

version     = $(shell sed -n 's/.*"$(1)": "\(.*\)".*/\1/p' src/ki_dev/tool-versions.json)
BIN        := $(CURDIR)/.venv/bin
CHECK      := docker compose -f compose.readme-check.yaml

.PHONY: help
help:
	@echo "ki-dev Makefile - Verfügbare Ziele:"
	@echo ""
	@echo "  make setup          Erstelle venv, ki-dev und bd"
	@echo "  make setup-agents   Geprüfte Codex- und Claude-CLI nach .venv/bin (braucht npm)"
	@echo "  make setup-runtime  Betriebs-venv und ~/.local/bin/ki-dev einrichten"
	@echo "  make demo           Starten Sie einen Mock-Lauf ohne Anbieterzugang"
	@echo "  make test           Führen Sie Tests und Lint aus"
	@echo "  make spec-test      Anforderungstests mit Ergebnismatrix (dürfen rot sein)"
	@echo "  make readme-check   README-Befehle im Wegwerf-Container, setzt Statuszeilen (braucht Docker)"
	@echo "  make readme-live    README-Beispiel mit echten Agenten (verbraucht Tokens; codex und claude angemeldet)"
	@echo "  make clean          Entfernen Sie venv und temporäre Dateien"
	@echo ""
	@echo "Beispiele:"
	@echo "  make setup          # Initialisierung durchführen"
	@echo "  make test           # Tests ausführen"

.PHONY: setup setup-agents setup-runtime demo test spec-test readme-check readme-live clean

setup: .venv/bin/ki-dev setup-bd

# Explizites Update nur ohne aktive oder pausierte ki-dev-Läufe.
setup-runtime:
	bash scripts/setup-runtime.sh

.venv/bin/ki-dev:
	python3 -m venv .venv
	$(BIN)/pip install -e '.[test]'

# Vorhandenen Stand bei jedem Aufruf prüfen, unabhängig von Dateizeitstempeln.
.PHONY: setup-bd
setup-bd: .venv/bin/ki-dev
	@"$(BIN)/python" scripts/setup_beads.py

# Agenten-CLIs in den Versionen aus tool-versions.json; ki-dev ruft
# keine anderen auf. Globale Installationen bleiben unverändert.
setup-agents: .venv/bin/ki-dev
	@bash scripts/setup-agents.sh \
	  $(call version,CODEX_VERSION) $(call version,CLAUDE_VERSION)

demo: setup
	PATH="$(BIN):$$PATH" scripts/demo-mock-lauf.sh

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
# Danach setzt der Renderer (Host-venv) Statuszeile und Ausgabe jedes
# README-Blocks aus den Ergebnissen genau dieses Laufs, auch bei rotem
# Test oder gescheitertem Imagebau (dann überall „nicht ausgeführt“).
# Exit: der von Build oder Container, wenn ≠ 0, sonst der des Renderers.
readme-check: .venv/bin/ki-dev
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
	mkdir "$$READMECHECK_TMP_DIR/readme-ergebnisse"; \
	check=0; $(CHECK) build check || check=$$?; \
	if [ "$$check" -eq 0 ]; then $(CHECK) run --rm check || check=$$?; fi; \
	render=0; $(BIN)/python scripts/render-readme.py \
		--write "$$READMECHECK_TMP_DIR/readme-ergebnisse" || render=$$?; \
	if [ "$$check" -ne 0 ]; then exit "$$check"; fi; \
	exit "$$render"

# Das README-Beispiel einmal mit echten Agenten, auf diesem Rechner:
# ruft Modelle auf und verbraucht Tokens. Ergebnis und Ereignisprotokoll
# landen eingecheckt in docs/beispiele/echtlauf/; render-readme.py setzt
# daraus die Statuszeile „Mit echten Agenten ausgeführt“. Variablen einer
# umgebenden Claude-Code-Sitzung gehen nicht an das claude des Laufs.
readme-live: export README_LIVE := 1
readme-live: export README_RESULTS_DIR := $(CURDIR)/docs/beispiele/echtlauf
readme-live: .venv/bin/ki-dev setup-agents
	@set -eu; \
	unset KI_DEV_FLOW_PATH; \
	for name in $$(env | sed -nE 's/^(CLAUDECODE|CLAUDE_CODE_[A-Z_]*|CLAUDE_EFFORT|CLAUDE_PID)=.*/\1/p'); do \
	  unset "$$name"; \
	done; \
	export PATH="$(BIN):$$PATH"; \
	bash -c 'source tests/readme/lib.sh; \
	  run_readme_test tests/readme/test_9_ergebnis.sh'; \
	$(BIN)/python scripts/render-readme.py

clean:
	rm -rf .venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
