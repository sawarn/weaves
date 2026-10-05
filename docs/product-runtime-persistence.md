# Product Runtime Persistence

## Status

The product runtime can use PostgreSQL for durable contract records. The
standalone runtime keeps its in-memory implementation so local scripts do not
need a database. Docker Compose starts the product API after its PostgreSQL
health check.

## Design

- `Repository[T]` remains the boundary used by the product runtime.
- `InMemoryRepository` is used when `DATABASE_URL` is empty.
- `PostgresRepository` stores versioned contract JSON in `product_records` and
  validates every read through the contract's strict JSON parser.
- Records are keyed by collection and the contract's declared ID field. Org
  and workspace IDs are indexed columns, and scoped reads apply those columns
  in SQL.
- The database connection pool belongs to the runtime and is closed with it.
- Startup applies an idempotent schema migration and seeds only missing demo
  records. Existing agent/model/connection configuration survives restarts.

The generic record table is an initial persistence adapter for the current v0
contracts. If a collection needs relational constraints, high volume queries,
or database-enforced tenant isolation, it can move behind the same repository
port to a dedicated table without changing the agent runtime or API contract.

## Local use

`docker compose up --build` runs the product API at port 8001 and the legacy POC
at port 8000. The product API uses `postgresql://...@postgres:5432/weaves` in
Compose. Its database volume is named `weaves-postgres`.

For memory-only mode, leave `DATABASE_URL` unset. The health endpoint reports
the selected storage mode and checks PostgreSQL readiness when PostgreSQL is
configured.

## Current boundaries

- The demo organization and local developer identity are still fixed.
- Authentication and request-derived tenant scope are not implemented yet.
- Product runs are synchronous; a run's individual repository writes are not
  currently wrapped in one cross-record transaction.
- This adapter is suitable for local v0 evaluation, not customer data or a
  production multi-tenant deployment.

The next platform work is to add a real identity/session boundary, then connect
one read-only organization system through the existing plugin gateway. The
connector choice remains an explicit product decision.
