"""Repository ports and implementations for local and persistent runtimes."""

import json
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Generic, Iterable, Literal, Optional, Protocol, TypeVar

from weaves.product.contracts.v1.base import OpaqueId, ProductContract
from weaves.product.contracts.v1.executions import ExecutionJobStatus

TContract = TypeVar("TContract", bound=ProductContract)


class IdempotencyKeyAlreadyExists(ValueError):
    """A database uniqueness constraint rejected a duplicate run key."""


def _updated_at(record: ProductContract) -> datetime:
    value = getattr(record, "updated_at", None)
    if not isinstance(value, datetime):
        raise TypeError("conditional updates require a mutable record with updated_at")
    return value


class Repository(Protocol[TContract]):
    def create(self, record: TContract) -> TContract: ...

    def put(self, record: TContract) -> TContract: ...

    def get(self, record_id: OpaqueId) -> TContract: ...

    def get_scoped(
        self,
        record_id: OpaqueId,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId] = None,
    ) -> TContract: ...

    def delete(self, record_id: OpaqueId) -> None: ...

    def list(self) -> tuple[TContract, ...]: ...

    def list_due(
        self, due_before: datetime, *, limit: int
    ) -> tuple[TContract, ...]: ...

    def list_audit_page(
        self,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId],
        *,
        action: Optional[str],
        target_type: Optional[str],
        target_id: Optional[str],
        actor_principal_id: Optional[str],
        created_after: Optional[datetime],
        created_before: Optional[datetime],
        cursor_created_at: Optional[datetime],
        cursor_event_id: Optional[str],
        limit: int,
    ) -> tuple[TContract, ...]: ...

    def find_by_field(self, field: str, value: str) -> Optional[TContract]: ...

    def claim_next_queued(
        self,
        worker_id: str,
        timestamp: datetime,
        org_id: Optional[str],
        workspace_id: Optional[str],
    ) -> Optional[TContract]: ...

    def list_scoped(
        self, org_id: OpaqueId, workspace_id: Optional[OpaqueId] = None
    ) -> tuple[TContract, ...]: ...

    def find_by_idempotency_key(
        self,
        key: str,
        requested_by_principal_id: str,
        org_id: OpaqueId,
        workspace_id: OpaqueId,
    ) -> Optional[TContract]: ...

    def put_if_status_and_stale(
        self,
        record: TContract,
        *,
        expected_status: str,
        updated_before: datetime,
    ) -> bool: ...

    def put_if_execution_job_owned(
        self,
        record: TContract,
        *,
        worker_id: str,
        attempts: int,
        expected_status: str = "running",
    ) -> bool: ...

    def put_if_invitation_pending(
        self, record: TContract, *, expected_token_digest: str
    ) -> bool: ...


class InMemoryRepository(Generic[TContract]):
    """A local repository keyed by a contract's explicit identifier field."""

    def __init__(self, id_field: str) -> None:
        self._id_field = id_field
        self._records: dict[str, TContract] = {}
        self._lock = RLock()

    def create(self, record: TContract) -> TContract:
        record_id = self._record_id(record)
        with self._lock:
            if record_id in self._records:
                raise ValueError(f"{self._id_field} already exists: {record_id}")
            self._records[record_id] = self._clone(record)
        return self._clone(record)

    def put(self, record: TContract) -> TContract:
        record_id = self._record_id(record)
        with self._lock:
            self._records[record_id] = self._clone(record)
        return self._clone(record)

    def get(self, record_id: OpaqueId) -> TContract:
        with self._lock:
            try:
                return self._clone(self._records[record_id])
            except KeyError as exc:
                raise KeyError(f"{self._id_field} not found: {record_id}") from exc

    def get_scoped(
        self,
        record_id: OpaqueId,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId] = None,
    ) -> TContract:
        """Resolve an object only when its stored tenant scope matches."""
        record = self.get(record_id)
        if getattr(record, "org_id", None) != org_id:
            raise KeyError(f"{self._id_field} not found in organization scope")
        if (
            workspace_id is not None
            and getattr(record, "workspace_id", None) != workspace_id
        ):
            raise KeyError(f"{self._id_field} not found in workspace scope")
        return record

    def delete(self, record_id: OpaqueId) -> None:
        with self._lock:
            if record_id not in self._records:
                raise KeyError(f"{self._id_field} not found: {record_id}")
            del self._records[record_id]

    def list(self) -> tuple[TContract, ...]:
        with self._lock:
            return tuple(self._clone(record) for record in self._records.values())

    def list_due(self, due_before: datetime, *, limit: int) -> tuple[TContract, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            due = [
                record
                for record in self._records.values()
                if getattr(getattr(record, "status", None), "value", None) == "active"
                and isinstance(getattr(record, "next_run_at", None), datetime)
                and getattr(record, "next_run_at") <= due_before
            ]
            due.sort(
                key=lambda record: (
                    getattr(record, "next_run_at"),
                    self._record_id(record),
                )
            )
            return tuple(self._clone(record) for record in due[:limit])

    def list_audit_page(
        self,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId],
        *,
        action: Optional[str],
        target_type: Optional[str],
        target_id: Optional[str],
        actor_principal_id: Optional[str],
        created_after: Optional[datetime],
        created_before: Optional[datetime],
        cursor_created_at: Optional[datetime],
        cursor_event_id: Optional[str],
        limit: int,
    ) -> tuple[TContract, ...]:
        if self._id_field != "audit_event_id":
            raise TypeError("audit event paging requires an audit event repository")
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            records = tuple(self._records.values())
        filtered = (
            record
            for record in records
            if getattr(record, "org_id", None) == org_id
            and (
                workspace_id is None
                or getattr(record, "workspace_id", None) == workspace_id
            )
            and (action is None or getattr(record, "action", None) == action)
            and (
                target_type is None
                or getattr(record, "target_type", None) == target_type
            )
            and (target_id is None or getattr(record, "target_id", None) == target_id)
            and (
                actor_principal_id is None
                or getattr(record, "actor_principal_id", None) == actor_principal_id
            )
            and (
                created_after is None or getattr(record, "created_at") >= created_after
            )
            and (
                created_before is None
                or getattr(record, "created_at") <= created_before
            )
            and (
                cursor_created_at is None
                or (
                    getattr(record, "created_at"),
                    self._record_id(record),
                )
                < (cursor_created_at, cursor_event_id or "")
            )
        )
        ordered = sorted(
            filtered,
            key=lambda record: (getattr(record, "created_at"), self._record_id(record)),
            reverse=True,
        )
        return tuple(self._clone(record) for record in ordered[:limit])

    def find_by_field(self, field: str, value: str) -> Optional[TContract]:
        with self._lock:
            for record in self._records.values():
                if getattr(record, field, None) == value:
                    return self._clone(record)
        return None

    def claim_next_queued(
        self,
        worker_id: str,
        timestamp: datetime,
        org_id: Optional[str],
        workspace_id: Optional[str],
    ) -> Optional[TContract]:
        with self._lock:
            queued = [
                record
                for record in self._records.values()
                if (org_id is None or getattr(record, "org_id", None) == org_id)
                and (
                    workspace_id is None
                    or getattr(record, "workspace_id", None) == workspace_id
                )
                if getattr(getattr(record, "status", None), "value", None) == "queued"
            ]
            if not queued:
                return None
            current = min(queued, key=lambda item: getattr(item, "created_at"))
            claimed = type(current).model_validate(
                current.model_copy(
                    update={
                        "status": ExecutionJobStatus.RUNNING,
                        "attempts": int(getattr(current, "attempts", 0)) + 1,
                        "worker_id": worker_id,
                        "started_at": timestamp,
                        "updated_at": timestamp,
                    }
                ).model_dump()
            )
            self._records[self._record_id(current)] = self._clone(claimed)
            return self._clone(claimed)

    def list_scoped(
        self, org_id: OpaqueId, workspace_id: Optional[OpaqueId] = None
    ) -> tuple[TContract, ...]:
        """List only records matching the requested organization/workspace."""
        with self._lock:
            return tuple(
                self._clone(record)
                for record in self._records.values()
                if getattr(record, "org_id", None) == org_id
                and (
                    workspace_id is None
                    or getattr(record, "workspace_id", None) == workspace_id
                )
            )

    def find_by_idempotency_key(
        self,
        key: str,
        requested_by_principal_id: str,
        org_id: OpaqueId,
        workspace_id: OpaqueId,
    ) -> Optional[TContract]:
        with self._lock:
            for record in self._records.values():
                if (
                    getattr(record, "idempotency_key", None) == key
                    and getattr(record, "requested_by_principal_id", None)
                    == requested_by_principal_id
                    and getattr(record, "org_id", None) == org_id
                    and getattr(record, "workspace_id", None) == workspace_id
                ):
                    return self._clone(record)
        return None

    def put_if_status_and_stale(
        self,
        record: TContract,
        *,
        expected_status: str,
        updated_before: datetime,
    ) -> bool:
        record_id = self._record_id(record)
        with self._lock:
            current = self._records.get(record_id)
            current_status = getattr(current, "status", None)
            if getattr(current_status, "value", current_status) != expected_status:
                return False
            if getattr(current, "updated_at", updated_before) > updated_before:
                return False
            self._records[record_id] = self._clone(record)
        return True

    def put_if_execution_job_owned(
        self,
        record: TContract,
        *,
        worker_id: str,
        attempts: int,
        expected_status: str = "running",
    ) -> bool:
        """Update an execution job only for its current owner and state."""
        record_id = self._record_id(record)
        with self._lock:
            current = self._records.get(record_id)
            if (
                current is None
                or getattr(getattr(current, "status", None), "value", None)
                != expected_status
                or getattr(current, "worker_id", None) != worker_id
                or getattr(current, "attempts", None) != attempts
            ):
                return False
            self._records[record_id] = self._clone(record)
        return True

    def put_if_invitation_pending(
        self, record: TContract, *, expected_token_digest: str
    ) -> bool:
        """Atomically accept, rotate, or revoke a still-pending invitation."""
        record_id = self._record_id(record)
        with self._lock:
            current = self._records.get(record_id)
            if (
                current is None
                or getattr(getattr(current, "status", None), "value", None) != "pending"
                or getattr(current, "token_digest", None) != expected_token_digest
            ):
                return False
            self._records[record_id] = self._clone(record)
        return True

    def _record_id(self, record: TContract) -> str:
        try:
            return str(getattr(record, self._id_field))
        except AttributeError as exc:
            raise TypeError(f"record has no {self._id_field} field") from exc

    def _clone(self, record: TContract) -> TContract:
        """Round-trip through the contract serializer for a detached deep copy."""
        return type(record).model_validate_json(record.model_dump_json())


class InMemoryUnitOfWork:
    """Lock and snapshot a set of in-memory repositories as one local transaction."""

    def __init__(self, repositories: Iterable[InMemoryRepository[Any]]) -> None:
        self._repositories = tuple(
            sorted(
                {id(repository): repository for repository in repositories}.values(),
                key=id,
            )
        )
        self._snapshots: dict[int, Any] = {}

    def __enter__(self) -> "InMemoryUnitOfWork":
        acquired: list[InMemoryRepository[Any]] = []
        try:
            for repository in self._repositories:
                repository._lock.acquire()
                acquired.append(repository)
            self._snapshots = {
                id(repository): {
                    key: repository._clone(record)
                    for key, record in repository._records.items()
                }
                for repository in self._repositories
            }
        except Exception:
            for repository in reversed(acquired):
                repository._lock.release()
            raise
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Literal[False]:
        try:
            if exc_type is not None:
                for repository in self._repositories:
                    repository._records = self._snapshots[id(repository)]
        finally:
            for repository in reversed(self._repositories):
                repository._lock.release()
        return False


class PostgresRepository(Generic[TContract]):
    """JSONB-backed repository with tenant scope stored as queryable columns."""

    def __init__(
        self,
        pool: Any,
        collection: str,
        id_field: str,
        record_type: type[TContract],
    ) -> None:
        self._pool = pool
        self._collection = collection
        self._id_field = id_field
        self._record_type = record_type

    def create(self, record: TContract) -> TContract:
        from psycopg import errors
        from psycopg.types.json import Jsonb

        record_id = self._record_id(record)
        try:
            with self._pool.connection() as connection:
                connection.execute(
                    """INSERT INTO product_records
                       (collection, record_id, org_id, workspace_id,
                        idempotency_key, requested_by_principal_id, payload, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()))""",
                    (
                        self._collection,
                        record_id,
                        self._scope(record, "org_id"),
                        self._scope(record, "workspace_id"),
                        getattr(record, "idempotency_key", None),
                        getattr(record, "requested_by_principal_id", None),
                        Jsonb(record.model_dump(mode="json")),
                        getattr(record, "created_at", None),
                    ),
                )
        except errors.UniqueViolation as exc:
            if getattr(exc.diag, "constraint_name", None) in {
                "product_records_run_idempotency_uq",
                "product_records_execution_job_idempotency_uq",
            }:
                raise IdempotencyKeyAlreadyExists(
                    "workflow run idempotency key already exists"
                ) from exc
            raise ValueError(f"{self._id_field} already exists: {record_id}") from exc
        return self._clone(record)

    def put(self, record: TContract) -> TContract:
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            connection.execute(
                """INSERT INTO product_records
                   (collection, record_id, org_id, workspace_id,
                    idempotency_key, requested_by_principal_id, payload)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (collection, record_id) DO UPDATE SET
                     org_id = EXCLUDED.org_id,
                     workspace_id = EXCLUDED.workspace_id,
                     idempotency_key = EXCLUDED.idempotency_key,
                     requested_by_principal_id = EXCLUDED.requested_by_principal_id,
                     payload = EXCLUDED.payload,
                     updated_at = now()""",
                (
                    self._collection,
                    self._record_id(record),
                    self._scope(record, "org_id"),
                    self._scope(record, "workspace_id"),
                    getattr(record, "idempotency_key", None),
                    getattr(record, "requested_by_principal_id", None),
                    Jsonb(record.model_dump(mode="json")),
                ),
            )
        return self._clone(record)

    def get(self, record_id: OpaqueId) -> TContract:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM product_records WHERE collection = %s AND record_id = %s",
                (self._collection, str(record_id)),
            ).fetchone()
        if row is None:
            raise KeyError(f"{self._id_field} not found: {record_id}")
        return self._deserialize(row[0])

    def get_scoped(
        self,
        record_id: OpaqueId,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId] = None,
    ) -> TContract:
        query = """SELECT payload FROM product_records
                    WHERE collection = %s AND record_id = %s AND org_id = %s"""
        params: tuple[object, ...] = (self._collection, str(record_id), str(org_id))
        if workspace_id is not None:
            query += " AND workspace_id = %s"
            params += (str(workspace_id),)
        with self._pool.connection() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            raise KeyError(f"{self._id_field} not found in requested scope")
        return self._deserialize(row[0])

    def delete(self, record_id: OpaqueId) -> None:
        with self._pool.connection() as connection:
            result = connection.execute(
                "DELETE FROM product_records WHERE collection = %s AND record_id = %s",
                (self._collection, str(record_id)),
            )
            if result.rowcount == 0:
                raise KeyError(f"{self._id_field} not found: {record_id}")

    def list(self) -> tuple[TContract, ...]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM product_records WHERE collection = %s ORDER BY record_id",
                (self._collection,),
            ).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)

    def list_due(self, due_before: datetime, *, limit: int) -> tuple[TContract, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if due_before.tzinfo is None or due_before.utcoffset() is None:
            raise ValueError("due_before must include a timezone")
        cutoff = due_before.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._pool.connection() as connection:
            rows = connection.execute(
                """SELECT payload FROM product_records
                   WHERE collection = %s AND payload->>'status' = 'active'
                     AND payload->>'next_run_at' <= %s
                   ORDER BY payload->>'next_run_at', record_id
                   LIMIT %s""",
                (self._collection, cutoff, limit),
            ).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)

    def list_audit_page(
        self,
        org_id: OpaqueId,
        workspace_id: Optional[OpaqueId],
        *,
        action: Optional[str],
        target_type: Optional[str],
        target_id: Optional[str],
        actor_principal_id: Optional[str],
        created_after: Optional[datetime],
        created_before: Optional[datetime],
        cursor_created_at: Optional[datetime],
        cursor_event_id: Optional[str],
        limit: int,
    ) -> tuple[TContract, ...]:
        if self._collection != "audit_events":
            raise TypeError("audit event paging requires an audit event repository")
        if limit < 1:
            raise ValueError("limit must be positive")
        query = """SELECT payload FROM product_records
                   WHERE collection = %s AND org_id = %s"""
        params: tuple[object, ...] = (self._collection, str(org_id))
        if workspace_id is not None:
            query += " AND workspace_id = %s"
            params += (str(workspace_id),)
        for field, value in (
            ("action", action),
            ("target_type", target_type),
            ("target_id", target_id),
            ("actor_principal_id", actor_principal_id),
        ):
            if value is not None:
                query += f" AND payload->>'{field}' = %s"
                params += (value,)
        if created_after is not None:
            query += " AND created_at >= %s"
            params += (created_after,)
        if created_before is not None:
            query += " AND created_at <= %s"
            params += (created_before,)
        if cursor_created_at is not None:
            if cursor_event_id is None:
                raise ValueError("cursor event ID is required")
            query += " AND (created_at, record_id) < (%s, %s)"
            params += (cursor_created_at, cursor_event_id)
        query += " ORDER BY created_at DESC, record_id DESC LIMIT %s"
        params += (limit,)
        with self._pool.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)

    def find_by_field(self, field: str, value: str) -> Optional[TContract]:
        if not field.isascii() or not field.replace("_", "a").isalnum():
            raise ValueError("field must be a valid contract field name")
        with self._pool.connection() as connection:
            row = connection.execute(
                f"""SELECT payload FROM product_records
                    WHERE collection = %s AND payload ->> '{field}' = %s LIMIT 1""",
                (self._collection, value),
            ).fetchone()
        return self._deserialize(row[0]) if row is not None else None

    def claim_next_queued(
        self,
        worker_id: str,
        timestamp: datetime,
        org_id: Optional[str],
        workspace_id: Optional[str],
    ) -> Optional[TContract]:
        scope_filter = ""
        scope_params: tuple[object, ...] = ()
        if org_id is not None:
            scope_filter += " AND org_id = %s"
            scope_params += (org_id,)
        if workspace_id is not None:
            scope_filter += " AND workspace_id = %s"
            scope_params += (workspace_id,)
        with self._pool.connection() as connection:
            row = connection.execute(
                f"""WITH candidate AS (
                       SELECT record_id FROM product_records
                       WHERE collection = %s{scope_filter}
                         AND payload->>'status' = 'queued'
                       ORDER BY created_at, record_id
                       LIMIT 1 FOR UPDATE SKIP LOCKED
                   )
                   UPDATE product_records AS job
                   SET payload = job.payload || jsonb_build_object(
                           'status', 'running',
                           'attempts', COALESCE((job.payload->>'attempts')::integer, 0) + 1,
                           'worker_id', %s::text,
                           'started_at', to_jsonb(%s::timestamptz),
                           'updated_at', to_jsonb(%s::timestamptz)
                       ),
                       updated_at = %s
                   FROM candidate
                   WHERE job.collection = %s AND job.record_id = candidate.record_id
                   RETURNING job.payload""",
                (
                    self._collection,
                    *scope_params,
                    worker_id,
                    timestamp,
                    timestamp,
                    timestamp,
                    self._collection,
                ),
            ).fetchone()
        return self._deserialize(row[0]) if row is not None else None

    def list_scoped(
        self, org_id: OpaqueId, workspace_id: Optional[OpaqueId] = None
    ) -> tuple[TContract, ...]:
        query = """SELECT payload FROM product_records
                    WHERE collection = %s AND org_id = %s"""
        params: tuple[object, ...] = (self._collection, str(org_id))
        if workspace_id is not None:
            query += " AND workspace_id = %s"
            params += (str(workspace_id),)
        query += " ORDER BY record_id"
        with self._pool.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)

    def find_by_idempotency_key(
        self,
        key: str,
        requested_by_principal_id: str,
        org_id: OpaqueId,
        workspace_id: OpaqueId,
    ) -> Optional[TContract]:
        with self._pool.connection() as connection:
            row = connection.execute(
                """SELECT payload FROM product_records
                   WHERE collection = %s AND org_id = %s AND workspace_id = %s
                     AND requested_by_principal_id = %s AND idempotency_key = %s""",
                (
                    self._collection,
                    str(org_id),
                    str(workspace_id),
                    requested_by_principal_id,
                    key,
                ),
            ).fetchone()
        return self._deserialize(row[0]) if row is not None else None

    def put_if_status_and_stale(
        self,
        record: TContract,
        *,
        expected_status: str,
        updated_before: datetime,
    ) -> bool:
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            result = connection.execute(
                """UPDATE product_records SET payload = %s, updated_at = %s
                   WHERE collection = %s AND record_id = %s
                     AND payload->>'status' = %s AND updated_at <= %s""",
                (
                    Jsonb(record.model_dump(mode="json")),
                    _updated_at(record),
                    self._collection,
                    self._record_id(record),
                    expected_status,
                    updated_before,
                ),
            )
        return int(result.rowcount) == 1

    def put_if_execution_job_owned(
        self,
        record: TContract,
        *,
        worker_id: str,
        attempts: int,
        expected_status: str = "running",
    ) -> bool:
        """Fence job heartbeat and completion updates to the active claim."""
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            result = connection.execute(
                """UPDATE product_records SET payload = %s, updated_at = %s
                   WHERE collection = %s AND record_id = %s
                     AND payload->>'status' = %s
                     AND payload->>'worker_id' = %s
                     AND (payload->>'attempts')::integer = %s""",
                (
                    Jsonb(record.model_dump(mode="json")),
                    _updated_at(record),
                    self._collection,
                    self._record_id(record),
                    expected_status,
                    worker_id,
                    attempts,
                ),
            )
        return int(result.rowcount) == 1

    def put_if_invitation_pending(
        self, record: TContract, *, expected_token_digest: str
    ) -> bool:
        """Fence invitation acceptance and management to its current token."""
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            result = connection.execute(
                """UPDATE product_records SET payload = %s, updated_at = %s
                   WHERE collection = %s AND record_id = %s
                     AND payload->>'status' = 'pending'
                     AND payload->>'token_digest' = %s""",
                (
                    Jsonb(record.model_dump(mode="json")),
                    _updated_at(record),
                    self._collection,
                    self._record_id(record),
                    expected_token_digest,
                ),
            )
        return int(result.rowcount) == 1

    def _record_id(self, record: TContract) -> str:
        try:
            return str(getattr(record, self._id_field))
        except AttributeError as exc:
            raise TypeError(f"record has no {self._id_field} field") from exc

    @staticmethod
    def _scope(record: TContract, field: str) -> Optional[str]:
        value = getattr(record, field, None)
        return str(value) if value is not None else None

    @staticmethod
    def _clone(record: TContract) -> TContract:
        return type(record).model_validate_json(record.model_dump_json())

    def _deserialize(self, payload: object) -> TContract:
        """Apply strict contract parsing to the JSONB representation."""
        return self._record_type.model_validate_json(json.dumps(payload))
