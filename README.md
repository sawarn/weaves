# Weaves Platform Backend

Weaves is a modular agent platform that connects organization systems and
context to bounded agents and workflows. This repository contains the
platform API, contracts, runtime, model and plugin gateways, and PostgreSQL
storage adapter.

The dashboard is maintained separately in
[`sawarn/weaves-app`](https://github.com/sawarn/weaves-app).

## Run the backend

Requirements: Docker Compose.

```sh
cp .env.example .env
docker compose up --build
```

The API is at [http://localhost:8001](http://localhost:8001), its interactive
API explorer is at [http://localhost:8001/docs](http://localhost:8001/docs),
and readiness is reported at `/api/v0/health`. PostgreSQL data is kept in the
`weaves-postgres` Docker volume.

To run the frontend, follow the instructions in the frontend repository and
set `WEAVES_API_BASE=http://localhost:8001/api/v0`.

## Model provider

Without `MODEL_API_KEY`, runs use the deterministic local model. To enable the
OpenAI-compatible adapter, set `MODEL_API_KEY`; `MODEL_BASE_URL` defaults to
`https://api.openai.com/v1` and `MODEL_NAME` defaults to `gpt-4o-mini`. Keep
provider credentials in the backend environment and never commit them.

## Development

Install dependencies with:

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
```

From `backend/`, use `pytest`, `ruff check .`, and `mypy` for the quality
harness. Product contracts and JSON schemas are under
`backend/weaves/product/contracts/v1` and `schemas/product/v1`.

## Current boundaries

The current runtime is for local v0 evaluation. It uses a demo organization
and developer identity, synchronous runs, and a mock context plugin. Sign-in,
customer connector installation, production tenant enforcement, and
background execution are planned platform work.
