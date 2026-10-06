import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///.local/weaves.db")
IS_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith(
    "postgres://"
)


def as_id(value):
    return value if IS_POSTGRES else str(value)


def statement(sql: str) -> str:
    return (
        sql
        if IS_POSTGRES
        else sql.replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")
    )


def json_value(value):
    if IS_POSTGRES:
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    import json

    return json.dumps(value)


@contextmanager
def connect():
    if IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        db_path = DATABASE_URL.removeprefix("sqlite:///")
        path = Path(db_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    last_error = None
    for _ in range(30 if IS_POSTGRES else 1):
        try:
            with connect() as conn:
                schema_name = "schema.sql" if IS_POSTGRES else "schema.sqlite.sql"
                schema = Path(__file__).with_name(schema_name).read_text()
                if IS_POSTGRES:
                    conn.execute(schema)
                    conn.execute(
                        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS instructions TEXT NOT NULL DEFAULT 'Answer the user using the connected company handbook. Be clear, concise, and cite source files.'"
                    )
                    conn.execute(
                        "ALTER TABLE runs ADD COLUMN IF NOT EXISTS agent_instructions TEXT NOT NULL DEFAULT ''"
                    )
                else:
                    conn.executescript(schema)
                    agent_columns = {
                        row["name"] for row in conn.execute("PRAGMA table_info(agents)")
                    }
                    if "instructions" not in agent_columns:
                        conn.execute(
                            "ALTER TABLE agents ADD COLUMN instructions TEXT NOT NULL DEFAULT 'Answer the user using the connected company handbook. Be clear, concise, and cite source files.'"
                        )
                    run_columns = {
                        row["name"] for row in conn.execute("PRAGMA table_info(runs)")
                    }
                    if "agent_instructions" not in run_columns:
                        conn.execute(
                            "ALTER TABLE runs ADD COLUMN agent_instructions TEXT NOT NULL DEFAULT ''"
                        )
                conn.execute(
                    statement("""
                    INSERT INTO agents (id, org_id, workspace_id, name, description)
                    VALUES ('company-knowledge-assistant', 'demo-org', 'demo-workspace',
                            'Company Knowledge Assistant',
                            'Answers questions using the approved demo handbook.')
                    ON CONFLICT (id) DO NOTHING
                    """)
                )
            return
        except Exception as exc:
            if not IS_POSTGRES:
                raise
            last_error = exc
            time.sleep(1)
    raise RuntimeError("Could not connect to PostgreSQL") from last_error
