PY := .venv/bin/python
UVICORN := .venv/bin/uvicorn

.PHONY: setup api shim web dev dev-cli test build serve

setup:            ## create venv + install backend and frontend deps
	test -d .venv || uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements-dev.txt
	cd frontend && npm install

api:              ## FastAPI backend on :8010 (reload on change)
	$(UVICORN) backend.app.main:app --reload --reload-dir backend/app --port 8010

shim:             ## Claude Code CLI wrapped as a Messages API on :8788
	$(UVICORN) shim.claude_cli_api:app --port 8788

web:              ## Vite dev server on :5173 (proxies /api to :8010)
	cd frontend && npm run dev

dev:              ## backend + frontend, using the Anthropic API
	./scripts/dev.sh

dev-cli:          ## backend + frontend + shim, using the claude CLI instead of an API key
	LLM_BACKEND=claude-cli ./scripts/dev.sh --with-shim

test:
	$(PY) -m pytest backend/tests -q

build:
	cd frontend && npm run build

serve: build      ## single process: FastAPI serves the built frontend on :8010
	$(UVICORN) backend.app.main:app --port 8010
