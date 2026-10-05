"""Repository ports and implementations for local and persistent runtimes."""

import json
from threading import RLock
from typing import Any, Generic, Optional, Protocol, TypeVar

from weaves.product.contracts.v1.base import OpaqueId, ProductContract

TContract = TypeVar("TContract", bound=ProductContract)


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

    def list(self) -> tuple[TContract, ...]: ...

    def list_scoped(
        self, org_id: OpaqueId, workspace_id: Optional[OpaqueId] = None
    ) -> tuple[TContract, ...]: ...


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

    def list(self) -> tuple[TContract, ...]:
        with self._lock:
            return tuple(self._clone(record) for record in self._records.values())

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

    def _record_id(self, record: TContract) -> str:
        try:
            return str(getattr(record, self._id_field))
        except AttributeError as exc:
            raise TypeError(f"record has no {self._id_field} field") from exc

    def _clone(self, record: TContract) -> TContract:
        """Round-trip through the contract serializer for a detached deep copy."""
        return type(record).model_validate_json(record.model_dump_json())


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
                       (collection, record_id, org_id, workspace_id, payload)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (
                        self._collection,
                        record_id,
                        self._scope(record, "org_id"),
                        self._scope(record, "workspace_id"),
                        Jsonb(record.model_dump(mode="json")),
                    ),
                )
        except errors.UniqueViolation as exc:
            raise ValueError(f"{self._id_field} already exists: {record_id}") from exc
        return self._clone(record)

    def put(self, record: TContract) -> TContract:
        from psycopg.types.json import Jsonb

        with self._pool.connection() as connection:
            connection.execute(
                """INSERT INTO product_records
                   (collection, record_id, org_id, workspace_id, payload)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (collection, record_id) DO UPDATE SET
                     org_id = EXCLUDED.org_id,
                     workspace_id = EXCLUDED.workspace_id,
                     payload = EXCLUDED.payload,
                     updated_at = now()""",
                (
                    self._collection,
                    self._record_id(record),
                    self._scope(record, "org_id"),
                    self._scope(record, "workspace_id"),
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

    def list(self) -> tuple[TContract, ...]:
        with self._pool.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM product_records WHERE collection = %s ORDER BY record_id",
                (self._collection,),
            ).fetchall()
        return tuple(self._deserialize(row[0]) for row in rows)

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
