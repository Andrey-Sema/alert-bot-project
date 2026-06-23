.PHONY: up down restart logs check test integration stress lint format help

# =========================================================================
# Infrastructure Management (Docker CLI V2 Standard)
# =========================================================================

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f

# =========================================================================
# Code Quality & Validation Matrix
# =========================================================================

lint:
	ruff check .
	mypy alert_bot_project/
	bandit -c pyproject.toml -r alert_bot_project/

format:
	ruff format .

# =========================================================================
# Testing Suite Engine
# =========================================================================

test:
	pytest --cov=alert_bot_project --cov-report=term-missing --cov-report=html tests/

integration:
	pytest tests/test_integration_pipeline.py

stress:
	python -m alert_bot_project.scripts.stress_test

# =========================================================================
# Aggregated Quality Gates
# =========================================================================

check: format lint test integration
	@echo "💯 All quality gates passed smoothly! Project is ready for production push."

help:
	@echo "🔧 OdesaAlert Bot DevOps Control Panel Commands:"
	@echo "  up          - Build and start all services in background"
	@echo "  down        - Stop and remove all active containers"
	@echo "  restart     - Restart all operational core nodes"
	@echo "  logs        - Follow live logging stream from infrastructure"
	@echo "  format      - Auto-format code layout using Ruff"
	@echo "  lint        - Run security audits, imports, and type checking"
	@echo "  test        - Run complete suite of internal unit tests"
	@echo "  integration - Run E2E pipeline integration scenario"
	@echo "  stress      - Inject high-velocity load benchmark into Redis"
	@echo "  check       - Run full pipeline audit (format -> lint -> test)"