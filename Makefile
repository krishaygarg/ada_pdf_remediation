.DEFAULT_GOAL := help
PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
SAMPLE ?= samples/physics/physics.pdf
OUT    ?= tmp/remediated.pdf

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

.PHONY: install
install: $(BIN)/python ## Create a virtualenv and install the project with dev extras
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]" build
	@echo "Install Poppler and Tesseract for the OCR path:"
	@echo "  macOS:  brew install poppler tesseract"
	@echo "  Debian: sudo apt-get install poppler-utils tesseract-ocr"

.PHONY: hooks
hooks: install ## Install the pre-commit hooks
	$(BIN)/pre-commit install

.PHONY: format
format: ## Apply formatting and safe lint fixes
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

.PHONY: lint
lint: ## Check formatting and lint without modifying files
	$(BIN)/ruff format --check --diff .
	$(BIN)/ruff check .

.PHONY: types
types: ## Run the type checker
	$(BIN)/mypy

.PHONY: test
test: ## Run the test suite
	$(BIN)/pytest

.PHONY: test-fast
test-fast: ## Run the test suite without the slow document tests
	$(BIN)/pytest -m "not slow"

.PHONY: cov
cov: ## Run the tests with a coverage report
	$(BIN)/pytest --cov=remediator --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

.PHONY: check
check: lint types test ## Everything CI runs

.PHONY: demo
demo: ## Remediate the bundled sample and audit the result
	@mkdir -p $(dir $(OUT))
	$(BIN)/remediate-pdf $(SAMPLE) $(OUT)
	$(BIN)/check-compliance $(OUT)

.PHONY: build
build: ## Build the sdist and wheel
	$(BIN)/python -m build

.PHONY: serve
serve: ## Run the web interface locally
	$(BIN)/python app.py

.PHONY: clean
clean: ## Remove build output, caches and scratch files
	rm -rf build dist htmlcov .coverage coverage.xml junit.xml
	rm -rf .pytest_cache .ruff_cache .mypy_cache .hypothesis
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
