"""PostgreSQL setup for the product runtime's versioned record store."""

from __future__ import annotations

from psycopg_pool import ConnectionPool


class ProductPostgresStore:
    """Owns the product record pool and applies its idempotent base schema."""

    def __init__(self, database_url: str, *, max_size: int = 10) -> None:
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=max_size,
            open=False,
            kwargs={"application_name": "weaves-product-api"},
        )
        self.pool.open(wait=True)
        try:
            self._migrate()
        except Exception:
            self.pool.close()
            raise

    def _migrate(self) -> None:
        with self.pool.connection() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS product_schema_migrations (
                    version integer PRIMARY KEY,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS product_records (
                    collection text NOT NULL,
                    record_id text NOT NULL,
                    org_id text,
                    workspace_id text,
                    payload jsonb NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (collection, record_id)
                )"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS product_records_org_scope_idx
                   ON product_records (collection, org_id, record_id)"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS product_records_workspace_scope_idx
                   ON product_records (collection, org_id, workspace_id, record_id)"""
            )
            connection.execute(
                "INSERT INTO product_schema_migrations (version) VALUES (1) ON CONFLICT DO NOTHING"
            )

    def close(self) -> None:
        self.pool.close()

    def check(self) -> None:
        """Fail if the configured database cannot serve a simple query."""
        with self.pool.connection() as connection:
            connection.execute("SELECT 1").fetchone()
